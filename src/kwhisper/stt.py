# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Transcription engine with faster-whisper (CTranslate2) on CUDA.

Blackwell note (sm_120): ``compute_type`` must be ``float16``. INT8 gives
``CUBLAS_STATUS_NOT_SUPPORTED`` on RTX 50xx with CTranslate2 < 4.7. The model is
kept resident in VRAM and a "warm-up" is run on load to pay the JIT-PTX cost
only once (the first inference is slow on Blackwell).
"""

from __future__ import annotations

import logging
import os
import sys
import time

import numpy as np

from .config import STTConfig

log = logging.getLogger(__name__)


def ensure_cuda_lib_path() -> None:
    """If STT uses CUDA via pip wheels, add cuBLAS/cuDNN to LD_LIBRARY_PATH and
    re-exec the process (the loader reads LD_LIBRARY_PATH only at startup).

    No-op if already done (KWHISPER_LDPATH_SET) or if the wheels are not used
    (e.g. system ctranslate2). Must be called BEFORE instantiating WhisperModel.
    Used both by the daemon (app.main) and the standalone scripts (smoke_stt)."""
    if os.environ.get("KWHISPER_LDPATH_SET"):
        return
    try:
        # These are namespace packages (no __init__.py): __file__ is None, so we
        # must use __path__ to locate the directory containing the .so files.
        import nvidia.cublas.lib as _cublas  # noqa: PLC0415
        import nvidia.cudnn.lib as _cudnn  # noqa: PLC0415
        paths = [next(iter(_cublas.__path__)), next(iter(_cudnn.__path__))]
    except Exception:  # noqa: BLE001
        return  # using system ctranslate2 or another path: nothing to do
    current = os.environ.get("LD_LIBRARY_PATH", "")
    if all(p in current.split(":") for p in paths):
        return
    # Remember the user's ORIGINAL LD_LIBRARY_PATH so the TTS worker can restore it:
    # the worker must NOT inherit the ct2 cuDNN-9 paths we prepend below, but it
    # should keep whatever the user had set.
    if current:
        os.environ["KWHISPER_ORIG_LD_LIBRARY_PATH"] = current
    os.environ["LD_LIBRARY_PATH"] = ":".join(paths + ([current] if current else []))
    os.environ["KWHISPER_LDPATH_SET"] = "1"
    os.execv(sys.executable, [sys.executable, *sys.argv])


class STTEngine:
    def __init__(self, cfg: STTConfig):
        self.cfg = cfg
        self._model = None

    def load(self) -> None:
        """Load the model into VRAM and warm it up. May take a few seconds."""
        from faster_whisper import WhisperModel

        t0 = time.monotonic()
        log.info(
            "Loading STT model '%s' (%s, %s)…",
            self.cfg.model, self.cfg.device, self.cfg.compute_type,
        )
        self._model = WhisperModel(
            self.cfg.model,
            device=self.cfg.device,
            compute_type=self.cfg.compute_type,
        )
        log.info("Model loaded in %.1fs. Warming up…", time.monotonic() - t0)
        self._warmup()
        log.info("STT ready (total warm-up %.1fs).", time.monotonic() - t0)

    def _warmup(self) -> None:
        # 1 s of silence: forces the JIT-PTX compilation the first time.
        silence = np.zeros(16000, dtype=np.float32)
        try:
            segments, _ = self._model.transcribe(silence, language=self.cfg.language or None, beam_size=1)
            for _ in segments:
                pass
        except Exception as exc:  # noqa: BLE001
            log.warning("Warm-up failed (non-critical): %s", exc)

    def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            raise RuntimeError("STTEngine.load() was not called")
        if audio.size == 0:
            return ""
        t0 = time.monotonic()
        segments, info = self._model.transcribe(
            audio,
            language=self.cfg.language or None,
            beam_size=self.cfg.beam_size,
            vad_filter=self.cfg.vad_filter,
            initial_prompt=self.cfg.initial_prompt or None,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        # Whisper sometimes leaves double spaces when joining segments.
        text = " ".join(text.split())
        log.info(
            "Transcribed in %.2fs (language=%s, %d chars): %r",
            time.monotonic() - t0, getattr(info, "language", "?"), len(text), text[:80],
        )
        return text
