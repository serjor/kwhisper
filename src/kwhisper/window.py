# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Detección de la clase de la ventana enfocada bajo KWin/Wayland.

Se usa para decidir si pegar con Ctrl+V (apps normales) o Ctrl+Shift+V
(terminales). Dos backends, en orden de preferencia:

1. ``kdotool`` si está instalado (AUR) — la vía más directa.
2. KWin vía D-Bus (sin AUR): carga un script de KWin que imprime la
   ``resourceClass`` de ``workspace.activeWindow`` y se lee del journal. Usa solo
   herramientas de KDE (``gdbus`` + ``journalctl``), ya presentes en Plasma.

Si ninguno funciona, devuelve "" (clase desconocida → se usa el atajo por defecto).
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import subprocess
import time
from datetime import datetime

log = logging.getLogger(__name__)

_KWIN_SERVICE = "org.kde.KWin"
_KWIN_SCRIPTING = "/Scripting"
_PLUGIN = "kwhisper-activewindow"
_MARKER = "KWHISPER_AW:"


def _build_script(nonce: str) -> str:
    # El nonce hace inequívoco el marcador en el journal (que solo tiene
    # resolución de 1 s): así no se lee el resultado de una consulta anterior
    # ocurrida dentro del mismo segundo.
    return (
        "var w = workspace.activeWindow;\n"
        'print("' + _MARKER + nonce + ':" + (w ? w.resourceClass : "none"));\n'
    )


class WindowDetector:
    def __init__(self):
        self._kdotool = shutil.which("kdotool")
        self._gdbus = shutil.which("gdbus")
        self._journalctl = shutil.which("journalctl")
        self._kwin_failed = False
        self._kwin_misses = 0

    @property
    def backend(self) -> str:
        if self._kdotool:
            return "kdotool"
        if self._gdbus and self._journalctl and not self._kwin_failed:
            return "kwin-dbus"
        return "ninguno"

    def active_class(self) -> str:
        """Clase (resourceClass) de la ventana enfocada, en minúsculas, o ""."""
        if self._kdotool:
            cls = self._via_kdotool()
            if cls is not None:
                return cls
        if self._gdbus and self._journalctl and not self._kwin_failed:
            cls = self._via_kwin()
            if cls is not None:
                return cls
        return ""

    # --- backend kdotool ---
    def _via_kdotool(self) -> str | None:
        try:
            wid = subprocess.run(["kdotool", "getactivewindow"],
                                 capture_output=True, text=True, timeout=2).stdout.strip()
            if not wid:
                return None
            cls = subprocess.run(["kdotool", "getwindowclassname", wid],
                                 capture_output=True, text=True, timeout=2).stdout.strip()
            return cls.lower()
        except Exception as exc:  # noqa: BLE001
            log.debug("kdotool falló: %s", exc)
            return None

    # --- backend KWin D-Bus (sin AUR) ---
    # Nota: KWin no re-ejecuta un script ya cargado al llamar run() otra vez, así
    # que recargamos (unload + load + run) en CADA consulta. Es barato (~60-120ms).
    def _load_script(self, script_text: str) -> int | None:
        # El script se escribe SOLO en XDG_RUNTIME_DIR (directorio privado del
        # usuario, 0700). No caemos a /tmp: un fichero de nombre predecible ahí
        # podría ser pre-creado/symlinkeado por otro usuario y KWin acabaría
        # ejecutando JS ajeno en tu sesión.
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime_dir:
            log.debug("XDG_RUNTIME_DIR no definido; no se carga el script de KWin.")
            return None
        try:
            path = os.path.join(runtime_dir, "kwhisper-activewindow.js")
            # O_NOFOLLOW + 0600: no seguir symlinks y solo el usuario lee/escribe.
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
            with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as fh:
                fh.write(script_text)
            subprocess.run(["gdbus", "call", "--session", "--dest", _KWIN_SERVICE,
                            "--object-path", _KWIN_SCRIPTING,
                            "--method", "org.kde.kwin.Scripting.unloadScript", _PLUGIN],
                           capture_output=True, timeout=3)
            out = subprocess.run(["gdbus", "call", "--session", "--dest", _KWIN_SERVICE,
                                  "--object-path", _KWIN_SCRIPTING,
                                  "--method", "org.kde.kwin.Scripting.loadScript", path, _PLUGIN],
                                 capture_output=True, text=True, timeout=3)
            m = re.search(r"-?\d+", out.stdout)
            if not m or int(m.group()) < 0:
                log.debug("loadScript no devolvió id válido: %r", out.stdout)
                return None
            return int(m.group())
        except Exception as exc:  # noqa: BLE001
            log.debug("No se pudo cargar el script de KWin: %s", exc)
            return None

    def _via_kwin(self) -> str | None:
        nonce = secrets.token_hex(4)
        sid = self._load_script(_build_script(nonce))
        if sid is None:
            self._note_fail()
            return None
        since = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            subprocess.run(["gdbus", "call", "--session", "--dest", _KWIN_SERVICE,
                            "--object-path", f"{_KWIN_SCRIPTING}/Script{sid}",
                            "--method", "org.kde.kwin.Script.run"],
                           capture_output=True, timeout=3)
        except Exception as exc:  # noqa: BLE001
            log.debug("run() del script KWin falló: %s", exc)
            self._note_fail()
            return None
        # El print llega al journal con un pequeño retardo: sondear brevemente.
        for _ in range(8):
            time.sleep(0.05)
            cls = self._read_journal(since, nonce)
            if cls is not None:
                self._kwin_misses = 0
                return cls
        self._note_fail()
        return None

    def _note_fail(self) -> None:
        self._kwin_misses += 1
        if self._kwin_misses >= 3:
            self._kwin_failed = True
            log.warning("Detección de terminal por KWin desactivada tras varios "
                        "fallos; se usará el atajo de pegado por defecto.")

    def _read_journal(self, since: str, nonce: str) -> str | None:
        try:
            out = subprocess.run(
                ["journalctl", "_COMM=kwin_wayland", "--since", since, "-o", "cat", "--no-pager"],
                capture_output=True, text=True, timeout=2).stdout
        except Exception:  # noqa: BLE001
            return None
        marker = _MARKER + nonce + ":"
        last = None
        for line in out.splitlines():
            i = line.find(marker)
            if i != -1:
                last = line[i + len(marker):].strip()
        if last is None:
            return None
        if last == "none":
            return ""
        return last.lower()
