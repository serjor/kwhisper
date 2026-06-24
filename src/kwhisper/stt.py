# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Motor de transcripción con faster-whisper (CTranslate2) sobre CUDA.

Nota Blackwell (sm_120): ``compute_type`` debe ser ``float16``. INT8 da
``CUBLAS_STATUS_NOT_SUPPORTED`` en RTX 50xx con CTranslate2 < 4.7. El modelo se
mantiene residente en VRAM y se hace un "warm-up" al cargar para pagar el JIT-PTX
una sola vez (la primera inferencia es lenta en Blackwell).
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
    """Si STT usa CUDA por wheels pip, mete cuBLAS/cuDNN en LD_LIBRARY_PATH y
    re-ejecuta el proceso (el loader lee LD_LIBRARY_PATH solo al arrancar).

    No-op si ya se hizo (KWHISPER_LDPATH_SET) o si no se usan los wheels (p.ej.
    ctranslate2 del sistema). Debe llamarse ANTES de instanciar WhisperModel.
    Lo usan tanto el daemon (app.main) como los scripts sueltos (smoke_stt)."""
    if os.environ.get("KWHISPER_LDPATH_SET"):
        return
    try:
        # Son namespace packages (sin __init__.py): __file__ es None, hay que
        # usar __path__ para localizar el directorio con las .so.
        import nvidia.cublas.lib as _cublas  # noqa: PLC0415
        import nvidia.cudnn.lib as _cudnn  # noqa: PLC0415
        paths = [next(iter(_cublas.__path__)), next(iter(_cudnn.__path__))]
    except Exception:  # noqa: BLE001
        return  # usando ctranslate2 del sistema u otra ruta: nada que hacer
    current = os.environ.get("LD_LIBRARY_PATH", "")
    if all(p in current.split(":") for p in paths):
        return
    os.environ["LD_LIBRARY_PATH"] = ":".join(paths + ([current] if current else []))
    os.environ["KWHISPER_LDPATH_SET"] = "1"
    os.execv(sys.executable, [sys.executable, *sys.argv])


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
