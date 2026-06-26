# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Local text-to-speech: spoken feedback (A) and spoken answers (B).

The neural engines NEVER load inside the kwhisper daemon. They live in a child
process (``kwhisper.tts_worker``) spawned lazily with a *scrubbed* environment
(the ct2-injected ``LD_LIBRARY_PATH`` entries / ``KWHISPER_LDPATH_SET`` removed).
That matters on Blackwell: ``stt.ensure_cuda_lib_path()`` injects faster-whisper's
cuDNN-9 into the parent's ``LD_LIBRARY_PATH``; dropping it for the child keeps the
worker from inheriting those ct2-specific paths. The real isolation between the two
CUDA stacks comes from never co-loading torch (Chatterbox, cu128) and ct2 in one
process, plus setup.sh pinning a single shared cuDNN-9.x both accept. A
torch/Blackwell crash then kills only the worker — the dictation daemon keeps
running and respawns it (bounded; auto-disables after N failures).

A FIFO queue plus a single pump thread serialize utterances (one at a time) and
allow barge-in: pressing the PTT key (``cancel()``) flushes the queue and cuts
whatever is currently playing.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path

from platformdirs import user_data_dir

from .config import TTSConfig

log = logging.getLogger(__name__)


def default_model_dir() -> Path:
    """Where the Kokoro model files live by default (XDG user data dir)."""
    return Path(user_data_dir("kwhisper")) / "models"


def _norm(s: str) -> str:
    # lowercase + strip diacritics: robust matching of the activation phrase
    # regardless of how Whisper capitalizes or accents it.
    s = unicodedata.normalize("NFD", s.casefold())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


class ActivationMatcher:
    """Deterministic detection of question mode (B).

    Fires ONLY when the transcription STARTS with an activation phrase, so normal
    dictation is never hijacked. Returns the question with the phrase stripped, or
    ``None`` when it is not a question (the normal pipeline then runs untouched).
    """

    def __init__(self, phrases: list[str]):
        # Longest phrase (most words) first, so "oye asistente" wins over "oye".
        self._phrases = sorted(
            (_norm(p) for p in phrases if p and p.strip()),
            key=lambda p: len(p.split()), reverse=True,
        )

    def match(self, text: str) -> str | None:
        # Token-by-token on a punctuation-stripped, normalized list. This tolerates
        # commas Whisper inserts inside the phrase ("Oye, asistente, ¿qué…") which a
        # plain string-prefix check would miss.
        raw = text.split()
        toks = [_norm(t).strip(",.:;¿?¡!") for t in raw]
        for p in self._phrases:
            pt = p.split()
            if pt and toks[:len(pt)] == pt:
                return " ".join(raw[len(pt):]).strip(" ,.:;¿?¡!")
        return None


