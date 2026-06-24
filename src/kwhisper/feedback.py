"""Realimentación sonora del dictado (inicio/fin/error) vía libcanberra."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from .config import UIConfig

log = logging.getLogger(__name__)

# Eventos sonoros estándar de freedesktop.
_EVENTS = {
    "start": "audio-volume-change",
    "stop": "complete",
    "error": "dialog-error",
}
_FREEDESKTOP = "/usr/share/sounds/freedesktop/stereo"


class Feedback:
    def __init__(self, cfg: UIConfig):
        self.cfg = cfg
        self._canberra = shutil.which("canberra-gtk-play")
        self._paplay = shutil.which("paplay") or shutil.which("pw-play")
        self._procs: list[subprocess.Popen] = []

    def _spawn(self, args: list[str]) -> None:
        # Conserva la referencia y poda los procesos de sonido ya terminados
        # (evita zombies sin perder el Popen).
        self._procs = [p for p in self._procs if p.poll() is None]
        self._procs.append(subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def play(self, event: str) -> None:
        if not self.cfg.sounds:
            return
        sound_id = _EVENTS.get(event)
        if not sound_id:
            return
        try:
            if self._canberra:
                self._spawn([self._canberra, "-i", sound_id])
                return
            path = os.path.join(_FREEDESKTOP, f"{sound_id}.oga")
            if self._paplay and os.path.exists(path):
                self._spawn([self._paplay, path])
        except Exception as exc:  # noqa: BLE001
            log.debug("No se pudo reproducir sonido %s: %s", event, exc)
