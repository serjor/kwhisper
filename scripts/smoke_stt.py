#!/usr/bin/env python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Smoke test del STT: graba unos segundos del micro y transcribe en GPU.

Valida de una vez: CUDA/Blackwell + faster-whisper + captura PipeWire.
Ejecuta dentro del venv:  python scripts/smoke_stt.py [segundos]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
    from kwhisper.config import load_config
    from kwhisper.stt import STTEngine, ensure_cuda_lib_path

    cfg = load_config()
    # Igual que el daemon: montar cuBLAS/cuDNN de los wheels en LD_LIBRARY_PATH
    # (re-exec) ANTES de cargar el modelo; si no, CUDA no encuentra libcublas.
    if cfg.stt.device == "cuda":
        ensure_cuda_lib_path()

    from kwhisper.audio import AudioRecorder

    print(f"Cargando modelo '{cfg.stt.model}' ({cfg.stt.compute_type}) en {cfg.stt.device}…")
    stt = STTEngine(cfg.stt)
    t0 = time.monotonic()
    stt.load()
    print(f"Modelo listo en {time.monotonic() - t0:.1f}s.\n")

    rec = AudioRecorder(cfg.audio.samplerate, cfg.audio.channels, cfg.audio.device)
    print(f"🎙  Habla durante {seconds:.0f} s…")
    rec.start()
    time.sleep(seconds)
    audio = rec.stop()
    print(f"Grabados {rec.duration(audio):.1f}s. Transcribiendo…\n")

    t1 = time.monotonic()
    text = stt.transcribe(audio)
    print(f"⏱  Transcripción en {time.monotonic() - t1:.2f}s")
    print(f"📝  {text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
