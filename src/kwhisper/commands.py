# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Voice command executor (whitelist of safe actions).

Only executes the actions the classifier can emit:
* ``open_app``   → launches a program (if allowed in config).
* ``close_app``  → terminates a program by name with SIGTERM (if allowed).
* ``press_key``  → sends a key combination with ydotool.
* ``none``       → does nothing.

By design it does NOT execute arbitrary shell commands dictated by voice.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import signal
import subprocess
from pathlib import Path

from .config import CommandsConfig
from .i18n import t
from .llm import Intent

log = logging.getLogger(__name__)

_KEY_ALIASES = {
    "ctrl": "KEY_LEFTCTRL", "control": "KEY_LEFTCTRL",
    "shift": "KEY_LEFTSHIFT", "alt": "KEY_LEFTALT",
    "super": "KEY_LEFTMETA", "meta": "KEY_LEFTMETA", "win": "KEY_LEFTMETA",
    "enter": "KEY_ENTER", "return": "KEY_ENTER", "intro": "KEY_ENTER",
    "esc": "KEY_ESC", "escape": "KEY_ESC",
    "space": "KEY_SPACE", "espacio": "KEY_SPACE", "tab": "KEY_TAB",
    "del": "KEY_DELETE", "delete": "KEY_DELETE", "supr": "KEY_DELETE",
    "backspace": "KEY_BACKSPACE", "retroceso": "KEY_BACKSPACE",
    "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
    "home": "KEY_HOME", "end": "KEY_END", "pageup": "KEY_PAGEUP", "pagedown": "KEY_PAGEDOWN",
}

# Desktop-entry field codes (freedesktop spec). They expand to file/URL/icon
# arguments at launch time; we strip them when running an Exec line ourselves.
_FIELD_CODES = {"%f", "%F", "%u", "%U", "%d", "%D",
                "%n", "%N", "%i", "%c", "%k", "%v", "%m"}


def _app_dirs() -> list[Path]:
    """XDG application directories, user first, then system and Flatpak exports."""
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    roots = [data_home, *data_dirs.split(":"),
             os.path.expanduser("~/.local/share/flatpak/exports/share"),
             "/var/lib/flatpak/exports/share"]
    dirs: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root:
            continue
        appdir = Path(root) / "applications"
        if str(appdir) in seen:
            continue
        seen.add(str(appdir))
        if appdir.is_dir():
            dirs.append(appdir)
    return dirs


def _parse_desktop(path: Path) -> dict[str, str]:
    """Parse the ``[Desktop Entry]`` group of a .desktop file into a dict."""
    entry: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entry
    in_entry = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_entry = line == "[Desktop Entry]"
            continue
        if in_entry and "=" in line:
            key, _, val = line.partition("=")
            entry[key.strip()] = val.strip()
    return entry


# Match weights for (exact, prefix, substring, compact-substring). ``Name``
# carries the brand; ``GenericName`` ("Calculadora", "Web Browser") is a weaker,
# more ambiguous signal, so it scores lower and never outranks a Name hit — yet
# an exact/prefix generic match still clears the 60 threshold (e.g. spoken
# "calculadora" → GenericName[es] "Calculadora científica").
_NAME_WEIGHTS = (100, 80, 60, 40)
_GENERIC_WEIGHTS = (75, 65, 45, 30)


def _name_score(value: str, q: str, q_compact: str,
                weights: tuple[int, int, int, int]) -> int:
    """Score one Name/GenericName value against the spoken query ``q``."""
    nl = " ".join(value.lower().split())
    exact, prefix, substring, compact = weights
    if nl == q:
        return exact
    if nl.startswith(q):
        return prefix
    if q in nl:
        return substring
    if q_compact and q_compact in nl.replace(" ", ""):
        return compact
    return 0


