# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tray icon (StatusNotifierItem) with state and menu."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .i18n import t

# Theme icons by state (with a fallback if the theme does not provide them).
_ICONS = {
    "idle": "audio-input-microphone",
    "recording": "media-record",
    "processing": "view-refresh",
    "error": "dialog-error",
    "disabled": "audio-input-microphone-muted",
}


def _label(state: str) -> str:
    # Resolved at call time (not import time) so the language set after
    # load_config() is already in effect.
    return t(f"tray.{state}") if state in _ICONS else t("tray.idle")


class Tray:
    def __init__(self, on_toggle_enabled: Callable[[bool], None],
                 on_open_config: Callable[[], None],
                 on_quit: Callable[[], None]):
        self._tray = QSystemTrayIcon()
        self._tray.setToolTip("kwhisper")

        menu = QMenu()
        self._status_action = QAction(_label("idle"))
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)
        menu.addSeparator()

        self._enabled_action = QAction(t("dictation.on"))
        self._enabled_action.setCheckable(True)
        self._enabled_action.setChecked(True)
        # Dynamic label (text, does not depend on the theme icon) + external callback.
        self._enabled_action.toggled.connect(self._on_enabled_toggled)
        self._enabled_action.toggled.connect(on_toggle_enabled)
        menu.addAction(self._enabled_action)

        cfg_action = QAction(t("tray.edit_config"))
        cfg_action.triggered.connect(on_open_config)
        menu.addAction(cfg_action)

        menu.addSeparator()
        quit_action = QAction(t("tray.quit"))
        quit_action.triggered.connect(on_quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self.set_state("idle")
        self._tray.show()

    def _on_enabled_toggled(self, checked: bool) -> None:
        # Explicit text in the menu: the user reads the state without relying on the icon.
        self._enabled_action.setText(t("dictation.on") if checked else t("dictation.off"))

    def set_state(self, state: str) -> None:
        icon_name = _ICONS.get(state, _ICONS["idle"])
        icon = QIcon.fromTheme(icon_name)
        if icon.isNull():
            # VISIBLY different fallback for 'disabled' even if the theme does
            # not provide the '-muted' icon (otherwise it would look like 'idle').
            fallback = "dialog-cancel" if state == "disabled" else "audio-input-microphone"
            icon = QIcon.fromTheme(fallback)
        self._tray.setIcon(icon)
        self._status_action.setText(_label(state))
        self._tray.setToolTip(_label(state) if state in _ICONS else "kwhisper")

    def notify(self, title: str, message: str,
               icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information) -> None:
        self._tray.showMessage(title, message, icon, 3000)
