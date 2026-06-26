# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Text injection into the focused window under KWin/Wayland.

Primary method (recommended): copy to the clipboard with ``wl-copy`` and
simulate ``Ctrl+V`` with ``ydotool``. This is the only 100% reliable path for
Spanish accents (ñ, á, ¿, ¡, ü) in KWin, because the character travels as
clipboard data and only a fixed, layout-invariant key combination is simulated.

Alternative method: ``dotool`` with ``DOTOOL_XKB_LAYOUT=es`` (direct typing,
does not clobber the clipboard, but may fail with some AltGr symbols).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time

from .config import InjectConfig
from .window import WindowDetector

log = logging.getLogger(__name__)

# evdev keycodes (layout-invariant) for building ydotool shortcuts.
_KEYCODES = {
    "ctrl": 29, "control": 29, "leftctrl": 29,
    "shift": 42, "leftshift": 42,
    "alt": 56, "leftalt": 56,
    "super": 125, "meta": 125, "win": 125,
    "v": 47,
}

# Window classes (WM_CLASS) that paste with Ctrl+Shift+V instead of Ctrl+V.
_TERMINAL_CLASSES = {
    "konsole", "yakuake", "alacritty", "kitty", "wezterm", "org.wezfurlong.wezterm",
    "foot", "footclient", "gnome-terminal", "xterm", "st", "terminator", "tilix",
    "qterminal", "deepin-terminal", "blackbox", "ghostty",
}


class InjectionError(RuntimeError):
    pass


def _ydotool_env() -> dict[str, str]:
    env = dict(os.environ)
    if "YDOTOOL_SOCKET" not in env:
        uid = os.getuid()
        env["YDOTOOL_SOCKET"] = f"/run/user/{uid}/.ydotool_socket"
    return env


