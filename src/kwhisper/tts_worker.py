# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Out-of-process TTS worker. Run as ``python -m kwhisper.tts_worker``.

Kokoro (CPU, torch-free) is the always-available engine for feedback and as the
answer fallback; Chatterbox (torch cu128, GPU) is optional for answers and, if it
fails to load on Blackwell, this worker degrades to Kokoro permanently for the
rest of the session.

Protocol (one JSON object per line):
* stdin  ← {"cmd": "config", model_dir, voice, speed, lang, device}
           {"cmd": "speak", "engine": "kokoro"|"chatterbox", "text": ...}
           {"cmd": "cancel"}      (handled immediately by the reader thread)
           {"cmd": "shutdown"}
* stdout → {"event": "done"|"cancelled"|"error", "fallback": bool, "detail": str}

The libraries' own chatter is redirected to stderr so it never corrupts the JSON
protocol on stdout (which uses the original fd captured before the swap).
"""

from __future__ import annotations

import json
import queue
import sys
import threading


class _Kokoro:
    """Lazy Kokoro (onnxruntime, sr=24000, float32). No torch."""

    def __init__(self, cfg: dict):
        self._k = None
        self.cfg = cfg

    def synth(self, text: str):
        if self._k is None:
            import os
            if self.cfg.get("device") == "cuda":
                # onnxruntime-gpu must be a CUDA-12.8 build (ORT>=1.22) for sm_120;
                # otherwise it silently falls back to CPU (which is fine for 82M).
                os.environ.setdefault("ONNX_PROVIDER", "CUDAExecutionProvider")
            from kokoro_onnx import Kokoro
            d = self.cfg["model_dir"]
            self._k = Kokoro(os.path.join(d, "kokoro-v1.0.onnx"),
                             os.path.join(d, "voices-v1.0.bin"))
        return self._k.create(text, voice=self.cfg["voice"],
                              speed=self.cfg["speed"], lang=self.cfg["lang"])


class _Chatterbox:
    """Lazy Chatterbox Multilingual (torch cu128, GPU, m.sr=24000)."""

    def __init__(self, cfg: dict):
        self._m = None
        self.cfg = cfg

    def synth(self, text: str):
        if self._m is None:
            import torch  # noqa: F401  (fail fast if the cu128 stack is broken)
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            self._m = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
        wav = self._m.generate(text, language_id=self.cfg["lang"])
        return wav.squeeze().cpu().numpy(), self._m.sr


def main() -> int:
    import sounddevice as sd

    # Capture the real stdout for the protocol, then send everything else to
    # stderr so library prints can't corrupt the JSON stream.
    out = sys.stdout
    sys.stdout = sys.stderr

    def reply(obj: dict) -> None:
        out.write(json.dumps(obj, ensure_ascii=False) + "\n")
        out.flush()

    cfg: dict | None = None
    kok = ch = None
    cb_dead = False                 # Chatterbox failed once → stop retrying
    cancel = threading.Event()
    play_lock = threading.Lock()  # serializes the cancel-check -> play vs cancel's stop
    cmds: queue.Queue = queue.Queue()

    def _reader() -> None:
        # Cancel must act immediately (even mid-playback), so it is handled here
        # rather than queued behind a long-running speak.
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("cmd") == "cancel":
                with play_lock:
                    cancel.set()
                    try:
                        sd.stop()
                    except Exception:  # noqa: BLE001,S110
                        pass
            else:
                cmds.put(m)
        cmds.put({"cmd": "shutdown"})  # stdin EOF → parent gone → exit

    threading.Thread(target=_reader, name="tts-reader", daemon=True).start()

    while True:
        m = cmds.get()
        c = m.get("cmd")
        if c == "shutdown":
            return 0
        if c == "config":
            cfg = m
            kok = _Kokoro(cfg)
            ch = _Chatterbox(cfg)
            continue
        if c != "speak" or cfg is None:
            continue
        # Clear at the START of each utterance (not in a finally): a stale cancel
        # left over from the previous utterance must not suppress this one.
        cancel.clear()
        engine = m.get("engine", "kokoro")
        text = m.get("text", "")
        fallback = False
        detail = ""
        try:
            if engine == "chatterbox" and not cb_dead:
                try:
                    samples, sr = ch.synth(text)
                except Exception as exc:  # noqa: BLE001  torch/Blackwell/load failure
                    cb_dead = True
                    fallback = True
                    detail = repr(exc)
                    sys.stderr.write(f"chatterbox->kokoro fallback: {exc!r}\n")
                    samples, sr = kok.synth(text)
            else:
                samples, sr = kok.synth(text)
            # Decide-to-play and start the stream atomically against a concurrent
            # cancel's stop, so a barge-in in the gap between the check and sd.play()
            # can't be missed. sd.wait() stays OUTSIDE the lock so cancel can stop it.
            with play_lock:
                started = not cancel.is_set()
                if started:
                    sd.play(samples, sr)  # float32 [-1, 1] mono
            if started:
                sd.wait()
            reply({"event": "cancelled" if cancel.is_set() else "done",
                   "fallback": fallback, "detail": detail})
        except Exception as exc:  # noqa: BLE001
            reply({"event": "error", "detail": repr(exc)})


if __name__ == "__main__":
    raise SystemExit(main())
