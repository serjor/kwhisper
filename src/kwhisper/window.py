# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Detection of the focused window's class under KWin/Wayland.

Used to decide whether to paste with Ctrl+V (normal apps) or Ctrl+Shift+V
(terminals). Two backends, in order of preference:

1. ``kdotool`` if installed (AUR) — the most direct route.
2. KWin via D-Bus (no AUR): loads a KWin script that prints the
   ``resourceClass`` of ``workspace.activeWindow`` and reads it from the journal.
   Uses only KDE tools (``gdbus`` + ``journalctl``), already present in Plasma.

If neither works, returns "" (unknown class → the default shortcut is used).
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


def ensure_session_bus() -> None:
    """Ensures ``DBUS_SESSION_BUS_ADDRESS`` so that ``gdbus --session`` can reach
    KWin when kwhisper starts as a user service.

    systemd ``--user`` does not always propagate this variable to the unit's
    environment (the ``import-environment`` list is limited), and without it the
    terminal detection fails silently: it ends up pasting with ``Ctrl+V`` in
    konsole, which does not paste. The user's session bus reliably lives at
    ``$XDG_RUNTIME_DIR/bus``; we set it if missing. Idempotent and cheap: just like
    ``inject._ydotool_env`` derives ``YDOTOOL_SOCKET`` from ``XDG_RUNTIME_DIR``.
    """
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        log.debug("XDG_RUNTIME_DIR no definido; no se puede derivar el bus de sesión.")
        return
    sock = os.path.join(runtime_dir, "bus")
    if os.path.exists(sock):
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={sock}"
        log.debug("DBUS_SESSION_BUS_ADDRESS no estaba definido; usando %s", sock)


def _build_script(nonce: str) -> str:
    # The nonce makes the marker unambiguous in the journal (which only has
    # 1 s resolution): this way we don't read the result of a previous query
    # that happened within the same second.
    return (
        "var w = workspace.activeWindow;\n"
        'print("' + _MARKER + nonce + ':" + (w ? w.resourceClass : "none"));\n'
    )


class WindowDetector:
    def __init__(self):
        # The session bus must be available before the first query to KWin;
        # under systemd it may not have been propagated to the unit's environment.
        ensure_session_bus()
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
        """Class (resourceClass) of the focused window, lowercased, or ""."""
        if self._kdotool:
            cls = self._via_kdotool()
            if cls is not None:
                return cls
        if self._gdbus and self._journalctl and not self._kwin_failed:
            cls = self._via_kwin()
            if cls is not None:
                return cls
        return ""

    # --- kdotool backend ---
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

    # --- KWin D-Bus backend (no AUR) ---
    # Note: KWin does not re-run an already-loaded script when calling run() again,
    # so we reload (unload + load + run) on EVERY query. It's cheap (~60-120ms).
    def _load_script(self, script_text: str) -> int | None:
        # The script is written ONLY to XDG_RUNTIME_DIR (the user's private
        # directory, 0700). We don't fall back to /tmp: a predictably-named file
        # there could be pre-created/symlinked by another user and KWin would end
        # up running someone else's JS in your session.
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime_dir:
            log.debug("XDG_RUNTIME_DIR no definido; no se carga el script de KWin.")
            return None
        try:
            path = os.path.join(runtime_dir, "kwhisper-activewindow.js")
            # O_NOFOLLOW + 0600: don't follow symlinks and only the user can read/write.
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
        # The print reaches the journal with a small delay: poll briefly.
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
