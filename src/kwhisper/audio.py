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
        # Live input level (0.0-1.0), updated on every audio block so the UI can
        # draw a reactive equalizer. Plain float assignment is atomic under the
        # GIL, so the overlay polls it from the Qt thread without a lock.
        self._level = 0.0

    @staticmethod
    def _resolve_device(device: str):
        if not device:
            return None
        # Allows a numeric index ("3") or a substring of the name ("UGREEN").
        try:
            return int(device)
        except ValueError:
            return device

    # Perceptual mapping for the level meter: anything quieter than -58 dBFS reads
    # as silence, -12 dBFS and above fills the meter. Working in dB (instead of
    # raw RMS) makes the equalizer track loudness the way the ear does.
    _LEVEL_FLOOR_DB = -58.0
    _LEVEL_CEIL_DB = -12.0

    def _callback(self, indata, frames, time_info, status):  # noqa: ANN001
        if status:
            log.warning("Audio status: %s", status)
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())
        self._level = self._compute_level(indata)

    def _compute_level(self, indata) -> float:  # noqa: ANN001
        x = indata.astype(np.float32)
        if x.ndim > 1:  # collapse to mono for the meter
            x = x.mean(axis=1)
        rms = float(np.sqrt(np.mean(x * x))) / 32768.0
        db = 20.0 * np.log10(rms + 1e-7)
        level = (db - self._LEVEL_FLOOR_DB) / (self._LEVEL_CEIL_DB - self._LEVEL_FLOOR_DB)
        return float(np.clip(level, 0.0, 1.0))

    @property
    def level(self) -> float:
        """Latest input level in [0, 1] for the live UI meter (0 while idle)."""
        return self._level

    @property
    def recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        if self._recording:
            return
        with self._lock:
            self._frames = []
            self._recording = True
        self._level = 0.0
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="int16",
            device=self.device,
            callback=self._callback,
            blocksize=0,  # let PortAudio choose the optimal size
        )
        self._stream.start()
        log.debug("Recording started (%d Hz, %d channel/s)", self.samplerate, self.channels)

    def stop(self) -> np.ndarray:
        """Close the stream and return the audio as normalized float32 mono."""
        if not self._recording:
            return np.zeros(0, dtype=np.float32)
        with self._lock:
            self._recording = False
        self._level = 0.0
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
