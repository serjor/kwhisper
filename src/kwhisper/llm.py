# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Dictation vs command classification with a local LLM via Ollama.

Given a transcription, ``gemma3`` decides whether the user wants to DICTATE text
(insert it into the window) or EXECUTE a command in natural language. It uses
structured output (JSON schema) with ``temperature=0`` so it is stable and fast.

If Ollama does not respond or the JSON is invalid, it *falls back to dictation*
with the transcription as-is: you never lose what you said.
"""

from __future__ import annotations

import json
import logging

import httpx
from pydantic import BaseModel, ValidationError

from .config import LLMConfig

log = logging.getLogger(__name__)


class Intent(BaseModel):
    kind: str = "dictation"          # "dictation" | "command"
    text: str = ""                   # text to insert (if dictation)
    action: str = "none"             # "open_app" | "press_key" | "none"
    argument: str = ""               # app name, key combination, etc.


# JSON schema that Ollama enforces on the output (structured outputs).
_FORMAT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["dictation", "command"]},
        "text": {"type": "string"},
        "action": {"type": "string", "enum": ["open_app", "press_key", "none"]},
        "argument": {"type": "string"},
    },
    "required": ["kind", "text", "action", "argument"],
}

_SYSTEM = """\
Eres el clasificador de un dictado por voz en español. Recibes la transcripción \
de lo que ha dicho el usuario y decides UNA de dos cosas:

1. kind="dictation": el usuario está dictando texto para escribir en una aplicación \
(lo normal). Devuelve en "text" la transcripción con mayúsculas y puntuación \
corregidas, SIN reescribir ni resumir ni añadir nada. action="none", argument="".

2. kind="command": el usuario da una orden imperativa dirigida al ordenador \
(abrir programas, pulsar teclas del sistema). Rellena:
   - action="open_app", argument=<nombre del programa, ej. "firefox">  → para "abre/lanza/inicia X".
   - action="press_key", argument=<combinación, ej. "Return", "ctrl+c", "Escape">  → para "pulsa/dale a X".
   En kind="command", "text" va vacío.

Reglas:
- Ante la duda, es "dictation". Solo es "command" si es una orden CLARA al ordenador.
- Frases conversacionales o de contenido ("abre el documento y escribe...", "dile que...") son DICTADO.
- Responde SOLO con el objeto JSON pedido."""

_FEWSHOT = [
    ("Hola, ¿qué tal estás hoy?",
     {"kind": "dictation", "text": "Hola, ¿qué tal estás hoy?", "action": "none", "argument": ""}),
    ("abre firefox",
     {"kind": "command", "text": "", "action": "open_app", "argument": "firefox"}),
    ("pulsa enter",
     {"kind": "command", "text": "", "action": "press_key", "argument": "Return"}),
    ("el año pasado estuve en españa con mi niño",
     {"kind": "dictation", "text": "El año pasado estuve en España con mi niño.", "action": "none", "argument": ""}),
    ("lanza la terminal konsole",
     {"kind": "command", "text": "", "action": "open_app", "argument": "konsole"}),
]


class IntentRouter:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._client = httpx.Client(base_url=cfg.host, timeout=cfg.timeout)

    def _messages(self, transcription: str) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": _SYSTEM}]
        for user, out in _FEWSHOT:
            msgs.append({"role": "user", "content": user})
            msgs.append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)})
        msgs.append({"role": "user", "content": transcription})
        return msgs

    def classify(self, transcription: str) -> Intent:
        """Classify; on any failure, return dictation with the raw text."""
        fallback = Intent(kind="dictation", text=transcription)
        if not transcription.strip():
            return fallback
        try:
            resp = self._client.post("/api/chat", json={
                "model": self.cfg.model,
                "messages": self._messages(transcription),
                "stream": False,
                "format": _FORMAT_SCHEMA,
                "options": {"temperature": 0},
            })
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            intent = Intent.model_validate_json(content)
        except (httpx.HTTPError, KeyError, ValidationError, json.JSONDecodeError) as exc:
            log.warning("LLM classification failed (%s); falling back to dictation.", exc)
            return fallback
        # Sanitization: if it says dictation but the text came back empty, use the transcription.
        if intent.kind == "dictation" and not intent.text.strip():
            intent.text = transcription
        log.info("Intent: kind=%s action=%s arg=%r", intent.kind, intent.action, intent.argument)
        return intent

    def close(self) -> None:
        self._client.close()
