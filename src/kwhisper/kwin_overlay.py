# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Anchor the overlay bottom-centre under KWin/Wayland.

Wayland forbids a client from positioning its own top-level windows, so KWin
centres the overlay by default. The supported way to place it is *from the
compositor*: we load a tiny KWin script (via the same D-Bus scripting channel
``window.py`` already uses) that, by window caption, moves the overlay to the
bottom-centre of its screen's usable area (``clientArea`` → excludes panels, so
it is resolution- and multi-monitor-independent).

The script is installed once and stays resident: it places the overlay both when
it is already mapped and on every ``windowAdded``, so repeated show/hide cycles
land in the right spot with no visible jump. Best-effort: if ``gdbus`` or KWin
scripting is unavailable, the overlay simply falls back to KWin's default
placement (centred) and nothing breaks.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading

log = logging.getLogger(__name__)

_KWIN_SERVICE = "org.kde.KWin"
_KWIN_SCRIPTING = "/Scripting"
_PLUGIN = "kwhisper-overlay-place"

# __TITLE__/__MARGIN__ are substituted (not str.format) to avoid escaping the
# JS braces. ``frameGeometry`` must be reassigned as a whole object: its getter
# returns a copy, so mutating ``.x`` in place is unreliable (KWin 6).
_SCRIPT_TEMPLATE = """(function () {
    var TITLE = "__TITLE__";
    var MARGIN = __MARGIN__;
    function place(w) {
        if (!w || w.caption !== TITLE) return;
        var area = workspace.clientArea(KWin.MaximizeArea, w);
        var g = w.frameGeometry;
        w.frameGeometry = {
            x: Math.round(area.x + (area.width - g.width) / 2),
            y: Math.round(area.y + area.height - g.height - MARGIN),
            width: g.width, height: g.height
        };
    }
    var all = workspace.windowList ? workspace.windowList() : workspace.clientList();
    for (var i = 0; i < all.length; i++) place(all[i]);
    if (workspace.windowAdded) workspace.windowAdded.connect(place);
    else if (workspace.clientAdded) workspace.clientAdded.connect(place);
})();
"""


class KWinOverlayPlacer:
    """Installs the bottom-centre placement KWin script (once, in the background)."""

    def __init__(self, title: str, margin: int = 48):
        self._title = title
        self._margin = int(margin)
        self._gdbus = shutil.which("gdbus")

    def install(self) -> None:
        """Install the script without blocking the Qt thread (gdbus ~100 ms)."""
        if not self._gdbus:
            log.debug("gdbus not found; overlay will use KWin's default placement.")
            return
        threading.Thread(target=self._install, name="kwhisper-overlay-place",
                         daemon=True).start()

    # ---- internals ----
    def _install(self) -> None:
        path = self._write_script()
        if path is None:
            return
        try:
            # Reload semantics mirror window.py: KWin won't re-run an already
            # loaded script, so unload first to keep installs idempotent.
            self._gdbus_call(_KWIN_SCRIPTING, "org.kde.kwin.Scripting.unloadScript", _PLUGIN)
            out = self._gdbus_call(_KWIN_SCRIPTING, "org.kde.kwin.Scripting.loadScript",
                                   path, _PLUGIN)
            m = re.search(r"-?\d+", out)
            if not m or int(m.group()) < 0:
                log.debug("overlay placement loadScript returned %r", out)
                return
            sid = int(m.group())
            self._gdbus_call(f"{_KWIN_SCRIPTING}/Script{sid}", "org.kde.kwin.Script.run")
            log.debug("overlay placement script installed (id=%d)", sid)
        except Exception as exc:  # noqa: BLE001
            log.debug("Could not install the overlay placement script: %s", exc)

    def _gdbus_call(self, object_path: str, method: str, *args: str) -> str:
        cmd = ["gdbus", "call", "--session", "--dest", _KWIN_SERVICE,
               "--object-path", object_path, "--method", method, *args]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout

    def _write_script(self) -> str | None:
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime_dir:
            log.debug("XDG_RUNTIME_DIR not set; not installing the placement script.")
            return None
        text = (_SCRIPT_TEMPLATE
                .replace("__TITLE__", self._title)
                .replace("__MARGIN__", str(self._margin)))
        try:
            path = os.path.join(runtime_dir, "kwhisper-overlay-place.js")
            # O_NOFOLLOW + 0600: same hardening as window.py — a predictably named
            # file must not be a symlink someone else planted, and only we read it.
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
            with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as fh:
                fh.write(text)
            return path
        except Exception as exc:  # noqa: BLE001
            log.debug("Could not write the placement script: %s", exc)
            return None