class TTSPlayer:
    """Parent-side facade: queue, barge-in, lazy worker spawn and bounded respawn.

    Thread-safety: ``speak_*`` run on the worker thread, ``cancel`` on the hotkey
    thread, ``close`` on the Qt thread. The pump thread is the ONLY reader of the
    worker's stdout; writes to its stdin are serialized with ``_io_lock`` so a
    barge-in ``cancel`` never interleaves bytes with a ``speak`` command.
    """

    def __init__(self, cfg: TTSConfig):
        self.cfg = cfg
        self.activation = ActivationMatcher(cfg.activation_phrases)
        self._q: queue.Queue = queue.Queue(maxsize=8)
        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()   # guards spawn/kill of self._proc
        self._io_lock = threading.Lock()      # serializes writes to the worker stdin
        self._pump_lock = threading.Lock()    # guards pump-thread startup
        self._pump: threading.Thread | None = None
        self._speaking = threading.Event()
        self._restarts = 0
        self._closed = False

    # ---------- public API ----------
    def speak_feedback(self, text: str) -> None:
        """A: read a command confirmation / error aloud (always Kokoro)."""
        if self.cfg.enabled and self.cfg.speak_feedback and text and text.strip():
            self._enqueue("kokoro", text)

    def speak_answer(self, text: str) -> None:
        """B: read the assistant's answer aloud (engine per config)."""
        if self.cfg.enabled and self.cfg.speak_answers and text and text.strip():
            self._enqueue(self.cfg.answer_engine, text)

    def cancel(self) -> None:
        """Barge-in: flush the queue and cut the current utterance (from PTT)."""
        if not (self.cfg.enabled and self.cfg.interrupt_on_ptt):
            return
        self._drain()
        if self._speaking.is_set():
            with self._proc_lock:
                proc = self._proc
            if proc is not None and proc.poll() is None:
                self._write(proc, {"cmd": "cancel"})

    @property
    def busy(self) -> bool:
        return self._speaking.is_set()

    def reload(self) -> None:
        """Drop the current worker so the next utterance respawns it with fresh
        config (e.g. a voice change from Settings). No-op if nothing is running."""
        with self._proc_lock:
            proc = self._proc
            self._proc = None
            self._restarts = 0  # a deliberate reload is not a failure
        if proc is not None and proc.poll() is None:
            self._write(proc, {"cmd": "shutdown"})
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                self._reap(proc)

    def close(self) -> None:
        """Stop the worker cleanly (called on quit). Best-effort, never raises."""
        self._closed = True
        self._drain()
        try:
            self._q.put_nowait(None)  # sentinel: wake the pump so it can exit
        except queue.Full:
            pass
        with self._proc_lock:
            proc = self._proc
            self._proc = None
        if proc is not None and proc.poll() is None:
            self._write(proc, {"cmd": "cancel"})
            self._write(proc, {"cmd": "shutdown"})
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                self._reap(proc)

    # ---------- internals ----------
    def _drain(self) -> None:
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def _enqueue(self, engine: str, text: str) -> None:
        if self._closed:
            return
        self._ensure_pump()
        try:
            self._q.put_nowait((engine, text))
        except queue.Full:
            log.debug("TTS queue full; dropping utterance")

    def _ensure_pump(self) -> None:
        with self._pump_lock:
            if self._pump is None or not self._pump.is_alive():
                # A fresh pump (first use, or re-enabled after auto-disable) starts
                # with a clean respawn budget so one past failure doesn't doom it.
                self._restarts = 0
                self._pump = threading.Thread(
                    target=self._pump_loop, name="tts-pump", daemon=True)
                self._pump.start()

    def _ensure_proc(self) -> subprocess.Popen:
        with self._proc_lock:
            if self._closed:
                raise RuntimeError("TTS player is closed")  # never spawn after close()
            if self._proc is not None and self._proc.poll() is None:
                return self._proc
            env = os.environ.copy()
            # Drop ct2's injected cuDNN-9 entries so the worker doesn't inherit them,
            # but RESTORE the user's original LD_LIBRARY_PATH (saved by stt.py before
            # it prepended the ct2 paths) instead of wiping it — otherwise the worker
            # loses any libs the user genuinely relies on (custom audio/CUDA).
            orig = env.pop("KWHISPER_ORIG_LD_LIBRARY_PATH", None)
            if orig:
                env["LD_LIBRARY_PATH"] = orig
            else:
                env.pop("LD_LIBRARY_PATH", None)
            env.pop("KWHISPER_LDPATH_SET", None)
            # Optional separate interpreter (escape hatch if the shared venv's
            # torch cu128 ever conflicts with ct2's pinned cuDNN at install time).
            py = os.environ.get("KWHISPER_TTS_PYTHON", sys.executable)
            proc = subprocess.Popen(
                [py, "-m", "kwhisper.tts_worker"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, bufsize=1, env=env)
            self._proc = proc
        # If Chatterbox (torch) is the answer engine, keep Kokoro on CPU so the worker
        # never hosts two CUDA stacks (onnxruntime-gpu + torch) in one process.
        device = "cpu" if self.cfg.answer_engine == "chatterbox" else self.cfg.device
        self._write(proc, {
            "cmd": "config",
            "model_dir": self.cfg.model_dir or str(default_model_dir()),
            "voice": self.cfg.voice, "speed": self.cfg.speed,
            "lang": self.cfg.lang, "device": device,
        })
        return proc

    def _write(self, proc: subprocess.Popen, obj: dict) -> None:
        if proc.stdin is None:
            return
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        try:
            with self._io_lock:
                proc.stdin.write(line)
                proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            log.debug("TTS write failed (%s)", exc)

    @staticmethod
    def _reap(proc: subprocess.Popen) -> None:
        """Wait briefly on a killed worker so it doesn't linger as a zombie."""
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass

    def _pump_loop(self) -> None:
        while True:
            item = self._q.get()
            if item is None:  # sentinel from close()
                return
            if self._closed:
                return
            engine, text = item
            proc = None
            try:
                proc = self._ensure_proc()
                self._speaking.set()
                self._write(proc, {"cmd": "speak", "engine": engine, "text": text})
                assert proc.stdout is not None
                line = proc.stdout.readline()  # blocks until done/cancelled/error
                if not line:
                    raise RuntimeError("TTS worker closed the pipe")
                ev = json.loads(line)
                if ev.get("fallback"):
                    log.warning("Chatterbox fell back to Kokoro: %s", ev.get("detail"))
                elif ev.get("event") == "error":
                    log.warning("TTS worker error: %s", ev.get("detail"))
                self._restarts = 0
            except Exception as exc:  # noqa: BLE001
                if self._closed:
                    return
                with self._proc_lock:
                    # If self._proc is no longer the proc we used, reload()/close()
                    # replaced it ON PURPOSE — a deliberate teardown, not a crash, so
                    # don't warn or spend the respawn budget on it.
                    superseded = proc is None or self._proc is not proc
                    if not superseded:
                        self._proc = None
                if superseded:
                    continue
                if proc.poll() is None:
                    proc.kill()
                self._reap(proc)  # deterministic reap, no lingering zombie
                log.warning("TTS failed (%s); respawning the worker", exc)
                self._restarts += 1
                if self._restarts > self.cfg.max_restarts:
                    log.error("TTS unstable; disabling it for this session")
                    self.cfg.enabled = False
                    return
            finally:
                self._speaking.clear()
