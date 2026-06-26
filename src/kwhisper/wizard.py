# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""First-run welcome wizard (PySide6).

Shown once, the first time kwhisper starts (when no config file existed yet), so
a non-technical user picks their interface language and Ollama model up front
instead of discovering the TOML file. It deliberately covers only those two
basics; the system prompt and everything else stay in the full Settings dialog.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .config import LLMConfig, UIConfig
from .i18n import t
from .llm import list_models

_LANGS = [("auto", "settings.lang_auto"), ("es", "Español"), ("en", "English")]


class WelcomeWizard(QDialog):
    def __init__(self, ui_cfg: UIConfig, llm_cfg: LLMConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self._llm_cfg = llm_cfg
        self.setWindowTitle(t("wizard.title"))
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        intro = QLabel(t("wizard.intro"))
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        root.addLayout(form)

        self._lang = QComboBox()
        for value, label_key in _LANGS:
            label = t(label_key) if label_key.startswith("settings.") else label_key
            self._lang.addItem(label, value)
        idx = self._lang.findData(ui_cfg.lang)
        self._lang.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(t("settings.language"), self._lang)

        self._model = QComboBox()
        self._model.setEditable(True)
        models = list_models(llm_cfg.host)
        if models:
            self._model.addItems(models)
        if llm_cfg.model and self._model.findText(llm_cfg.model) < 0:
            self._model.insertItem(0, llm_cfg.model)
        self._model.setCurrentText(llm_cfg.model)
        form.addRow(t("settings.model"), self._model)

        hint = QLabel(t("settings.model_none") if not models
                      else t("settings.model_found", count=len(models)))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        form.addRow("", hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("wizard.finish"))
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def values(self) -> dict:
        return {
            "ui_lang": self._lang.currentData(),
            "llm_model": self._model.currentText().strip() or self._llm_cfg.model,
        }
