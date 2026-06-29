# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Personal dictionary with learning from user corrections.

Two cooperating mechanisms, both fed from the same store
(``~/.config/kwhisper/dictionary.toml``, next to ``config.toml`` so it is easy to
edit by hand):

* **Biasing** — a ``vocab`` list of terms is appended to Whisper's
  ``initial_prompt`` so the model is nudged towards recognising the user's jargon,
  names and acronyms (see ``stt.STTEngine.transcribe``).
* **Replacements** — literal ``wrong → right`` rules applied to the transcription
  *after* the LLM and *before* injection, to fix recurring mistakes.

Corrections are captured via the "Correct last dictation" dialog (the tray):
:func:`diff_words` finds the words the user changed and :func:`is_learnable`
keeps only the "rare" ones (proper nouns, jargon, acronyms), imitating Wispr
Flow's behaviour of not polluting the dictionary with everyday words.

The store NEVER crashes the daemon: a malformed/invalid file is logged and
treated as empty (unlike ``config.py``, which exits on a bad config).
"""

from __future__ import annotations

import difflib
import logging
import re
import threading
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

DICTIONARY_PATH = CONFIG_DIR / "dictionary.toml"

# How many vocab terms to feed Whisper's initial_prompt. The model only attends
# to ~224 tokens of preceding context, so an unbounded list would be wasteful.
_VOCAB_PROMPT_LIMIT = 50

# Tokeniser for the word-level diff and the learnability filter. Unicode \w keeps
# accented letters and digits together (e.g. "large-v3" splits on the dash, which
# is fine: each side is judged independently).
_WORD_RE = re.compile(r"\w+", re.UNICODE)

# Small embedded set of common Spanish function words. NOT a full lexicon: it is
# only meant to drop the most frequent everyday words so the dictionary keeps
# proper nouns and jargon. The user can always edit/prune the TOML by hand.
_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "lo", "al", "del",
    "de", "a", "ante", "bajo", "con", "contra", "desde", "en", "entre", "hacia",
    "hasta", "para", "por", "según", "sin", "sobre", "tras", "y", "e", "o", "u",
    "ni", "que", "qué", "como", "cómo", "cuando", "cuándo", "donde", "dónde",
    "porque", "pues", "si", "sí", "no", "ya", "muy", "más", "menos", "también",
    "tampoco", "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
    "aquel", "aquella", "esto", "eso", "aquello", "mi", "mis", "tu", "tus", "su",
    "sus", "me", "te", "se", "nos", "os", "le", "les", "yo", "tú", "él", "ella",
    "ello", "ellos", "ellas", "nosotros", "vosotros", "usted", "ustedes",
    "es", "son", "era", "fue", "ser", "estar", "está", "están", "hay", "he",
    "ha", "han", "su", "del", "uno", "dos", "tres", "cosa", "cosas", "hacer",
    "todo", "toda", "todos", "todas", "otro", "otra", "otros", "otras", "cada",
    "mucho", "mucha", "poco", "poca", "tan", "tanto", "aquí", "ahí", "allí",
    "ahora", "luego", "después", "antes", "siempre", "nunca", "bien", "mal",
}


class Replacement(BaseModel):
    wrong: str
    right: str
    source: Literal["auto", "manual"] = "manual"
    count: int = 1


class _DictFile(BaseModel):
    """Validation schema for the on-disk TOML."""

    vocab: list[str] = []
    replacements: list[Replacement] = []


# --------------------------------------------------------------------------- #
# Pure helpers (no Qt/GPU/IO) — unit-tested directly.
# --------------------------------------------------------------------------- #
def diff_words(original: str, corrected: str) -> list[tuple[str, str]]:
    """Return the one-word→one-word substitutions between two texts.

    Only 1:1 replacements are reported (a single word swapped for a single
    word); insertions, deletions and multi-word rewrites are ignored, since
    those are not learnable as a ``wrong → right`` term.
    """
    a = _WORD_RE.findall(original)
    b = _WORD_RE.findall(corrected)
    pairs: list[tuple[str, str]] = []
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace" and (i2 - i1) == 1 and (j2 - j1) == 1:
            pairs.append((a[i1], b[j1]))
    return pairs


def _looks_rare(term: str) -> bool:
    """True if ``term`` looks like a proper noun, acronym or technical token.

    Heuristic, best-effort (there is no full Spanish lexicon here):
    * a leading capital → proper noun ("Madrid", "Disroot");
    * an internal capital or all-caps → CamelCase/acronym ("API", "kubeCTL");
    * contains a digit → identifier ("v3", "x86");
    * otherwise a lowercase word that is NOT a common stopword (jargon like
      "kubectl", "kubernetes").
    """
    if any(ch.isdigit() for ch in term):
        return True
    if term[:1].isupper():
        return True
    if any(ch.isupper() for ch in term[1:]):
        return True
    return term.lower() not in _STOPWORDS


def is_learnable(wrong: str, right: str) -> bool:
    """Whether a ``wrong → right`` correction is worth storing (Wispr-style).

    Keeps rare terms, drops everyday words and trivial punctuation/casing-only
    churn so the dictionary does not get polluted.
    """
    w, r = wrong.strip(), right.strip()
    if not w or not r or w == r:
        return False
    if len(r) <= 2:
        return False
    # A correction that only flips the casing of a common word is noise; but a
    # proper noun ("madrid"→"Madrid") still reads as rare via _looks_rare.
    if w.lower() in _STOPWORDS:
        return False
    return _looks_rare(r)


# --------------------------------------------------------------------------- #
# Persistent store
# --------------------------------------------------------------------------- #
class PersonalDictionary:
    """Thread-safe store for vocab + replacements.

    The worker thread reads (``vocab_terms``/``apply_replacements``) while the Qt
    thread writes (``learn``) and the user may edit the file by hand, so all
    access is guarded by a re-entrant lock.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or DICTIONARY_PATH
        self._vocab: list[str] = []
        self._replacements: list[Replacement] = []
        self._lock = threading.RLock()

    # ---- IO ----
    def load(self) -> None:
        """Load from disk. A missing/malformed/invalid file → empty (logged)."""
        with self._lock:
            self._vocab = []
            self._replacements = []
            if not self.path.exists():
                return
            try:
                with self.path.open("rb") as fh:
                    data = tomllib.load(fh)
                parsed = _DictFile.model_validate(data)
            except (tomllib.TOMLDecodeError, ValidationError, OSError) as exc:
                log.warning("Ignoring invalid dictionary %s: %s", self.path, exc)
                return
            self._vocab = parsed.vocab
            self._replacements = parsed.replacements
            log.info("Dictionary loaded: %d vocab, %d replacements",
                     len(self._vocab), len(self._replacements))

    def _persist(self) -> None:
        """Write the store atomically (temp file + os.replace). Lock held."""
        import os
        import tempfile

        import tomlkit

        doc = tomlkit.document()
        doc.add(tomlkit.comment(
            "kwhisper — personal dictionary. Restart the daemon after editing by hand:"))
        doc.add(tomlkit.comment("  systemctl --user restart kwhisper"))
        doc.add(tomlkit.nl())
        # Terms to boost during recognition (Whisper initial_prompt).
        doc["vocab"] = self._vocab
        # Literal wrong→right fixes applied after the LLM, before pasting.
        aot = tomlkit.aot()
        for rep in self._replacements:
            tbl = tomlkit.table()
            tbl["wrong"] = rep.wrong
            tbl["right"] = rep.right
            tbl["source"] = rep.source     # "auto" (learned, ✨) | "manual"
            tbl["count"] = rep.count
            aot.append(tbl)
        doc["replacements"] = aot

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".dictionary.",
                                   suffix=".toml.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(tomlkit.dumps(doc))
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def save(self) -> None:
        with self._lock:
            self._persist()

    # ---- reads (worker thread) ----
    def vocab_terms(self, limit: int = _VOCAB_PROMPT_LIMIT) -> list[str]:
        """Terms to feed Whisper's initial_prompt, capped to ``limit``."""
        with self._lock:
            return self._vocab[:limit] if limit else list(self._vocab)

    def apply_replacements(self, text: str) -> str:
        """Apply every ``wrong → right`` rule (whole-word, case-insensitive)."""
        if not text:
            return text
        with self._lock:
            rules = list(self._replacements)
        for rep in rules:
            pattern = re.compile(r"\b" + re.escape(rep.wrong) + r"\b", re.IGNORECASE)
            # A plain function avoids backreference interpretation in ``right``.
            text = pattern.sub(lambda _m, r=rep.right: r, text)
        return text

    # ---- writes (Qt thread) ----
    def learn(self, pairs: list[tuple[str, str]], source: str = "auto") -> int:
        """Add/strengthen replacements and vocab from corrections; persist.

        Returns the number of *new* terms actually learned (already-known ones
        only bump their count). Pairs are filtered through :func:`is_learnable`.
        """
        learned = 0
        changed = False
        with self._lock:
            for wrong, right in pairs:
                if not is_learnable(wrong, right):
                    continue
                existing = next(
                    (r for r in self._replacements
                     if r.wrong.lower() == wrong.lower() and r.right == right),
                    None,
                )
                if existing is not None:
                    existing.count += 1
                    changed = True
                    continue
                self._replacements.append(
                    Replacement(wrong=wrong, right=right, source=source))
                self._add_vocab(right)
                learned += 1
                changed = True
            if changed:
                self._persist()
        return learned

    def _add_vocab(self, term: str) -> None:
        """Append a term to vocab if not already present (case-insensitive). Lock held."""
        term = term.strip()
        if term and term.lower() not in {v.lower() for v in self._vocab}:
            self._vocab.append(term)
