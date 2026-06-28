# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Floating status overlay (recording / processing) that does NOT steal focus.

A dark, rounded *pill* with a live equalizer instead of a flat coloured square:

* **recording** — vertical bars that react to the microphone level in real time
  (fed by a level source wired up in ``app.py``), with a pulsing red REC dot.
* **processing** — a calm violet→cyan travelling wave that reads as "thinking",
  independent of the mic.
* **error** — low red bars.

Crucial: keeps ``WA_ShowWithoutActivating`` + a focusless Tool-type window so it
does not steal focus from the target window (where the text will be injected).
The animation runs on a self-contained ``QTimer`` (Qt thread) that only ticks
while the pill is visible, so it costs nothing at rest.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import ClassVar

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

# ---- geometry (logical px; the transparent MARGIN around the pill is the glow) --
_MARGIN = 12
_PILL_W = 192
_PILL_H = 58
_PAD_X = 18
_PAD_Y = 11
_DOT_R = 5.0
_DOT_GAP = 10.0
_NBARS = 7
_BAR_W = 6.0
_BAR_GAP = 7.0
# Tallest in the centre, shortest at the edges → a natural spectrum silhouette.
_WEIGHTS = (0.42, 0.62, 0.82, 1.0, 0.82, 0.62, 0.42)


class Overlay(QWidget):
    # Per-state palette: (bar_top, bar_bottom, dot, glow). Bars use a vertical
    # gradient; the glow is a soft coloured halo behind the pill.
    _STATES: ClassVar[dict[str, tuple[str, str, str, str]]] = {
        "recording": ("#ff5d7a", "#ff9d54", "#ff4d6d", "#ff4d6d"),
        "processing": ("#8a7bff", "#38d6ff", "#7c8bff", "#6f7bff"),
        "error": ("#ff6a6a", "#c0392b", "#ff4d4d", "#ff4d4d"),
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
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(_PILL_W + 2 * _MARGIN, _PILL_H + 2 * _MARGIN)
        # Stable caption: the KWin placement script (kwin_overlay.py) matches on
        # this to anchor the pill bottom-centre under Wayland.
        self.setWindowTitle("kwhisper-overlay")

        self._state = "recording"
        self._bars = [0.0] * _NBARS
        self._t = 0.0
        # Provides the live mic level (0-1); replaced via set_level_source().
        self._level_source: Callable[[], float] = lambda: 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 fps
        self._timer.timeout.connect(self._tick)

    # ---------- public API (called from the Qt thread via signals) ----------
    def set_level_source(self, source: Callable[[], float]) -> None:
        """Wire the live microphone level provider used by the equalizer."""
        self._level_source = source

    def show_state(self, state: str, text: str) -> None:  # noqa: ARG002
        # ``text`` is kept for signal compatibility; the pill is intentionally
        # textless — state is conveyed by colour and animation.
        self._state = state if state in self._STATES else "processing"
        if not self.isVisible():
            self._bars = [0.0] * _NBARS  # grow in from flat on first appearance
            self._reposition()
            self.show()
        if not self._timer.isActive():
            self._timer.start()
        self.raise_()

    def hide_overlay(self) -> None:
        self._timer.stop()
        self.hide()

    # ---------- positioning ----------
    def _reposition(self) -> None:
        """Centre the pill horizontally, near the bottom of the primary screen."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + geo.height() - self.height() - int(geo.height() * 0.10)
        self.move(x, y)

    # ---------- animation ----------
    def _tick(self) -> None:
        self._t += 1.0
        if self._state == "recording":
            self._advance_recording()
        elif self._state == "error":
            self._advance_to(0.16, ease=0.20)
        else:  # processing / thinking
            self._advance_processing()
        self.update()

    def _advance_recording(self) -> None:
        level = max(0.0, min(1.0, self._level_source()))
        for i in range(_NBARS):
            # Per-bar wobble (0.45-1.0) so the bars never move in lockstep.
            wobble = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(self._t * 0.16 + i * 1.1))
            target = level * _WEIGHTS[i] * wobble
            cur = self._bars[i]
            # Fast attack, slow decay → the snappy feel of a real VU meter.
            k = 0.45 if target > cur else 0.16
            self._bars[i] = cur + (target - cur) * k

    def _advance_processing(self) -> None:
        for i in range(_NBARS):
            target = 0.22 + 0.6 * (0.5 + 0.5 * math.sin(self._t * 0.13 - i * 0.85))
            self._bars[i] += (target - self._bars[i]) * 0.25

    def _advance_to(self, target: float, *, ease: float) -> None:
        for i in range(_NBARS):
            self._bars[i] += (target - self._bars[i]) * ease

    # ---------- painting ----------
    def paintEvent(self, event) -> None:  # noqa: ANN001, ARG002
        bar_top, bar_bottom, dot_hex, glow_hex = self._STATES.get(
            self._state, self._STATES["processing"])

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pill = QRectF(_MARGIN, _MARGIN, _PILL_W, _PILL_H)
        radius = _PILL_H / 2.0

        # Soft coloured glow behind the pill.
        glow = QColor(glow_hex)
        glow.setAlpha(34)
        halo = pill.adjusted(-7, -7, 7, 7)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawRoundedRect(halo, radius + 7, radius + 7)

        # Dark pill body with a faint vertical sheen and a hairline border.
        body = QLinearGradient(pill.topLeft(), pill.bottomLeft())
        body.setColorAt(0.0, QColor(30, 30, 40, 238))
        body.setColorAt(1.0, QColor(16, 16, 24, 238))
        path = QPainterPath()
        path.addRoundedRect(pill, radius, radius)
        p.fillPath(path, body)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
        p.drawPath(path)

        center_y = pill.center().y()
        inner_left = pill.left() + _PAD_X

        # Status LED on the left: a glowing, pulsing dot.
        pulse = 0.5 + 0.5 * math.sin(self._t * 0.14)
        dot = QColor(dot_hex)
        dot_cx = inner_left + _DOT_R
        glow_dot = QColor(dot_hex)
        glow_dot.setAlpha(int(70 + 60 * pulse))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow_dot)
        gr = _DOT_R + 3.0
        p.drawEllipse(QRectF(dot_cx - gr, center_y - gr, gr * 2, gr * 2))
        p.setBrush(dot)
        dr = _DOT_R * (0.82 + 0.18 * pulse)
        p.drawEllipse(QRectF(dot_cx - dr, center_y - dr, dr * 2, dr * 2))

        # Equalizer bars, centred in the space to the right of the LED.
        bars_w = _NBARS * _BAR_W + (_NBARS - 1) * _BAR_GAP
        region_left = inner_left + 2 * _DOT_R + _DOT_GAP
        region_right = pill.right() - _PAD_X
        bars_x = region_left + (region_right - region_left - bars_w) / 2.0
        max_h = _PILL_H - 2 * _PAD_Y

        for i, value in enumerate(self._bars):
            h = _BAR_W + max(0.0, min(1.0, value)) * (max_h - _BAR_W)
            x = bars_x + i * (_BAR_W + _BAR_GAP)
            rect = QRectF(x, center_y - h / 2.0, _BAR_W, h)
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0.0, QColor(bar_top))
            grad.setColorAt(1.0, QColor(bar_bottom))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(rect, _BAR_W / 2.0, _BAR_W / 2.0)