def _resolve_desktop(query: str) -> tuple[str, Path] | None:
    """Find the best-matching .desktop for a spoken app name.

    Matches (case-insensitive) every ``Name``/``Name[lang]`` and
    ``GenericName``/``GenericName[lang]`` value plus the file id against the
    spoken text. ``Name`` outweighs ``GenericName``. Returns ``(desktop_id,
    path)`` or ``None`` if nothing scores high enough. The id is what
    ``kstart --application`` expects.
    """
    q = " ".join(query.lower().split())
    if not q:
        return None
    q_compact = q.replace(" ", "")
    best: tuple[str, Path] | None = None
    best_score = 0
    for base in _app_dirs():
        for path in sorted(base.rglob("*.desktop")):
            entry = _parse_desktop(path)
            if entry.get("Type", "Application") != "Application":
                continue
            if entry.get("Hidden", "").lower() == "true" or not entry.get("Exec"):
                continue
            score = 0
            for key, value in entry.items():
                field = key.split("[", 1)[0]  # "Name[es]" -> "Name"
                if field == "Name":
                    score = max(score, _name_score(value, q, q_compact, _NAME_WEIGHTS))
                elif field == "GenericName":
                    score = max(score, _name_score(value, q, q_compact, _GENERIC_WEIGHTS))
            stem = path.stem.lower()
            if stem == q or stem.replace("-", " ").replace("_", " ") == q:
                score = max(score, 95)
            elif q_compact and stem.replace("-", "").replace("_", "") == q_compact:
                score = max(score, 70)
            if entry.get("NoDisplay", "").lower() == "true":
                score -= 15
            if score > best_score:
                desktop_id = "-".join(path.relative_to(base).with_suffix("").parts)
                best_score, best = score, (desktop_id, path)
    return best if best_score >= 60 else None


def _exec_argv(exec_line: str) -> list[str]:
    """Tokenize a Desktop ``Exec=`` line, dropping field codes like ``%u``."""
    try:
        tokens = shlex.split(exec_line)
    except ValueError:
        return []
    return [tok for tok in tokens if tok not in _FIELD_CODES]


def _exe_candidate(name: str) -> str | None:
    """Resolve a spoken name to an executable on PATH, trying common spellings."""
    base = name.strip()
    low = base.lower()
    first = base.split()[0] if base.split() else ""
    candidates = [base, low, low.replace(" ", "-"), low.replace(" ", "_"),
                  low.replace(" ", ""), first, first.lower()]
    seen: set[str] = set()
    for cand in candidates:
        if cand and cand not in seen:
            seen.add(cand)
            if shutil.which(cand):
                return cand
    return None


def _matching_pids(names: set[str]) -> list[int]:
    """PIDs owned by the current user whose process name is in ``names``.

    Matches the kernel ``comm`` (capped at 15 chars by Linux) and the basename
    of ``argv[0]``, case-insensitively. Never returns our own PID, and only
    considers processes of the current uid (the only ones we may signal anyway).
    """
    targets = {n for n in (x.lower() for x in names) if n}
    if not targets:
        return []
    truncated = {n[:15] for n in targets}  # /proc/<pid>/comm is truncated to 15
    me = os.getpid()
    uid = os.getuid()
    proc = Path("/proc")
    try:
        entries = [e for e in proc.iterdir() if e.name.isdigit()]
    except OSError:
        return []
    pids: list[int] = []
    for entry in entries:
        pid = int(entry.name)
        if pid == me:
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            comm = (entry / "comm").read_text(errors="replace").strip().lower()
        except OSError:
            continue  # process vanished or unreadable; skip it
        argv0 = ""
        try:
            raw = (entry / "cmdline").read_bytes().split(b"\0")
            if raw and raw[0]:
                argv0 = os.path.basename(raw[0].decode("utf-8", "replace")).lower()
        except OSError:
            pass
        if comm in truncated or (argv0 and argv0 in targets):
            pids.append(pid)
    return pids


