#!/usr/bin/env python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""STT smoke test: records a few seconds from the mic and transcribes on the GPU.

Validates in one go: CUDA/Blackwell + faster-whisper + PipeWire capture.
Run inside the venv:  python scripts/smoke_stt.py [seconds]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
    from kwhisper.config import load_config
    from kwhisper.i18n import set_language, t
    from kwhisper.stt import STTEngine, ensure_cuda_lib_path

    cfg = load_config()
    set_language(cfg.ui.lang)
    # Same as the daemon: mount cuBLAS/cuDNN from the wheels into LD_LIBRARY_PATH
    # (re-exec) BEFORE loading the model; otherwise CUDA can't find libcublas.
    if cfg.stt.device == "cuda":
        ensure_cuda_lib_path()

    from kwhisper.audio import AudioRecorder

    print(t("smoke.loading", model=cfg.stt.model, compute=cfg.stt.compute_type, device=cfg.stt.device))
    stt = STTEngine(cfg.stt)
    t0 = time.monotonic()
    stt.load()
    print(t("smoke.model_ready", secs=time.monotonic() - t0))

    rec = AudioRecorder(cfg.audio.samplerate, cfg.audio.channels, cfg.audio.device)
    print(t("smoke.speak", seconds=seconds))
    rec.start()
    time.sleep(seconds)
    audio = rec.stop()
    print(t("smoke.recorded", secs=rec.duration(audio)))

    t1 = time.monotonic()
    text = stt.transcribe(audio)
    print(t("smoke.transcribed_in", secs=time.monotonic() - t1))
    print(f"📝  {text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
