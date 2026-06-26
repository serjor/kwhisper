# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Microphone audio capture via sounddevice (PortAudio → PipeWire).

Records to an in-memory buffer while push-to-talk is active and, on stop,
returns an ``np.ndarray`` float32 mono at 16 kHz, which is what Whisper expects.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


class AudioRecorder:
    """Push-to-talk recorder: ``start()`` opens the stream, ``stop()`` closes it
    and returns the accumulated audio."""

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
        # Allows a numeric index ("3") or a substring of the name ("UGREEN").
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
            blocksize=0,  # let PortAudio choose the optimal size
        )
        self._stream.start()
        log.debug("Grabación iniciada (%d Hz, %d canal/es)", self.samplerate, self.channels)

    def stop(self) -> np.ndarray:
        """Close the stream and return the audio as normalized float32 mono."""
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
        if audio.ndim > 1:  # to mono if it comes in stereo
            audio = audio.mean(axis=1)
        # int16 → float32 in [-1, 1], which is the format faster-whisper consumes.
        return (audio.astype(np.float32) / 32768.0).flatten()

    def duration(self, audio: np.ndarray) -> float:
        return len(audio) / float(self.samplerate)
