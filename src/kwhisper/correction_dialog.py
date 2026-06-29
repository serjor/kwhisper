# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Dialog to teach the personal dictionary from the last dictation.

Wayland forbids reading another app's text field, so instead of silently
watching the user's edits (as Wispr Flow does on macOS/Windows) we show them an
editable copy of what was pasted. The caller diffs the edited text against the
original to learn the corrected words (see ``app.KWhisper._on_correct_last``).

Like ``settings_dialog``, this widget only *collects* the corrected text
(:meth:`corrected_text`); the diffing, filtering and persistence are the caller's
job, keeping the dialog side-effect free.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .i18n import t


class CorrectionDialog(QDialog):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("correction.title"))
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        intro = QLabel(t("correction.intro"))
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._edit = QPlainTextEdit()
        self._edit.setPlainText(text)
        root.addWidget(self._edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def corrected_text(self) -> str:
        return self._edit.toPlainText().strip()
