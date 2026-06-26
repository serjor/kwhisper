# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Loading and persistence of the kwhisper configuration.

The config lives in ``~/.config/kwhisper/config.toml`` (XDG). If it does not
exist, a commented template with the default values is written the first time.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Literal

from platformdirs import user_config_dir
from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("kwhisper"))
CONFIG_PATH = CONFIG_DIR / "config.toml"


class HotkeyConfig(BaseModel):
    # "evdev" = real push-to-talk (press and hold); requires the `input` group.
    # "portal" = portal shortcut in toggle mode (does not require the input group).
    backend: Literal["evdev", "portal"] = "evdev"
    # evdev name of the PTT key. Discover it with `kwhisper-findkey`.
    key: str = "KEY_PAUSE"
    # Specific /dev/input/eventX path; empty = autodetect keyboards.
    device: str = ""


class AudioConfig(BaseModel):
    samplerate: int = 16000
    channels: int = 1
    # Input device name or index (PortAudio); empty = default.
    device: str = ""


class STTConfig(BaseModel):
    model: str = "large-v3-turbo"
    # float16 MANDATORY on Blackwell sm_120 (INT8 gives CUBLAS_STATUS_NOT_SUPPORTED).
    compute_type: str = "float16"
    device: str = "cuda"
    # "es" forces Spanish (stable with English technical terms); "" = autodetection.
    language: str = "es"
    beam_size: int = 1
    vad_filter: bool = True
    # Optional initial hint with frequent jargon to pin English terms.
    initial_prompt: str = ""


class LLMConfig(BaseModel):
    enabled: bool = True
    host: str = "http://127.0.0.1:11434"
    model: str = "gemma3"
    timeout: float = 8.0
    # ADVANCED. Empty = use the built-in, tested system prompt (recommended).
    # A custom value overrides it and can BREAK command/dictation classification.
    system_prompt: str = ""


class InjectConfig(BaseModel):
    # "clipboard" = clipboard + Ctrl+V (100% accents); "dotool" = direct typing.
    method: Literal["clipboard", "dotool"] = "clipboard"
    paste_key: str = "ctrl+v"
    terminal_paste_key: str = "ctrl+shift+v"
    restore_clipboard: bool = True
    # Margin before restoring the clipboard: the target app requests the data in
    # a deferred way after the Ctrl+V; a low value may restore too early.
    restore_delay: float = 0.5
    # Detect terminals (via kdotool or KWin D-Bus) to use Ctrl+Shift+V.
    detect_terminal: bool = True


class UIConfig(BaseModel):
    overlay: bool = True
    sounds: bool = True
    notifications: bool = True
    # UI/CLI language: "auto" detects it from the locale; "es"/"en" force it.
    lang: Literal["auto", "es", "en"] = "auto"


class CommandsConfig(BaseModel):
    enabled: bool = True
    allow_launch: bool = True
    allow_close: bool = True


class Config(BaseModel):
    hotkey: HotkeyConfig = Field(default_factory=HotkeyConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    inject: InjectConfig = Field(default_factory=InjectConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    commands: CommandsConfig = Field(default_factory=CommandsConfig)


DEFAULT_TOML = """\
# kwhisper configuration — ~/.config/kwhisper/config.toml
# Restart the daemon after editing:  systemctl --user restart kwhisper

[hotkey]
# backend: "evdev" = real push-to-talk (hold the key down). Requires `input` group.
#          "portal" = portal shortcut in toggle mode (no input group).
backend = "evdev"
# Push-to-talk key. Discover the exact name with:  kwhisper-findkey
key = "KEY_PAUSE"
# Specific device (/dev/input/eventX). Empty = autodetect keyboards.
device = ""

[audio]
samplerate = 16000
channels = 1
# Mic name/index (PortAudio). Empty = system default input.
device = ""

[stt]
model = "large-v3-turbo"
compute_type = "float16"   # MANDATORY on RTX 50xx (Blackwell). Do not use int8.
device = "cuda"
language = "es"            # "" for language autodetection
beam_size = 1
vad_filter = true
initial_prompt = ""        # e.g.: "kubernetes, pull request, deploy, commit"

[llm]
# false = the LLM is NOT used: dictates the transcription as-is (without fixing
#         punctuation/capitalization or classifying commands).
# true  = the LLM fixes dictation punctuation and, if [commands].enabled,
#         also classifies and executes voice commands.
enabled = true
host = "http://127.0.0.1:11434"
model = "gemma3"
timeout = 8.0
# ADVANCED — leave empty ("") to use the built-in, tested prompt (recommended).
# A custom prompt overrides it and can BREAK command classification and
# dictation punctuation. The Settings dialog can restore the default for you.
system_prompt = ""

[inject]
method = "clipboard"       # "clipboard" (recommended) | "dotool"
paste_key = "ctrl+v"
terminal_paste_key = "ctrl+shift+v"
restore_clipboard = true
restore_delay = 0.5        # raise this if the previous clipboard appears when pasting
detect_terminal = true     # Ctrl+Shift+V in terminals (via kdotool or KWin D-Bus)

[ui]
overlay = true
sounds = true
notifications = true
lang = "auto"             # UI/CLI language: "auto" (from locale) | "es" | "en"

[commands]
# false = commands are never executed (but if [llm].enabled it still fixes
#         dictation punctuation). true = "abre <app>"/"pulsa <tecla>" get
#         executed; requires [llm].enabled = true.
enabled = true
allow_launch = true        # allow "abre <app>"
allow_close = true         # allow "cierra <app>" (sends SIGTERM by process name)
"""


def load_config() -> Config:
    """Load the config; if it does not exist, write the default template.

    On malformed TOML or invalid values, exit cleanly with a readable message
    (not a traceback, nor silent defaults that ignore your intent).
    """
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(DEFAULT_TOML, encoding="utf-8")
        return Config()
    try:
        with CONFIG_PATH.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        log.error("Malformed config.toml (%s): %s", CONFIG_PATH, exc)
        raise SystemExit(1) from exc
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        log.error("Invalid value in %s:\n%s", CONFIG_PATH, exc)
        raise SystemExit(1) from exc


def save_settings(
    *,
    ui_lang: str | None = None,
    llm_model: str | None = None,
    llm_system_prompt: str | None = None,
) -> None:
    """Persist a subset of settings to ``config.toml`` (for the Settings UI).

    Only the provided fields are written; every other value, and all the
    explanatory comments in the file, are preserved (we round-trip the document
    with ``tomlkit``). The write is atomic (temp file + ``os.replace``) so a
    crash mid-save never leaves a truncated config.

    This is intentionally limited to the keys the graphical dialog exposes
    (UI language, Ollama model, system prompt); the rest stays file-only.
    """
    import os
    import tempfile

    import tomlkit

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    base = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else DEFAULT_TOML
    doc = tomlkit.parse(base)

    def _table(name: str):
        if name not in doc:
            doc[name] = tomlkit.table()
        return doc[name]

    if ui_lang is not None:
        _table("ui")["lang"] = ui_lang
    if llm_model is not None:
        _table("llm")["model"] = llm_model
    if llm_system_prompt is not None:
        # Multiline TOML string (""" … """) when it spans lines, for readability.
        _table("llm")["system_prompt"] = tomlkit.string(
            llm_system_prompt, multiline="\n" in llm_system_prompt
        )

    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".config.", suffix=".toml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(tomlkit.dumps(doc))
        os.replace(tmp, CONFIG_PATH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
