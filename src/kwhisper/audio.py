# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Captura de audio del micrófono vía sounddevice (PortAudio → PipeWire).

Graba a un buffer en memoria mientras el push-to-talk esté activo y, al parar,
devuelve un ``np.ndarray`` float32 mono a 16 kHz, que es lo que espera Whisper.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


class AudioRecorder:
    """Grabador push-to-talk: ``start()`` abre el stream, ``stop()`` lo cierra
    y devuelve el audio acumulado."""

    def __init__(self, samplerate: int = 16000, channels: int = 1, device: str = ""):
        self.samplerate = samplerate
        self.channels = channels
        self.device = self._resolve_device(device)
        self._stream: sd.InputStream | None = None
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._recording = False

    @staticmethod
    def _resolve_device(device: str):
        if not device:
            return None
        # Permite índice numérico ("3") o subcadena del nombre ("UGREEN").
        try:
            return int(device)
        except ValueError:
            return device

    def _callback(self, indata, frames, time_info, status):  # noqa: ANN001
        if status:
            log.warning("Audio status: %s", status)
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())

    @property
    def recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        if self._recording:
            return
        with self._lock:
            self._frames = []
            self._recording = True
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="int16",
            device=self.device,
            callback=self._callback,
            blocksize=0,  # que PortAudio elija el tamaño óptimo
        )
        self._stream.start()
        log.debug("Grabación iniciada (%d Hz, %d canal/es)", self.samplerate, self.channels)

    def stop(self) -> np.ndarray:
        """Cierra el stream y devuelve el audio como float32 mono normalizado."""
        if not self._recording:
            return np.zeros(0, dtype=np.float32)
        with self._lock:
            self._recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        with self._lock:
            frames = self._frames
            self._frames = []
        if not frames:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(frames, axis=0)
        if audio.ndim > 1:  # a mono si llegara estéreo
            audio = audio.mean(axis=1)
        # int16 → float32 en [-1, 1], que es el formato que consume faster-whisper.
        return (audio.astype(np.float32) / 32768.0).flatten()

    def duration(self, audio: np.ndarray) -> float:
        return len(audio) / float(self.samplerate)
