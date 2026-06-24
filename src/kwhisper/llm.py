"""Clasificación dictado vs comando con un LLM local vía Ollama.

Dada una transcripción, ``gemma3`` decide si el usuario quiere DICTAR texto
(insertarlo en la ventana) o EJECUTAR un comando en lenguaje natural. Usa salida
estructurada (JSON schema) con ``temperature=0`` para que sea estable y rápido.

Si Ollama no responde o el JSON es inválido, se hace *fallback a dictado* con la
transcripción tal cual: nunca se pierde lo que dijiste.
"""

from __future__ import annotations

import json
import logging

import httpx
from pydantic import BaseModel, ValidationError

from .config import LLMConfig

log = logging.getLogger(__name__)


class Intent(BaseModel):
    tipo: str = "dictado"            # "dictado" | "comando"
    texto: str = ""                  # texto a insertar (si dictado)
    accion: str = "ninguna"          # "abrir_app" | "pulsar_tecla" | "ninguna"
    argumento: str = ""              # nombre de app, combinación de teclas, etc.


# JSON schema que Ollama fuerza en la salida (structured outputs).
_FORMAT_SCHEMA = {
    "type": "object",
    "properties": {
        "tipo": {"type": "string", "enum": ["dictado", "comando"]},
        "texto": {"type": "string"},
        "accion": {"type": "string", "enum": ["abrir_app", "pulsar_tecla", "ninguna"]},
        "argumento": {"type": "string"},
    },
    "required": ["tipo", "texto", "accion", "argumento"],
}

_SYSTEM = """\
Eres el clasificador de un dictado por voz en español. Recibes la transcripción \
de lo que ha dicho el usuario y decides UNA de dos cosas:

1. "dictado": el usuario está dictando texto para escribir en una aplicación \
(lo normal). Devuelve en "texto" la transcripción con mayúsculas y puntuación \
corregidas, SIN reescribir ni resumir ni añadir nada. accion="ninguna", argumento="".

2. "comando": el usuario da una orden imperativa dirigida al ordenador \
(abrir programas, pulsar teclas del sistema). Rellena:
   - accion="abrir_app", argumento=<nombre del programa, ej. "firefox">  → para "abre/lanza/inicia X".
   - accion="pulsar_tecla", argumento=<combinación, ej. "Return", "ctrl+c", "Escape">  → para "pulsa/dale a X".
   En "comando", "texto" va vacío.

Reglas:
- Ante la duda, es "dictado". Solo es "comando" si es una orden CLARA al ordenador.
- Frases conversacionales o de contenido ("abre el documento y escribe...", "dile que...") son DICTADO.
- Responde SOLO con el objeto JSON pedido."""

_FEWSHOT = [
    ("Hola, ¿qué tal estás hoy?",
     {"tipo": "dictado", "texto": "Hola, ¿qué tal estás hoy?", "accion": "ninguna", "argumento": ""}),
    ("abre firefox",
     {"tipo": "comando", "texto": "", "accion": "abrir_app", "argumento": "firefox"}),
    ("pulsa enter",
     {"tipo": "comando", "texto": "", "accion": "pulsar_tecla", "argumento": "Return"}),
    ("el año pasado estuve en españa con mi niño",
     {"tipo": "dictado", "texto": "El año pasado estuve en España con mi niño.", "accion": "ninguna", "argumento": ""}),
    ("lanza la terminal konsole",
     {"tipo": "comando", "texto": "", "accion": "abrir_app", "argumento": "konsole"}),
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
        """Clasifica; ante cualquier fallo, devuelve dictado con el texto crudo."""
        fallback = Intent(tipo="dictado", texto=transcription)
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
            log.warning("Clasificación LLM falló (%s); fallback a dictado.", exc)
            return fallback
        # Saneado: si dice dictado pero el texto vino vacío, usa la transcripción.
        if intent.tipo == "dictado" and not intent.texto.strip():
            intent.texto = transcription
        log.info("Intención: tipo=%s accion=%s arg=%r", intent.tipo, intent.accion, intent.argumento)
        return intent

    def close(self) -> None:
        self._client.close()
