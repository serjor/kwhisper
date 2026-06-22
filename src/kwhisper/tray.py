"""Icono de bandeja (StatusNotifierItem) con estado y menú."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

# Iconos del tema según estado (con fallback si el tema no los trae).
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

        self._enabled_action = QAction("Activado")
        self._enabled_action.setCheckable(True)
        self._enabled_action.setChecked(True)
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

    def set_state(self, state: str) -> None:
        icon_name = _ICONS.get(state, _ICONS["idle"])
        icon = QIcon.fromTheme(icon_name)
        if icon.isNull():
            icon = QIcon.fromTheme("audio-input-microphone")
        self._tray.setIcon(icon)
        self._status_action.setText(_LABELS.get(state, _LABELS["idle"]))
        self._tray.setToolTip(_LABELS.get(state, "kwhisper"))

    def notify(self, title: str, message: str,
               icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information) -> None:
        self._tray.showMessage(title, message, icon, 3000)
