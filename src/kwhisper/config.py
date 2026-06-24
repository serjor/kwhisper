"""Carga y persistencia de la configuración de kwhisper.

La config vive en ``~/.config/kwhisper/config.toml`` (XDG). Si no existe, se
escribe una plantilla comentada con los valores por defecto la primera vez.
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
    # "evdev" = push-to-talk real (mantener pulsado); requiere grupo `input`.
    # "portal" = atajo del portal en modo toggle (no requiere grupo input).
    backend: Literal["evdev", "portal"] = "evdev"
    # Nombre evdev de la tecla PTT. Descúbrela con `kwhisper-findkey`.
    key: str = "KEY_PAUSE"
    # Ruta /dev/input/eventX concreta; vacío = autodetectar teclados.
    device: str = ""


class AudioConfig(BaseModel):
    samplerate: int = 16000
    channels: int = 1
    # Nombre o índice de dispositivo de entrada (PortAudio); vacío = por defecto.
    device: str = ""


class STTConfig(BaseModel):
    model: str = "large-v3-turbo"
    # OBLIGATORIO float16 en Blackwell sm_120 (INT8 da CUBLAS_STATUS_NOT_SUPPORTED).
    compute_type: str = "float16"
    device: str = "cuda"
    # "es" fuerza español (estable con tecnicismos en inglés); "" = autodetección.
    language: str = "es"
    beam_size: int = 1
    vad_filter: bool = True
    # Pista inicial opcional con jerga frecuente para fijar términos en inglés.
    initial_prompt: str = ""


class LLMConfig(BaseModel):
    enabled: bool = True
    host: str = "http://127.0.0.1:11434"
    model: str = "gemma3"
    timeout: float = 8.0


class InjectConfig(BaseModel):
    # "clipboard" = portapapeles + Ctrl+V (100% acentos); "dotool" = tecleo directo.
    method: Literal["clipboard", "dotool"] = "clipboard"
    paste_key: str = "ctrl+v"
    terminal_paste_key: str = "ctrl+shift+v"
    restore_clipboard: bool = True
    # Margen antes de restaurar el portapapeles: la app destino pide el dato de
    # forma diferida tras el Ctrl+V; un valor bajo puede restaurar antes de tiempo.
    restore_delay: float = 0.5
    # Detectar terminales (vía kdotool o KWin D-Bus) para usar Ctrl+Shift+V.
    detect_terminal: bool = True


class UIConfig(BaseModel):
    overlay: bool = True
    sounds: bool = True
    notifications: bool = True


class CommandsConfig(BaseModel):
    enabled: bool = True
    allow_launch: bool = True


class Config(BaseModel):
    hotkey: HotkeyConfig = Field(default_factory=HotkeyConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    inject: InjectConfig = Field(default_factory=InjectConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    commands: CommandsConfig = Field(default_factory=CommandsConfig)


DEFAULT_TOML = """\
# Configuración de kwhisper — ~/.config/kwhisper/config.toml
# Reinicia el daemon tras editar:  systemctl --user restart kwhisper

[hotkey]
# backend: "evdev" = push-to-talk real (mantener pulsado). Requiere grupo `input`.
#          "portal" = atajo del portal en modo toggle (sin grupo input).
backend = "evdev"
# Tecla de push-to-talk. Descubre el nombre exacto con:  kwhisper-findkey
key = "KEY_PAUSE"
# Dispositivo concreto (/dev/input/eventX). Vacío = autodetectar teclados.
device = ""

[audio]
samplerate = 16000
channels = 1
# Nombre/índice del micro (PortAudio). Vacío = entrada por defecto del sistema.
device = ""

[stt]
model = "large-v3-turbo"
compute_type = "float16"   # OBLIGATORIO en RTX 50xx (Blackwell). No pongas int8.
device = "cuda"
language = "es"            # "" para autodetección de idioma
beam_size = 1
vad_filter = true
initial_prompt = ""        # ej: "kubernetes, pull request, deploy, commit"

[llm]
# false = NO se usa el LLM: dicta la transcripción tal cual (sin corregir
#         puntuación/mayúsculas ni clasificar comandos).
# true  = el LLM corrige la puntuación del dictado y, si [commands].enabled,
#         además clasifica y ejecuta comandos de voz.
enabled = true
host = "http://127.0.0.1:11434"
model = "gemma3"
timeout = 8.0

[inject]
method = "clipboard"       # "clipboard" (recomendado) | "dotool"
paste_key = "ctrl+v"
terminal_paste_key = "ctrl+shift+v"
restore_clipboard = true
restore_delay = 0.5        # sube esto si al pegar aparece el portapapeles anterior
detect_terminal = true     # Ctrl+Shift+V en terminales (vía kdotool o KWin D-Bus)

[ui]
overlay = true
sounds = true
notifications = true

[commands]
# false = nunca se ejecutan comandos (pero si [llm].enabled sigue corrigiendo
#         la puntuación del dictado). true = "abre <app>"/"pulsa <tecla>" se
#         ejecutan; requiere [llm].enabled = true.
enabled = true
allow_launch = true        # permitir "abre <app>"
"""


def load_config() -> Config:
    """Carga la config; si no existe, escribe la plantilla por defecto.

    Ante TOML mal formado o valores inválidos, sale limpiamente con un mensaje
    legible (no un traceback, ni defaults silenciosos que ignoren tu intención).
    """
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(DEFAULT_TOML, encoding="utf-8")
        return Config()
    try:
        with CONFIG_PATH.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        log.error("config.toml mal formado (%s): %s", CONFIG_PATH, exc)
        raise SystemExit(1) from exc
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        log.error("Valor inválido en %s:\n%s", CONFIG_PATH, exc)
        raise SystemExit(1) from exc
