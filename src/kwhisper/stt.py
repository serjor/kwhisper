"""Motor de transcripción con faster-whisper (CTranslate2) sobre CUDA.

Nota Blackwell (sm_120): ``compute_type`` debe ser ``float16``. INT8 da
``CUBLAS_STATUS_NOT_SUPPORTED`` en RTX 50xx con CTranslate2 < 4.7. El modelo se
mantiene residente en VRAM y se hace un "warm-up" al cargar para pagar el JIT-PTX
una sola vez (la primera inferencia es lenta en Blackwell).
"""

from __future__ import annotations

import logging
import time

import numpy as np

from .config import STTConfig

log = logging.getLogger(__name__)


class STTEngine:
    def __init__(self, cfg: STTConfig):
        self.cfg = cfg
        self._model = None

    def load(self) -> None:
        """Carga el modelo en VRAM y lo calienta. Puede tardar unos segundos."""
        from faster_whisper import WhisperModel

        t0 = time.monotonic()
        log.info(
            "Cargando modelo STT '%s' (%s, %s)…",
            self.cfg.model, self.cfg.device, self.cfg.compute_type,
        )
        self._model = WhisperModel(
            self.cfg.model,
            device=self.cfg.device,
            compute_type=self.cfg.compute_type,
        )
        log.info("Modelo cargado en %.1fs. Calentando…", time.monotonic() - t0)
        self._warmup()
        log.info("STT listo (warm-up total %.1fs).", time.monotonic() - t0)

    def _warmup(self) -> None:
        # 1 s de silencio: fuerza la compilación JIT-PTX la primera vez.
        silence = np.zeros(16000, dtype=np.float32)
        try:
            segments, _ = self._model.transcribe(silence, language=self.cfg.language or None, beam_size=1)
            for _ in segments:
                pass
        except Exception as exc:  # noqa: BLE001
            log.warning("Warm-up falló (no crítico): %s", exc)

    def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            raise RuntimeError("STTEngine.load() no fue llamado")
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
        # Whisper a veces deja dobles espacios al unir segmentos.
        text = " ".join(text.split())
        log.info(
            "Transcrito en %.2fs (idioma=%s, %d chars): %r",
            time.monotonic() - t0, getattr(info, "language", "?"), len(text), text[:80],
        )
        return text
