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


class TTSConfig(BaseModel):
    # DEFAULT off: nothing changes for current users until they opt in (and
    # install the TTS extra). The neural engines NEVER load in the daemon; they
    # live in an isolated subprocess (kwhisper.tts_worker), so torch (Chatterbox)
    # cannot clash with the cuDNN-9 that faster-whisper pins via LD_LIBRARY_PATH.
    enabled: bool = False
    speak_feedback: bool = True     # A: read command confirmations / errors aloud (Kokoro)
    speak_answers: bool = True      # B: read the LLM's answer aloud (question mode)
    # Engine for spoken feedback AND answers. Piper has natural es-ES (Spain) voices
    # and installs torch-free (onnxruntime). Kokoro is multilingual but its Spanish is
    # Latin-American. Chatterbox is the most natural but pulls torch (opt-in; won't
    # install on Python >=3.14 — use a separate 3.12 venv via KWHISPER_TTS_PYTHON).
    engine: Literal["kokoro", "piper", "chatterbox"] = "piper"
    # Interpreted per engine: Piper = voice-model filename ("es_ES-davefx-medium");
    # Kokoro = built-in voice id ("ef_dora"); Chatterbox = ignored (uses lang).
    voice: str = "es_ES-davefx-medium"
    speed: float = 1.0
    lang: str = "es"
    # Kokoro device: "cpu" keeps the new code path CUDA-free (Whisper provably untouched).
    device: Literal["cpu", "cuda"] = "cpu"
    model_dir: str = ""             # "" = <user data dir>/kwhisper/models
    isolate: bool = True            # run engines in an isolated subprocess (do NOT disable on Blackwell)
    interrupt_on_ptt: bool = True   # barge-in: pressing the PTT key cuts the current utterance
    max_restarts: int = 5           # respawns of the worker before auto-disabling TTS this session
    # The transcription must START with one of these to enter question mode (B);
    # otherwise the normal dictation/command pipeline is untouched. Keep them
    # DISTINCTIVE and multi-word: a single common word (e.g. "pregunta") would
    # swallow legitimate dictation that merely begins with it.
    activation_phrases: list[str] = Field(
        default_factory=lambda: ["oye asistente", "oye kwhisper"])


class Config(BaseModel):
    hotkey: HotkeyConfig = Field(default_factory=HotkeyConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    inject: InjectConfig = Field(default_factory=InjectConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    commands: CommandsConfig = Field(default_factory=CommandsConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)


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

[tts]
# Voice output (TTS). Disabled by default: needs the TTS extra installed
# (scripts/setup.sh offers it). Piper has natural Castilian Spanish (es-ES) voices
# and is torch-free; the neural engines run in an isolated subprocess so they can't
# destabilize Whisper.
enabled = false
speak_feedback = true       # read command confirmations and errors aloud
speak_answers = true        # read the assistant's answer aloud (question mode)
# engine for feedback AND answers:
#   "piper"      = natural es-ES (Spain), torch-free (recommended)
#   "kokoro"     = multilingual, but Spanish is Latin-American
#   "chatterbox" = most natural, but pulls torch cu128 (opt-in; needs Python <3.14)
engine = "piper"
# voice — interpreted per engine:
#   piper:      voice-model file, e.g. "es_ES-davefx-medium" | "es_ES-sharvard-medium"
#   kokoro:     built-in id "ef_dora" (f) | "em_alex" (m) | "em_santa" (m)  [Latin-American]
#   chatterbox: ignored (uses lang)
voice = "es_ES-davefx-medium"
speed = 1.0
lang = "es"
device = "cpu"              # "cpu" (recommended) | "cuda" (needs onnxruntime-gpu cu128)
model_dir = ""             # empty = <user data dir>/kwhisper/models
isolate = true              # run engines in an isolated subprocess (do NOT disable on Blackwell)
interrupt_on_ptt = true     # cut the current utterance when the PTT key is pressed (barge-in)
max_restarts = 5            # worker respawns before auto-disabling TTS this session
# Phrases that open question mode (the transcription must START with one of them).
# Keep them distinctive and multi-word: a single common word like "pregunta" would
# hijack normal dictation that happens to begin with it.
activation_phrases = ["oye asistente", "oye kwhisper"]
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
    tts_enabled: bool | None = None,
    tts_feedback: bool | None = None,
    tts_answers: bool | None = None,
    tts_engine: str | None = None,
    tts_voice: str | None = None,
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
    if tts_enabled is not None:
        _table("tts")["enabled"] = tts_enabled
    if tts_feedback is not None:
        _table("tts")["speak_feedback"] = tts_feedback
    if tts_answers is not None:
        _table("tts")["speak_answers"] = tts_answers
    if tts_engine is not None:
        _table("tts")["engine"] = tts_engine
    if tts_voice is not None:
        _table("tts")["voice"] = tts_voice

    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".config.", suffix=".toml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(tomlkit.dumps(doc))
        os.replace(tmp, CONFIG_PATH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
