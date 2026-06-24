"""Overlay flotante de estado (grabando / procesando) que NO roba el foco.

Crucial: usa ``WA_ShowWithoutActivating`` + ventana tipo Tool sin foco, para no
robar el foco de la ventana destino (donde se va a inyectar el texto).
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QLabel, QWidget


class Overlay(QWidget):
    _COLORS: ClassVar[dict[str, str]] = {
        "recording": "#e74c3c",
        "processing": "#f39c12",
        "error": "#c0392b",
    }

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._label = QLabel("", self)
        self._label.setMargin(14)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self._label.font()
        font.setPointSize(13)
        font.setBold(True)
        self._label.setFont(font)
        self._label.setStyleSheet("color: white;")
        self.resize(220, 56)

    def _set_bg(self, hex_color: str) -> None:
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(hex_color))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

    def show_state(self, state: str, text: str) -> None:
        self._set_bg(self._COLORS.get(state, "#34495e"))
        self._label.setText(text)
        self._label.adjustSize()
        self.resize(self._label.width() + 8, self._label.height() + 8)
        if not self.isVisible():
            self.show()
        self.raise_()

    def hide_overlay(self) -> None:
        self.hide()