def _paste_args(combo: str) -> list[str]:
    """'ctrl+shift+v' -> ['29:1','42:1','47:1','47:0','42:0','29:0'] for ydotool."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    codes = []
    for p in parts:
        if p not in _KEYCODES:
            raise InjectionError(f"Tecla desconocida en combinación de pegado: {p!r}")
        codes.append(_KEYCODES[p])
    seq = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
    return seq


def _pick_clipboard_type(types_text: str) -> str:
    """Choose the MIME type to save/restore from ``wl-paste --list-types`` output.

    Prefers plain text over ``text/html``: restoring with ``wl-copy -t text/html``
    makes ``wl-copy`` offer that HTML under ALL text aliases (``text/plain``
    included), and then konsole pastes the raw HTML instead of the text. If there
    is no plain text, it falls back to the first offered type, to preserve images
    or other non-textual content.
    """
    types = [t.strip() for t in types_text.splitlines() if t.strip()]
    for t in types:
        if t.lower().startswith("text/plain"):
            return t
    return types[0] if types else ""


class TextInjector:
    def __init__(self, cfg: InjectConfig):
        self.cfg = cfg
        self._have_ydotool = shutil.which("ydotool") is not None
        self._have_wlcopy = shutil.which("wl-copy") is not None
        self._have_dotool = shutil.which("dotool") is not None
        self._detector = WindowDetector()
        # Serialize injections: the deferred clipboard restore acquires it and
        # releases it when done, so the next injection waits until the user's
        # clipboard is back.
        self._inject_lock = threading.Lock()
        if cfg.method == "clipboard" and not (self._have_ydotool and self._have_wlcopy):
            log.error("Faltan herramientas: ydotool=%s wl-copy=%s (instala con pacman)",
                      self._have_ydotool, self._have_wlcopy)

    def _is_terminal(self) -> bool:
        if not self.cfg.detect_terminal:
            return False
        return self._detector.active_class() in _TERMINAL_CLASSES

    # --- main API ---
    def inject(self, text: str) -> None:
        if not text:
            return
        # We hold the lock for the entire injection. The clipboard method may
        # delegate its release to the deferred restore thread (see below).
        self._inject_lock.acquire()
        if self.cfg.method == "dotool" and self._have_dotool:
            try:
                self._inject_dotool(text)
            finally:
                self._inject_lock.release()
        else:
            self._inject_clipboard(text)  # manages releasing the lock

    def _inject_clipboard(self, text: str) -> None:
        """Paste via clipboard. Called with ``_inject_lock`` HELD and guarantees
        releasing it EXACTLY once on ANY path: the ``finally`` releases it unless
        it has been transferred to the deferred restore thread (which will then
        release it)."""
        lock_transferred = False
        try:
            if not (self._have_ydotool and self._have_wlcopy):
                raise InjectionError(
                    "Inyección por portapapeles requiere 'ydotool' y 'wl-copy'. "
                    "Instala: sudo pacman -S ydotool wl-clipboard"
                )
            env = _ydotool_env()
            # Detect the terminal BEFORE touching the clipboard (the focused
            # window is now the target one; the overlay does not steal focus).
            combo = self.cfg.terminal_paste_key if self._is_terminal() else self.cfg.paste_key
            prev = self._save_clipboard()

            paste_error: Exception | None = None
            try:
                seq = _paste_args(combo)  # may raise if the combination is invalid
                subprocess.run(["wl-copy"], input=text.encode("utf-8"), check=True)
                time.sleep(0.03)  # margin for the clipboard to propagate
                subprocess.run(["ydotool", "key", *seq], check=True, env=env)
            except subprocess.CalledProcessError as exc:
                paste_error = InjectionError(f"Fallo al pegar: {exc}")
            except Exception as exc:  # noqa: BLE001  (e.g. invalid key in combo)
                paste_error = exc

            # Restoration ALWAYS happens (even if the paste failed), so as not to
            # leave the dictation in the user's clipboard.
            if self.cfg.restore_clipboard:
                # Deferred in the background: inject() returns after the paste and
                # the worker frees _processing without waiting for restore_delay;
                # the lock is released by the restore thread. If starting the
                # thread fails (e.g. RuntimeError when threads are exhausted), we
                # restore inline and let the finally release the lock (without
                # transferring it).
                t = threading.Thread(target=self._delayed_restore, args=(prev,),
                                     name="clip-restore", daemon=True)
                try:
                    t.start()
                except Exception:  # noqa: BLE001
                    log.warning("No se pudo lanzar el hilo de restauración; "
                                "restaurando el portapapeles en línea.")
                    self._restore_clipboard(prev)
                else:
                    lock_transferred = True

            if paste_error is not None:
                raise paste_error
        finally:
            if not lock_transferred:
                self._inject_lock.release()

    def _delayed_restore(self, prev: tuple[bytes | None, str | None, bool]) -> None:
        try:
            time.sleep(self.cfg.restore_delay)
            self._restore_clipboard(prev)
        finally:
            self._inject_lock.release()

    def _inject_dotool(self, text: str) -> None:
        env = dict(os.environ)
        env.setdefault("DOTOOL_XKB_LAYOUT", "es")
        # dotool reads one command per line from stdin: text with newlines would
        # break the parsing (subsequent lines would be taken as commands). We
        # split it up: each line is typed with `type` and newlines are sent as
        # Return.
        cmds: list[str] = []
        for i, line in enumerate(text.split("\n")):
            if i:
                cmds.append("key Return")
            if line:
                cmds.append(f"type {line}")
        script = "\n".join(cmds)
        if not script:
            return
        try:
            subprocess.run(["dotool"], input=script.encode("utf-8"),
                           check=True, env=env)
        except subprocess.CalledProcessError as exc:
            raise InjectionError(f"dotool falló: {exc}") from exc

    # --- clipboard ---
    def _save_clipboard(self) -> tuple[bytes | None, str | None, bool]:
        """Returns (data, mime, ok). ok=False if it could NOT be read (timeout/error):
        in that case it won't be restored, so as not to erase whatever the user
        had (e.g. a large image that took longer than the timeout)."""
        try:
            mime = ""
            types = subprocess.run(["wl-paste", "--list-types"],
                                   capture_output=True, text=True, timeout=3)
            if types.returncode == 0 and types.stdout.strip():
                mime = _pick_clipboard_type(types.stdout)
            cmd = ["wl-paste", "-n", *(["-t", mime] if mime else [])]
            out = subprocess.run(cmd, capture_output=True, timeout=10)
            if out.returncode != 0:
                return (None, None, True)  # empty clipboard (confirmed)
            return (out.stdout, mime or None, True)
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("No se pudo leer el portapapeles (%s); no se restaurará "
                        "para no perder su contenido.", exc)
            return (None, None, False)

    def _restore_clipboard(self, saved: tuple[bytes | None, str | None, bool]) -> None:
        data, mime, ok = saved
        if not ok:
            return  # we don't know what was there → don't touch (better than erasing)
        try:
            if data:
                subprocess.run(["wl-copy", *(["-t", mime] if mime else [])],
                               input=data, check=False)
            else:
                subprocess.run(["wl-copy", "--clear"], check=False)
        except Exception as exc:  # noqa: BLE001
            log.debug("No se pudo restaurar el portapapeles: %s", exc)
