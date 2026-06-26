# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Voice command executor (whitelist of safe actions).

Only executes the actions the classifier can emit:
* ``abrir_app``    → launches a program (if allowed in config).
* ``pulsar_tecla`` → sends a key combination with ydotool.
* ``ninguna``      → does nothing.

By design it does NOT execute arbitrary shell commands dictated by voice.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from .config import CommandsConfig
from .llm import Intent

log = logging.getLogger(__name__)

_KEY_ALIASES = {
    "ctrl": "KEY_LEFTCTRL", "control": "KEY_LEFTCTRL",
    "shift": "KEY_LEFTSHIFT", "alt": "KEY_LEFTALT",
    "super": "KEY_LEFTMETA", "meta": "KEY_LEFTMETA", "win": "KEY_LEFTMETA",
    "enter": "KEY_ENTER", "return": "KEY_ENTER", "intro": "KEY_ENTER",
    "esc": "KEY_ESC", "escape": "KEY_ESC",
    "space": "KEY_SPACE", "espacio": "KEY_SPACE", "tab": "KEY_TAB",
    "del": "KEY_DELETE", "delete": "KEY_DELETE", "supr": "KEY_DELETE",
    "backspace": "KEY_BACKSPACE", "retroceso": "KEY_BACKSPACE",
    "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
    "home": "KEY_HOME", "end": "KEY_END", "pageup": "KEY_PAGEUP", "pagedown": "KEY_PAGEDOWN",
}


class CommandExecutor:
    def __init__(self, cfg: CommandsConfig):
        self.cfg = cfg
        self._procs: list[subprocess.Popen] = []

    def _spawn(self, args: list[str]) -> None:
        # Launches detached and keeps the reference, pruning the already finished
        # ones (avoids zombies without losing the Popen).
        self._procs = [p for p in self._procs if p.poll() is None]
        self._procs.append(subprocess.Popen(
            args, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def execute(self, intent: Intent) -> str:
        """Execute the intent's action. Returns a human-readable result message."""
        if intent.accion == "abrir_app":
            return self._open_app(intent.argumento)
        if intent.accion == "pulsar_tecla":
            return self._press_key(intent.argumento)
        return "Sin acción."

    def _open_app(self, name: str) -> str:
        name = (name or "").strip()
        if not name:
            return "Comando 'abrir' sin aplicación."
        if not self.cfg.allow_launch:
            return "Lanzar aplicaciones está desactivado en la config."
        # Only the first token: we launch the binary WITHOUT extra arguments that
        # the transcription could sneak in (e.g. dangerous flags to a binary).
        binary = name.split()[0]
        try:
            if shutil.which(binary):
                self._spawn([binary])
                return f"Abriendo {binary}"
            # Fallback: launcher via .desktop (KDE/GTK).
            if shutil.which("kstart"):
                self._spawn(["kstart", binary])
                return f"Abriendo {binary} (kstart)"
            if shutil.which("gtk-launch"):
                self._spawn(["gtk-launch", binary])
                return f"Abriendo {binary} (gtk-launch)"
            return f"No encuentro la aplicación '{binary}'."
        except Exception as exc:  # noqa: BLE001
            log.exception("Fallo al abrir %s", name)
            return f"Error al abrir {name}: {exc}"

    def _press_key(self, combo: str) -> str:
        combo = (combo or "").strip()
        if not combo:
            return "Comando 'pulsar' sin tecla."
        try:
            from evdev import ecodes
        except ImportError:
            return "python-evdev no disponible para resolver teclas."
        tokens = [t for t in combo.replace(" ", "").lower().split("+") if t]
        codes: list[int] = []
        for t in tokens:
            key_name = _KEY_ALIASES.get(t, f"KEY_{t.upper()}")
            code = ecodes.ecodes.get(key_name)
            if code is None:
                return f"Tecla desconocida: {t!r}"
            codes.append(code)
        seq = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
        env = dict(os.environ)
        env.setdefault("YDOTOOL_SOCKET", f"/run/user/{os.getuid()}/.ydotool_socket")
        try:
            subprocess.run(["ydotool", "key", *seq], check=True, env=env,
                           capture_output=True)
            return f"Pulsado {combo}"
        except subprocess.CalledProcessError as exc:
            return f"Fallo al pulsar {combo}: {exc}"
        except FileNotFoundError:
            return "ydotool no instalado."