class CommandExecutor:
    def __init__(self, cfg: CommandsConfig):
        self.cfg = cfg
        self._procs: list[subprocess.Popen] = []

    def _spawn(self, args: list[str]) -> None:
        # Launches detached and keeps the reference, pruning the already finished
        # ones (avoids zombies without losing the Popen).
        self._procs = [p for p in self._procs if p.poll() is None]
        self._procs.append(subprocess.Popen(
            args, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def execute(self, intent: Intent) -> str:
        """Execute the intent's action. Returns a human-readable result message."""
        if intent.action == "open_app":
            return self._open_app(intent.argument)
        if intent.action == "close_app":
            return self._close_app(intent.argument)
        if intent.action == "press_key":
            return self._press_key(intent.argument)
        return t("cmd.no_action")

    def _open_app(self, name: str) -> str:
        name = (name or "").strip()
        if not name:
            return t("cmd.open_no_app")
        if not self.cfg.allow_launch:
            return t("cmd.launch_disabled")
        try:
            # Prefer the .desktop entry whose Name matches what was spoken: it
            # carries the correct Exec, so "Zen Browser" → zen.desktop even when
            # the binary is named differently (zen-bin) or lives outside PATH.
            desktop = _resolve_desktop(name)
            if desktop is not None and self._launch_desktop(desktop):
                return t("cmd.opening", app=name)
            # Fallback: a matching executable on PATH. We launch the binary with
            # NO dictated arguments, so the transcription can't sneak in flags.
            binary = _exe_candidate(name)
            if binary:
                self._spawn([binary])
                return t("cmd.opening", app=binary)
            return t("cmd.app_not_found", app=name)
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to open %s", name)
            return t("cmd.open_error", app=name, error=exc)

    def _close_names(self, name: str) -> set[str]:
        """Process-name candidates (binary basenames) for a spoken app name.

        Symmetric to opening: the .desktop ``Exec`` gives the real binary even
        when it differs from the spoken name ("Zen Browser" → ``zen-bin``), with
        PATH and the raw name as fallbacks.
        """
        names: set[str] = set()
        desktop = _resolve_desktop(name)
        if desktop is not None:
            argv = _exec_argv(_parse_desktop(desktop[1]).get("Exec", ""))
            if argv:
                names.add(os.path.basename(argv[0]))
        binary = _exe_candidate(name)
        if binary:
            names.add(os.path.basename(binary))
        low = " ".join(name.lower().split())
        names.update({low, low.replace(" ", "-"),
                      low.replace(" ", "_"), low.replace(" ", "")})
        return {n for n in names if n}

    def _close_app(self, name: str) -> str:
        name = (name or "").strip()
        if not name:
            return t("cmd.close_no_app")
        if not self.cfg.allow_close:
            return t("cmd.close_disabled")
        try:
            pids = _matching_pids(self._close_names(name))
            if not pids:
                return t("cmd.app_not_running", app=name)
            # SIGTERM only: lets the app save state and exit cleanly. We never
            # escalate to SIGKILL — forcing a stuck app is the user's call.
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass  # gone or not ours; nothing to do
            return t("cmd.closing", app=name)
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to close %s", name)
            return t("cmd.close_error", app=name, error=exc)

    def _launch_desktop(self, desktop: tuple[str, Path]) -> bool:
        """Launch a resolved .desktop via the first available launcher."""
        desktop_id, path = desktop
        if shutil.which("kstart"):  # canonical on KDE; expects the desktop id
            self._spawn(["kstart", "--application", desktop_id])
            return True
        if shutil.which("gio"):
            self._spawn(["gio", "launch", str(path)])
            return True
        if shutil.which("gtk-launch"):
            self._spawn(["gtk-launch", desktop_id])
            return True
        argv = _exec_argv(_parse_desktop(path).get("Exec", ""))
        if argv:
            self._spawn(argv)
            return True
        return False

    def _press_key(self, combo: str) -> str:
        combo = (combo or "").strip()
        if not combo:
            return t("cmd.press_no_key")
        try:
            from evdev import ecodes
        except ImportError:
            return t("cmd.no_evdev")
        tokens = [tok for tok in combo.replace(" ", "").lower().split("+") if tok]
        codes: list[int] = []
        for tok in tokens:
            key_name = _KEY_ALIASES.get(tok, f"KEY_{tok.upper()}")
            code = ecodes.ecodes.get(key_name)
            if code is None:
                return t("cmd.unknown_key", key=repr(tok))
            codes.append(code)
        seq = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
        env = dict(os.environ)
        env.setdefault("YDOTOOL_SOCKET", f"/run/user/{os.getuid()}/.ydotool_socket")
        try:
            subprocess.run(["ydotool", "key", *seq], check=True, env=env,
                           capture_output=True)
            return t("cmd.pressed", combo=combo)
        except subprocess.CalledProcessError as exc:
            return t("cmd.press_failed", combo=combo, error=exc)
        except FileNotFoundError:
            return t("cmd.no_ydotool")
