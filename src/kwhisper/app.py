# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Entry point of the kwhisper daemon: ties hotkey → audio → STT → LLM → action.

Threading model:
* Qt thread (main): tray and overlay (all the UI).
* Hotkey thread (evdev/portal): detects press/release.
* Ephemeral per-phrase worker thread: STT + classification + injection/command.

Communication toward the UI goes through Qt signals (queued delivery to the Qt thread).
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time

from .config import CONFIG_PATH, Config, load_config

log = logging.getLogger("kwhisper")


class KWhisper:
    def __init__(self, cfg: Config):
        from PySide6.QtCore import QObject, Signal

        self.cfg = cfg
        self.enabled = True
        self._recording = False
        self._processing = False
        # Serializes state transitions between the hotkey thread and the worker.
        self._lock = threading.Lock()
        self.stt_ready = threading.Event()

        # --- UI signals ---
        class _Ctrl(QObject):
            state = Signal(str)
            overlay = Signal(str, str)
            notify = Signal(str, str)
        self.ctrl = _Ctrl()

        # --- components (without importing Qt here) ---
        from .audio import AudioRecorder
        from .commands import CommandExecutor
        from .feedback import Feedback
        from .inject import TextInjector
        from .llm import IntentRouter
        from .stt import STTEngine

        self.recorder = AudioRecorder(cfg.audio.samplerate, cfg.audio.channels, cfg.audio.device)
        self.stt = STTEngine(cfg.stt)
        self.router = IntentRouter(cfg.llm) if cfg.llm.enabled else None
        self.injector = TextInjector(cfg.inject)
        self.executor = CommandExecutor(cfg.commands)
        self.feedback = Feedback(cfg.ui)
        self._listener = None
        self._quitting = False
        # Created by setup_ui() based on cfg.ui.overlay; defaulted here so the
        # attribute always exists (the worker checks it before injecting).
        self.overlay = None

    # ---------- lifecycle ----------
    def setup_ui(self) -> None:
        from .overlay import Overlay
        from .tray import Tray

        self.overlay = Overlay() if self.cfg.ui.overlay else None
        self.tray = Tray(self._on_toggle_enabled, self._on_open_config, self._on_quit)

        self.ctrl.state.connect(self.tray.set_state)
        self.ctrl.notify.connect(self._do_notify)
        if self.overlay is not None:
            self.ctrl.overlay.connect(self._do_overlay)

    def _do_overlay(self, state: str, text: str) -> None:
        if not self.overlay:
            return
        if state:
            self.overlay.show_state(state, text)
        else:
            self.overlay.hide_overlay()

    def _do_notify(self, title: str, msg: str) -> None:
        if self.cfg.ui.notifications:
            self.tray.notify(title, msg)

    def _hide_overlay_before_inject(self) -> None:
        """Hide the overlay and yield a margin before injecting the text.

        Under KWin Wayland the overlay may grab keyboard focus despite its
        no-activation flags; if it is still visible when pasting, the Ctrl+Shift+V
        ends up in the overlay (which ignores it) and nothing is pasted. We hide
        it first and wait a moment for the compositor to return focus to the
        target window. The emit is delivered in a queue to the Qt thread, so the
        brief wait gives the hide time to actually be processed before the paste.
        """
        if self.overlay is None:
            return
        self.ctrl.overlay.emit("", "")
        time.sleep(0.12)

    def start_listener(self) -> None:
        if self.cfg.hotkey.backend == "portal":
            from .hotkey.portal_listener import PortalListener
            self._listener = PortalListener(
                self._on_start, self._on_stop,
                on_error=lambda m: self.ctrl.notify.emit("kwhisper", m),
            )
        else:
            from .hotkey.evdev_listener import EvdevListener, HotkeyPermissionError
            self._listener = EvdevListener(
                self.cfg.hotkey.key, self._on_start, self._on_stop, self.cfg.hotkey.device,
            )
            try:
                self._listener.start()
                return
            except HotkeyPermissionError as exc:
                log.error("%s", exc)
                self.ctrl.notify.emit("kwhisper", "Sin permiso de teclado (grupo input). "
                                                  "Mira los logs o usa backend=portal.")
                return
            except ValueError as exc:  # unknown key in config
                log.error("%s", exc)
                self.ctrl.notify.emit("kwhisper", str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("No se pudo iniciar el hotkey evdev: %s", exc)
                self.ctrl.notify.emit("kwhisper", "No se pudo iniciar el hotkey. Revisa los logs.")
                return
        self._listener.start()

    def load_model_async(self) -> None:
        def _load() -> None:
            self.ctrl.state.emit("processing")
            try:
                self.stt.load()
                self.stt_ready.set()
                self.ctrl.state.emit("idle")
                self.ctrl.notify.emit("kwhisper", "Listo para dictar.")
            except Exception as exc:  # noqa: BLE001
                log.exception("Fallo cargando el modelo STT")
                self.ctrl.state.emit("error")
                self.ctrl.notify.emit("kwhisper", f"Error cargando STT: {exc}")
        threading.Thread(target=_load, name="stt-load", daemon=True).start()

    # ---------- hotkey callbacks (listener thread) ----------
    # Return True only if the transition actually happened. The portal listener
    # (toggle mode) uses that value to avoid desyncing its state when the
    # recording is rejected (busy/disabled). The evdev one ignores it.
    def _on_start(self) -> bool:
        with self._lock:
            if not self.enabled or self._recording or self._processing:
                return False
            self._recording = True
        try:
            self.recorder.start()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._recording = False
            log.exception("No se pudo iniciar la grabación")
            self.ctrl.notify.emit("kwhisper", f"Error de micrófono: {exc}")
            return False
        self.feedback.play("start")
        self.ctrl.overlay.emit("recording", "🎙  Grabando…")
        self.ctrl.state.emit("recording")
        return True

    def _on_stop(self) -> bool:
        with self._lock:
            if not self._recording:
                return False
            self._recording = False
            # Set EARLY under lock: closes the TOCTOU window so a new
            # push-to-talk does not start a second recording while we process.
            self._processing = True
        audio = self.recorder.stop()
        self.feedback.play("stop")
        self.ctrl.overlay.emit("processing", "⏳  Procesando…")
        self.ctrl.state.emit("processing")
        threading.Thread(target=self._process, args=(audio,),
                         name="kwhisper-process", daemon=True).start()
        return True

    # ---------- pipeline (worker thread) ----------
    def _process(self, audio) -> None:  # noqa: ANN001
        try:
            dur = self.recorder.duration(audio)
            if dur < 0.25:
                self.ctrl.notify.emit("kwhisper", "Grabación demasiado corta.")
                return
            if not self.stt_ready.wait(timeout=30):
                self.ctrl.notify.emit("kwhisper", "El modelo aún se está cargando.")
                return
            text = self.stt.transcribe(audio)
            if not text:
                self.ctrl.notify.emit("kwhisper", "No se detectó voz.")
                return

            # With the LLM active (router != None) we ALWAYS classify: that way
            # dictation gains punctuation/capitalization correction even if
            # command execution is disabled.
            if self.router is not None:
                intent = self.router.classify(text)
            else:
                from .llm import Intent
                intent = Intent(tipo="dictado", texto=text)

            # Execute the command only if they are enabled; otherwise (or if it
            # is dictation, or a command with execution disabled) text is written.
            if intent.tipo == "comando" and self.cfg.commands.enabled:
                msg = self.executor.execute(intent)
                self.ctrl.notify.emit("Comando", msg)
            else:
                # Hide the overlay BEFORE injecting so it does not keep the
                # keyboard focus under KWin Wayland (otherwise the Ctrl+Shift+V
                # would go to the overlay and nothing would be pasted in the target window).
                self._hide_overlay_before_inject()
                self.injector.inject(intent.texto or text)
        except Exception as exc:  # noqa: BLE001
            log.exception("Error en el pipeline")
            self.ctrl.overlay.emit("error", "⚠  Error")
            self.ctrl.notify.emit("kwhisper", f"Error: {exc}")
        finally:
            # Emit the UI state BEFORE releasing the guard: while
            # _processing stays True, _on_start cannot start a new recording,
            # so a later "recording" is always posted afterwards.
            self.ctrl.overlay.emit("", "")
            self.ctrl.state.emit("idle" if self.enabled else "disabled")
            with self._lock:
                self._processing = False

    # ---------- menu actions ----------
    def _on_toggle_enabled(self, checked: bool) -> None:
        self.enabled = checked
        self.ctrl.state.emit("idle" if checked else "disabled")
        # Explicit feedback: without this the only hint is the tray icon (which
        # depends on the theme) and it looks like the checkbox does nothing.
        self.ctrl.notify.emit("kwhisper",
                              "Dictado activado" if checked else "Dictado desactivado")

    def _on_open_config(self) -> None:
        try:
            # We keep the reference so we don't lose the Popen (and so the
            # finished child gets reaped on the next launch).
            self._cfg_proc = subprocess.Popen(
                ["xdg-open", str(CONFIG_PATH)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo abrir la config")

    def _on_quit(self) -> None:
        from PySide6.QtWidgets import QApplication
        if self._quitting:  # reentrant-safe: a 2nd signal does not repeat the shutdown
            return
        self._quitting = True
        if self._listener:
            self._listener.stop()
        if self.router:
            self.router.close()
        QApplication.quit()


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("KWHISPER_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()
    # Under systemd --user the session bus may not be in the environment: without it
    # terminal detection (KWin/gdbus) fails and it pastes with Ctrl+V in konsole.
    from .window import ensure_session_bus
    ensure_session_bus()
    if cfg.stt.device == "cuda":
        from .stt import ensure_cuda_lib_path
        ensure_cuda_lib_path()

    from PySide6.QtWidgets import QApplication

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("kwhisper")
    qapp.setQuitOnLastWindowClosed(False)

    app = KWhisper(cfg)
    app.setup_ui()
    app.load_model_async()
    app.start_listener()

    from PySide6.QtCore import QTimer

    # Ctrl+C (SIGINT) and `systemctl --user stop` (SIGTERM) must stop the daemon
    # cleanly. qapp.exec() blocks the interpreter in C++, so:
    #  1) we register Python handlers that route to the clean shutdown (_on_quit), and
    #  2) a periodic no-op QTimer returns control to the interpreter so the
    #     signal is handled and the queued quit wakes up the event loop.
    def _signal_shutdown(signum, _frame):  # noqa: ANN001
        log.info("Señal %s recibida; cerrando kwhisper.", signal.Signals(signum).name)
        app._on_quit()

    signal.signal(signal.SIGINT, _signal_shutdown)
    signal.signal(signal.SIGTERM, _signal_shutdown)

    wake_timer = QTimer()
    wake_timer.timeout.connect(lambda: None)  # yields control to the Python interpreter
    wake_timer.start(200)

    log.info("kwhisper en marcha. Backend hotkey=%s, tecla=%s",
             cfg.hotkey.backend, cfg.hotkey.key)
    return qapp.exec()


if __name__ == "__main__":
    raise SystemExit(main())
