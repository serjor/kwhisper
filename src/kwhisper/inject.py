# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Inyección de texto en la ventana enfocada bajo KWin/Wayland.

Método principal (recomendado): copiar al portapapeles con ``wl-copy`` y simular
``Ctrl+V`` con ``ydotool``. Es el único camino 100% fiable para acentos del
español (ñ, á, ¿, ¡, ü) en KWin, porque el carácter viaja como dato del
portapapeles y solo se simula una combinación fija invariante al layout.

Método alternativo: ``dotool`` con ``DOTOOL_XKB_LAYOUT=es`` (tecleo directo,
no pisa el portapapeles, pero puede fallar con algún signo AltGr).
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

# Keycodes evdev (invariantes al layout) para construir atajos en ydotool.
_KEYCODES = {
    "ctrl": 29, "control": 29, "leftctrl": 29,
    "shift": 42, "leftshift": 42,
    "alt": 56, "leftalt": 56,
    "super": 125, "meta": 125, "win": 125,
    "v": 47,
}

# Clases de ventana (WM_CLASS) que pegan con Ctrl+Shift+V en vez de Ctrl+V.
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
    """'ctrl+shift+v' -> ['29:1','42:1','47:1','47:0','42:0','29:0'] para ydotool."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    codes = []
    for p in parts:
        if p not in _KEYCODES:
            raise InjectionError(f"Tecla desconocida en combinación de pegado: {p!r}")
        codes.append(_KEYCODES[p])
    seq = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
    return seq


class TextInjector:
    def __init__(self, cfg: InjectConfig):
        self.cfg = cfg
        self._have_ydotool = shutil.which("ydotool") is not None
        self._have_wlcopy = shutil.which("wl-copy") is not None
        self._have_dotool = shutil.which("dotool") is not None
        self._detector = WindowDetector()
        # Serializa inyecciones: la restauración diferida del portapapeles lo
        # toma y lo suelta al terminar, de modo que la siguiente inyección
        # espera a que el portapapeles del usuario esté de vuelta.
        self._inject_lock = threading.Lock()
        if cfg.method == "clipboard" and not (self._have_ydotool and self._have_wlcopy):
            log.error("Faltan herramientas: ydotool=%s wl-copy=%s (instala con pacman)",
                      self._have_ydotool, self._have_wlcopy)

    def _is_terminal(self) -> bool:
        if not self.cfg.detect_terminal:
            return False
        return self._detector.active_class() in _TERMINAL_CLASSES

    # --- API principal ---
    def inject(self, text: str) -> None:
        if not text:
            return
        # Tomamos el lock para toda la inyección. El método de portapapeles puede
        # delegar su liberación al hilo de restauración diferida (ver abajo).
        self._inject_lock.acquire()
        if self.cfg.method == "dotool" and self._have_dotool:
            try:
                self._inject_dotool(text)
            finally:
                self._inject_lock.release()
        else:
            self._inject_clipboard(text)  # gestiona la liberación del lock

    def _inject_clipboard(self, text: str) -> None:
        """Pega via portapapeles. Se llama con ``_inject_lock`` TOMADO y
        garantiza liberarlo EXACTAMENTE una vez por CUALQUIER camino: el
        ``finally`` lo suelta salvo que se haya transferido al hilo de
        restauración diferida (que lo soltará él)."""
        lock_transferred = False
        try:
            if not (self._have_ydotool and self._have_wlcopy):
                raise InjectionError(
                    "Inyección por portapapeles requiere 'ydotool' y 'wl-copy'. "
                    "Instala: sudo pacman -S ydotool wl-clipboard"
                )
            env = _ydotool_env()
            # Detectar terminal ANTES de tocar el portapapeles (la ventana
            # enfocada ahora es la de destino; el overlay no roba el foco).
            combo = self.cfg.terminal_paste_key if self._is_terminal() else self.cfg.paste_key
            prev = self._save_clipboard()

            paste_error: Exception | None = None
            try:
                seq = _paste_args(combo)  # puede lanzar si la combinación es inválida
                subprocess.run(["wl-copy"], input=text.encode("utf-8"), check=True)
                time.sleep(0.03)  # margen para que el portapapeles propague
                subprocess.run(["ydotool", "key", *seq], check=True, env=env)
            except subprocess.CalledProcessError as exc:
                paste_error = InjectionError(f"Fallo al pegar: {exc}")
            except Exception as exc:  # noqa: BLE001  (p.ej. tecla inválida en combo)
                paste_error = exc

            # La restauración SIEMPRE ocurre (aunque el pegado fallara), para no
            # dejar el dictado en el portapapeles del usuario.
            if self.cfg.restore_clipboard:
                # Diferida en segundo plano: inject() retorna tras el pegado y el
                # worker libera _processing sin esperar restore_delay; el lock lo
                # suelta el hilo de restauración. Si el arranque del hilo falla
                # (p.ej. RuntimeError al agotar hilos), restauramos en línea y
                # dejamos que el finally libere el lock (sin transferirlo).
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
        # dotool lee una orden por línea de stdin: un texto con saltos rompería
        # el parseo (las líneas siguientes se tomarían como comandos). Troceamos:
        # cada línea se teclea con `type` y los saltos se envían como Return.
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

    # --- portapapeles ---
    def _save_clipboard(self) -> tuple[bytes | None, str | None, bool]:
        """Devuelve (datos, mime, ok). ok=False si NO se pudo leer (timeout/error):
        en ese caso no se restaurará, para no borrar lo que el usuario tuviera
        (p.ej. una imagen grande que tardó más que el timeout)."""
        try:
            mime = ""
            types = subprocess.run(["wl-paste", "--list-types"],
                                   capture_output=True, text=True, timeout=3)
            if types.returncode == 0 and types.stdout.strip():
                mime = types.stdout.strip().splitlines()[0].strip()
            cmd = ["wl-paste", "-n", *(["-t", mime] if mime else [])]
            out = subprocess.run(cmd, capture_output=True, timeout=10)
            if out.returncode != 0:
                return (None, None, True)  # portapapeles vacío (confirmado)
            return (out.stdout, mime or None, True)
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("No se pudo leer el portapapeles (%s); no se restaurará "
                        "para no perder su contenido.", exc)
            return (None, None, False)

    def _restore_clipboard(self, saved: tuple[bytes | None, str | None, bool]) -> None:
        data, mime, ok = saved
        if not ok:
            return  # no sabemos qué había → no tocar (mejor que borrar)
        try:
            if data:
                subprocess.run(["wl-copy", *(["-t", mime] if mime else [])],
                               input=data, check=False)
            else:
                subprocess.run(["wl-copy", "--clear"], check=False)
        except Exception as exc:  # noqa: BLE001
            log.debug("No se pudo restaurar el portapapeles: %s", exc)
