"""Punto de entrada del daemon kwhisper: une hotkey → audio → STT → LLM → acción.

Modelo de hilos:
* Hilo Qt (principal): bandeja y overlay (toda la UI).
* Hilo del hotkey (evdev/portal): detecta pulsar/soltar.
* Hilo worker efímero por frase: STT + clasificación + inyección/comando.

La comunicación hacia la UI va por señales Qt (entrega en cola al hilo Qt).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading

from .config import CONFIG_PATH, Config, load_config

log = logging.getLogger("kwhisper")


class KWhisper:
    def __init__(self, cfg: Config):
        from PySide6.QtCore import QObject, Signal

        self.cfg = cfg
        self.enabled = True
        self._recording = False
        self._processing = False
        # Serializa las transiciones de estado entre el hilo del hotkey y el worker.
        self._lock = threading.Lock()
        self.stt_ready = threading.Event()

        # --- señales UI ---
        class _Ctrl(QObject):
            state = Signal(str)
            overlay = Signal(str, str)
            notify = Signal(str, str)
        self.ctrl = _Ctrl()

        # --- componentes (sin importar Qt aquí) ---
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

    # ---------- ciclo de vida ----------
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
            except ValueError as exc:  # tecla desconocida en config
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

    # ---------- callbacks del hotkey (hilo del listener) ----------
    # Devuelven True solo si la transición ocurrió de verdad. El listener del
    # portal (modo toggle) usa ese valor para no desincronizar su estado cuando
    # la grabación se rechaza (ocupado/deshabilitado). El evdev lo ignora.
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
            # Set TEMPRANO bajo lock: cierra la ventana TOCTOU para que un nuevo
            # push-to-talk no arranque una segunda grabación mientras procesamos.
            self._processing = True
        audio = self.recorder.stop()
        self.feedback.play("stop")
        self.ctrl.overlay.emit("processing", "⏳  Procesando…")
        self.ctrl.state.emit("processing")
        threading.Thread(target=self._process, args=(audio,),
                         name="kwhisper-process", daemon=True).start()
        return True

    # ---------- pipeline (hilo worker) ----------
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

            # Con el LLM activo (router != None) clasificamos SIEMPRE: así el
            # dictado gana corrección de puntuación/mayúsculas aunque la
            # ejecución de comandos esté desactivada.
            if self.router is not None:
                intent = self.router.classify(text)
            else:
                from .llm import Intent
                intent = Intent(tipo="dictado", texto=text)

            # Ejecutar comando solo si están habilitados; si no (o si es
            # dictado, o un comando con ejecución desactivada) se escribe texto.
            if intent.tipo == "comando" and self.cfg.commands.enabled:
                msg = self.executor.execute(intent)
                self.ctrl.notify.emit("Comando", msg)
            else:
                self.injector.inject(intent.texto or text)
        except Exception as exc:  # noqa: BLE001
            log.exception("Error en el pipeline")
            self.ctrl.overlay.emit("error", "⚠  Error")
            self.ctrl.notify.emit("kwhisper", f"Error: {exc}")
        finally:
            # Emitir el estado de UI ANTES de soltar el guard: mientras
            # _processing siga True, _on_start no puede arrancar una grabación
            # nueva, así que un "recording" posterior se postea siempre después.
            self.ctrl.overlay.emit("", "")
            self.ctrl.state.emit("idle" if self.enabled else "disabled")
            with self._lock:
                self._processing = False

    # ---------- acciones del menú ----------
    def _on_toggle_enabled(self, checked: bool) -> None:
        self.enabled = checked
        self.ctrl.state.emit("idle" if checked else "disabled")

    def _on_open_config(self) -> None:
        try:
            # Guardamos la referencia para no perder el Popen (y que se recolecte
            # el hijo terminado en el siguiente arranque).
            self._cfg_proc = subprocess.Popen(
                ["xdg-open", str(CONFIG_PATH)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo abrir la config")

    def _on_quit(self) -> None:
        from PySide6.QtWidgets import QApplication
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

    log.info("kwhisper en marcha. Backend hotkey=%s, tecla=%s",
             cfg.hotkey.backend, cfg.hotkey.key)
    return qapp.exec()


if __name__ == "__main__":
    raise SystemExit(main())
