# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tray icon (StatusNotifierItem) with state and menu."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

# Theme icons by state (with a fallback if the theme does not provide them).
_ICONS = {
    "idle": "audio-input-microphone",
    "recording": "media-record",
    "processing": "view-refresh",
    "error": "dialog-error",
    "disabled": "audio-input-microphone-muted",
}
_LABELS = {
    "idle": "kwhisper: listo",
    "recording": "kwhisper: grabando…",
    "processing": "kwhisper: procesando…",
    "error": "kwhisper: error",
    "disabled": "kwhisper: desactivado",
}


class Tray:
    def __init__(self, on_toggle_enabled: Callable[[bool], None],
                 on_open_config: Callable[[], None],
                 on_quit: Callable[[], None]):
        self._tray = QSystemTrayIcon()
        self._tray.setToolTip("kwhisper")

        menu = QMenu()
        self._status_action = QAction("kwhisper: listo")
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)
        menu.addSeparator()

        self._enabled_action = QAction("Dictado activado")
        self._enabled_action.setCheckable(True)
        self._enabled_action.setChecked(True)
        # Dynamic label (text, does not depend on the theme icon) + external callback.
        self._enabled_action.toggled.connect(self._on_enabled_toggled)
        self._enabled_action.toggled.connect(on_toggle_enabled)
        menu.addAction(self._enabled_action)

        cfg_action = QAction("Editar configuración…")
        cfg_action.triggered.connect(on_open_config)
        menu.addAction(cfg_action)

        menu.addSeparator()
        quit_action = QAction("Salir")
        quit_action.triggered.connect(on_quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self.set_state("idle")
        self._tray.show()

    def _on_enabled_toggled(self, checked: bool) -> None:
        # Explicit text in the menu: the user reads the state without relying on the icon.
        self._enabled_action.setText("Dictado activado" if checked else "Dictado desactivado")

    def set_state(self, state: str) -> None:
        icon_name = _ICONS.get(state, _ICONS["idle"])
        icon = QIcon.fromTheme(icon_name)
        if icon.isNull():
            # VISIBLY different fallback for 'disabled' even if the theme does
            # not provide the '-muted' icon (otherwise it would look like 'idle').
            fallback = "dialog-cancel" if state == "disabled" else "audio-input-microphone"
            icon = QIcon.fromTheme(fallback)
        self._tray.setIcon(icon)
        self._status_action.setText(_LABELS.get(state, _LABELS["idle"]))
        self._tray.setToolTip(_LABELS.get(state, "kwhisper"))

    def notify(self, title: str, message: str,
               icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information) -> None:
        self._tray.showMessage(title, message, icon, 3000)
