# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Graphical settings dialog (PySide6) for non-technical users.

Exposes the three most commonly tweaked options without touching the TOML file:
* Interface language (auto / Español / English).
* Ollama model — a pick-list populated live from the running Ollama instance,
  falling back to a free-text field when Ollama is unreachable.
* System prompt — hidden behind an "Advanced" section with a prominent warning,
  because overriding it can break command/dictation classification. A
  "restore default" button rolls back to the built-in, tested prompt.

The dialog only *collects* values (:meth:`SettingsDialog.values`); persisting
and live-applying them is the caller's job (see ``app.py``), which keeps the
widget free of side effects and easy to reason about.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import LLMConfig, UIConfig
from .i18n import t
from .llm import DEFAULT_SYSTEM_PROMPT, list_models, normalize_system_prompt

# (config value, human label key). "auto" first so it is the default choice.
_LANGS = [("auto", "settings.lang_auto"), ("es", "Español"), ("en", "English")]


class SettingsDialog(QDialog):
    def __init__(self, ui_cfg: UIConfig, llm_cfg: LLMConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self._llm_cfg = llm_cfg
        self.setWindowTitle(t("settings.title"))
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        root.addLayout(form)

        # --- Interface language ---
        self._lang = QComboBox()
        for value, label_key in _LANGS:
            # Built-in language names (Español/English) are not translation keys;
            # only "auto" is localized.
            label = t(label_key) if label_key.startswith("settings.") else label_key
            self._lang.addItem(label, value)
        idx = self._lang.findData(ui_cfg.lang)
        self._lang.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(t("settings.language"), self._lang)

        # --- Ollama model (pick-list + manual fallback) ---
        self._model = QComboBox()
        self._model.setEditable(True)  # always allow typing a name Ollama doesn't list yet
        self._refresh = QPushButton(t("settings.model_refresh"))
        self._refresh.clicked.connect(self._reload_models)
        model_row = QHBoxLayout()
        model_row.addWidget(self._model, 1)
        model_row.addWidget(self._refresh)
        model_box = QWidget()
        model_box.setLayout(model_row)
        form.addRow(t("settings.model"), model_box)
        self._model_hint = QLabel()
        self._model_hint.setWordWrap(True)
        self._model_hint.setStyleSheet("color: palette(mid);")
        form.addRow("", self._model_hint)
        self._reload_models()  # populates from Ollama; keeps the configured model selected

        # --- Advanced: system prompt (collapsed, with a serious warning) ---
        self._advanced = QGroupBox(t("settings.advanced"))
        self._advanced.setCheckable(True)
        self._advanced.setChecked(bool((llm_cfg.system_prompt or "").strip()))
        adv = QVBoxLayout(self._advanced)

        warning = QLabel("⚠  " + t("settings.prompt_warning"))
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #c0392b; font-weight: bold;")
        adv.addWidget(warning)

        adv.addWidget(QLabel(t("settings.system_prompt")))
        self._prompt = QPlainTextEdit()
        self._prompt.setPlainText((llm_cfg.system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPT)
        self._prompt.setMinimumHeight(180)
        adv.addWidget(self._prompt)

        restore = QPushButton(t("settings.restore_default"))
        restore.clicked.connect(lambda: self._prompt.setPlainText(DEFAULT_SYSTEM_PROMPT))
        adv.addWidget(restore, 0, Qt.AlignmentFlag.AlignLeft)

        self._advanced.toggled.connect(self._on_advanced_toggled)
        self._on_advanced_toggled(self._advanced.isChecked())
        root.addWidget(self._advanced)

        # --- Save / Cancel ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t("settings.save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("settings.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---------- helpers ----------
    def _on_advanced_toggled(self, checked: bool) -> None:
        # A checkable QGroupBox keeps its children visible when unchecked; hide
        # them ourselves so the section truly collapses.
        for child in self._advanced.findChildren(QWidget):
            child.setVisible(checked)

    def _reload_models(self) -> None:
        current = self._model.currentText().strip() or self._llm_cfg.model
        models = list_models(self._llm_cfg.host)
        self._model.clear()
        if models:
            self._model.addItems(models)
            self._model_hint.setText(t("settings.model_found", count=len(models)))
        else:
            self._model_hint.setText(t("settings.model_none"))
        # Keep (or restore) the configured model even if Ollama doesn't list it.
        if current and self._model.findText(current) < 0:
            self._model.insertItem(0, current)
        self._model.setCurrentText(current)

    # ---------- result ----------
    def values(self) -> dict:
        """Collected settings (call after the dialog is accepted).

        ``system_prompt`` is normalized: blank or equal-to-default becomes ``""``
        so the config records "use the built-in prompt" (rollback) rather than
        pinning a copy of the default.
        """
        return {
            "ui_lang": self._lang.currentData(),
            "llm_model": self._model.currentText().strip() or self._llm_cfg.model,
            "llm_system_prompt": normalize_system_prompt(self._prompt.toPlainText()),
        }
