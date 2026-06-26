# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pure unit tests (no GPU, no Wayland, no Ollama).

Run:  python -m pytest tests/  ·  or directly:  python tests/test_unit.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_paste_args_simple():
    from kwhisper.inject import _paste_args
    # Ctrl+V → press ctrl, press v, release v, release ctrl
    assert _paste_args("ctrl+v") == ["29:1", "47:1", "47:0", "29:0"]


def test_paste_args_terminal():
    from kwhisper.inject import _paste_args
    # Ctrl+Shift+V → correct nested press/release order
    assert _paste_args("ctrl+shift+v") == ["29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]


def test_pick_clipboard_type_prefers_plain():
    # konsole offers text/html FIRST; saving/restoring that type contaminated
    # the text aliases with raw HTML. text/plain should be preferred.
    from kwhisper.inject import _pick_clipboard_type
    konsole = "text/html\ntext/plain\ntext/plain;charset=utf-8\nTEXT\nSTRING\nUTF8_STRING"
    assert _pick_clipboard_type(konsole) == "text/plain"
    # Without plain text (e.g. an image) the first offered type is kept.
    assert _pick_clipboard_type("image/png\nimage/bmp") == "image/png"
    # Only text/plain with a charset: respected as-is.
    assert _pick_clipboard_type("text/html\ntext/plain;charset=utf-8") == "text/plain;charset=utf-8"
    # Empty list → empty string (doesn't blow up).
    assert _pick_clipboard_type("") == ""


def test_config_defaults():
    from kwhisper.config import Config
    cfg = Config()
    assert cfg.stt.compute_type == "float16"  # critical on Blackwell
    assert cfg.hotkey.backend == "evdev"
    assert cfg.inject.method == "clipboard"


def test_intent_fallback_to_dictation():
    # The default Intent model is dictation (what the fallback uses).
    from kwhisper.llm import Intent
    i = Intent(kind="dictation", text="hola mundo")
    assert i.kind == "dictation" and i.text == "hola mundo"
    assert i.action == "none"


def test_invalid_backend_rejected():
    # Literal: a backend with a typo must fail validation (not fall back to evdev).
    from pydantic import ValidationError
    from kwhisper.config import Config
    try:
        Config.model_validate({"hotkey": {"backend": "banana"}})
    except ValidationError:
        return
    raise AssertionError("backend inválido debería lanzar ValidationError")


def test_ensure_session_bus_derives_from_runtime_dir(tmp_path=None):
    # Without DBUS_SESSION_BUS_ADDRESS but with $XDG_RUNTIME_DIR/bus present, the
    # bus address is derived (the systemd --user case that broke pasting).
    import os
    from kwhisper.window import ensure_session_bus

    saved = {k: os.environ.get(k) for k in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")}
    runtime = Path(__file__).resolve().parent / "_busdir_tmp"
    try:
        runtime.mkdir(exist_ok=True)
        (runtime / "bus").write_bytes(b"")  # socket marker (just needs to exist)
        os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
        os.environ["XDG_RUNTIME_DIR"] = str(runtime)
        ensure_session_bus()
        assert os.environ["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={runtime / 'bus'}"
        # Idempotent: doesn't overwrite an already-present value.
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/keep/me"
        ensure_session_bus()
        assert os.environ["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/keep/me"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        (runtime / "bus").unlink(missing_ok=True)
        runtime.rmdir()


def test_i18n_lookup_and_fallback():
    # Translation, interpolation and fallback to English for unknown languages.
    from kwhisper import i18n
    i18n.set_language("es")
    assert i18n.t("ready") == "Listo para dictar."
    assert i18n.t("cmd.opening", app="firefox") == "Abriendo firefox"
    i18n.set_language("en")
    assert i18n.t("ready") == "Ready to dictate."
    i18n.set_language("xx")  # unknown → English fallback
    assert i18n.get_language() == "en"
    # Missing key returns the key itself (never raises).
    assert i18n.t("nope.not.here") == "nope.not.here"


def test_i18n_catalogs_have_same_keys():
    # Both languages must define exactly the same set of keys (no gaps).
    from kwhisper.i18n import _CATALOG
    assert set(_CATALOG["en"]) == set(_CATALOG["es"])


def test_save_settings_roundtrip_preserves_comments(tmp_path):
    # The Settings dialog persists a subset of keys; everything else and all the
    # explanatory comments must survive the round-trip.
    from kwhisper import config

    cfg_dir = tmp_path / "kwhisper"
    cfg_path = cfg_dir / "config.toml"
    saved_dir, saved_path = config.CONFIG_DIR, config.CONFIG_PATH
    config.CONFIG_DIR, config.CONFIG_PATH = cfg_dir, cfg_path
    try:
        config.save_settings(ui_lang="en", llm_model="qwen2.5",
                             llm_system_prompt="Línea 1\nLínea 2")
        text = cfg_path.read_text(encoding="utf-8")
        assert "# kwhisper configuration" in text  # comments preserved
        loaded = config.load_config()
        assert loaded.ui.lang == "en"
        assert loaded.llm.model == "qwen2.5"
        assert loaded.llm.system_prompt == "Línea 1\nLínea 2"
        assert loaded.llm.host == "http://127.0.0.1:11434"  # untouched default kept
        # A second save only updates the given field, leaving the rest intact.
        config.save_settings(ui_lang="es")
        loaded2 = config.load_config()
        assert loaded2.ui.lang == "es"
        assert loaded2.llm.model == "qwen2.5"
    finally:
        config.CONFIG_DIR, config.CONFIG_PATH = saved_dir, saved_path


def test_normalize_system_prompt():
    from kwhisper.llm import DEFAULT_SYSTEM_PROMPT, normalize_system_prompt
    # Blank or equal-to-default → "" (config records "use built-in", a rollback).
    assert normalize_system_prompt("") == ""
    assert normalize_system_prompt("   \n  ") == ""
    assert normalize_system_prompt(DEFAULT_SYSTEM_PROMPT) == ""
    assert normalize_system_prompt("\n" + DEFAULT_SYSTEM_PROMPT + "\n") == ""
    # A genuine custom prompt is kept (trimmed).
    assert normalize_system_prompt("  custom prompt  ") == "custom prompt"


def test_system_prompt_override_used_in_messages():
    from kwhisper.config import LLMConfig
    from kwhisper.llm import DEFAULT_SYSTEM_PROMPT, IntentRouter
    # Empty override → built-in default prompt.
    router = IntentRouter(LLMConfig(system_prompt=""))
    try:
        assert router._messages("hola")[0]["content"] == DEFAULT_SYSTEM_PROMPT
    finally:
        router.close()
    # Non-empty override → custom prompt wins.
    router = IntentRouter(LLMConfig(system_prompt="SOY OTRO PROMPT"))
    try:
        assert router._messages("hola")[0]["content"] == "SOY OTRO PROMPT"
    finally:
        router.close()


def test_list_models_parses_tags(monkeypatch):
    from kwhisper import llm

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "gemma3"}, {"name": "qwen2.5"}, {"bogus": 1}]}

    monkeypatch.setattr(llm.httpx, "get", lambda *a, **k: _Resp())
    assert llm.list_models("http://x") == ["gemma3", "qwen2.5"]  # sorted, name-only


def test_list_models_unreachable_returns_empty(monkeypatch):
    from kwhisper import llm

    def _boom(*a, **k):
        raise llm.httpx.ConnectError("nope")

    monkeypatch.setattr(llm.httpx, "get", _boom)
    assert llm.list_models("http://x") == []


def test_command_key_resolution():
    # Resolution of friendly keys → evdev keycodes (needs python-evdev).
    try:
        from evdev import ecodes
    except ImportError:
        return  # environment without evdev: skip
    from kwhisper.commands import _KEY_ALIASES
    assert ecodes.ecodes[_KEY_ALIASES["enter"]] == ecodes.ecodes["KEY_ENTER"]
    assert ecodes.ecodes[_KEY_ALIASES["ctrl"]] == ecodes.ecodes["KEY_LEFTCTRL"]


def test_name_score_ranks_name_above_generic():
    from kwhisper.commands import _GENERIC_WEIGHTS, _NAME_WEIGHTS, _name_score
    # Exact brand name is the strongest signal.
    assert _name_score("KCalc", "kcalc", "kcalc", _NAME_WEIGHTS) == 100
    # Generic exact/prefix score lower but still clear the 60 threshold.
    assert _name_score("Calculadora", "calculadora", "calculadora", _GENERIC_WEIGHTS) == 75
    assert _name_score("Calculadora científica", "calculadora", "calculadora",
                       _GENERIC_WEIGHTS) == 65
    # No relation → 0.
    assert _name_score("Firefox", "kcalc", "kcalc", _NAME_WEIGHTS) == 0


def test_resolve_desktop_matches_generic_name(tmp_path, monkeypatch):
    from kwhisper import commands
    appdir = tmp_path / "applications"
    appdir.mkdir()
    (appdir / "org.kde.kcalc.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=KCalc\nName[es]=KCalc\n"
        "GenericName=Scientific Calculator\nGenericName[es]=Calculadora científica\n"
        "Exec=kcalc\n", encoding="utf-8")
    monkeypatch.setattr(commands, "_app_dirs", lambda: [appdir])
    # Brand name resolves (exact Name).
    assert commands._resolve_desktop("kcalc")[0] == "org.kde.kcalc"
    # The generic Spanish word now resolves too, via GenericName[es] prefix.
    assert commands._resolve_desktop("calculadora")[0] == "org.kde.kcalc"
    # An unrelated word still resolves to nothing.
    assert commands._resolve_desktop("zzqxnotreal") is None


def test_close_app_respects_whitelist():
    # allow_close=False must short-circuit before touching any process.
    from kwhisper import i18n
    from kwhisper.commands import CommandExecutor
    from kwhisper.config import CommandsConfig

    ex = CommandExecutor(CommandsConfig(allow_close=False))
    assert ex._close_app("firefox") == i18n.t("cmd.close_disabled")


def test_close_names_includes_raw_candidates():
    # The raw spoken name always yields process-name candidates, regardless of
    # whether the app is installed (so multi-word names still match a binary).
    from kwhisper.commands import CommandExecutor
    from kwhisper.config import CommandsConfig

    names = CommandExecutor(CommandsConfig())._close_names("Firefox Web")
    assert {"firefox web", "firefox-web", "firefox_web", "firefoxweb"} <= names


def test_close_app_unknown_reports_not_running():
    # A name that matches no running process returns the "not running" message
    # (exercises _close_names + _matching_pids without signalling anything).
    from kwhisper import i18n
    from kwhisper.commands import CommandExecutor
    from kwhisper.config import CommandsConfig

    ex = CommandExecutor(CommandsConfig(allow_close=True))
    bogus = "zzqxnotreal"
    assert ex._close_app(bogus) == i18n.t("cmd.app_not_running", app=bogus)


def test_matching_pids_detects_child():
    # _matching_pids reads /proc; verify it spots a child by its comm and never
    # returns our own PID. We terminate the child ourselves (no SIGTERM by name).
    import subprocess

    from kwhisper.commands import _matching_pids

    if not Path("/proc").is_dir():
        return  # non-Linux: /proc scanning is unavailable
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        comm = Path(f"/proc/{proc.pid}/comm").read_text().strip()
        assert proc.pid in _matching_pids({comm})
        # Unrelated name matches nothing; our own PID is always excluded.
        import os
        assert os.getpid() not in _matching_pids({comm})
        assert proc.pid not in _matching_pids({"kwhisper-nope-xyz"})
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_activation_matcher_strips_phrase_and_question():
    from kwhisper.tts import ActivationMatcher
    m = ActivationMatcher(["oye asistente", "oye kwhisper", "pregunta"])
    # Accent/case-insensitive; the activation phrase is stripped, the question kept.
    assert m.match("Oye asistente, ¿qué hora es?") == "qué hora es"
    assert m.match("oye kwhisper cuéntame un chiste") == "cuéntame un chiste"
    assert m.match("Pregunta cuánto es dos más dos") == "cuánto es dos más dos"


def test_activation_matcher_ignores_non_questions():
    from kwhisper.tts import ActivationMatcher
    m = ActivationMatcher(["oye asistente", "pregunta"])
    # No activation phrase at the START → normal dictation (None).
    assert m.match("el año pasado estuve en España") is None
    # The phrase must OPEN the text; mid-sentence does not trigger.
    assert m.match("dime qué pasó y oye asistente escucha") is None


def test_activation_matcher_longest_phrase_wins():
    from kwhisper.tts import ActivationMatcher
    # With overlapping prefixes the most specific (more words) must win, so the
    # remaining question is stripped correctly (not left with "asistente …").
    m = ActivationMatcher(["oye", "oye asistente"])
    assert m.match("oye asistente dime la hora") == "dime la hora"


def test_activation_matcher_tolerates_commas_in_phrase():
    from kwhisper.tts import ActivationMatcher
    # Whisper routinely punctuates the interjection ("Oye, asistente, ¿qué…");
    # token-by-token matching must still detect it (a string-prefix check wouldn't).
    m = ActivationMatcher(["oye asistente", "oye kwhisper"])
    assert m.match("Oye, asistente, ¿qué hora es?") == "qué hora es"
    assert m.match("oye, kwhisper, pon música") == "pon música"


def test_activation_matcher_bare_wakeword_is_empty():
    from kwhisper.tts import ActivationMatcher
    # A bare wakeword with no question returns "" (falsy), so app.py routes it to
    # normal dictation instead of sending the bare phrase to the LLM.
    m = ActivationMatcher(["oye asistente"])
    assert m.match("oye asistente") == ""
    assert m.match("Oye, asistente.") == ""


def test_ttsplayer_disabled_is_inert():
    # With the default (enabled=false) nothing is spawned or queued: current
    # users see zero behaviour change and no subprocess is ever launched.
    from kwhisper.config import TTSConfig
    from kwhisper.tts import TTSPlayer

    p = TTSPlayer(TTSConfig(enabled=False))
    p.speak_feedback("hola")
    p.speak_answer("hola")
    p.cancel()
    assert p._pump is None
    assert p._q.empty()
    assert p._proc is None
    p.close()


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✔ {name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  ✗ {name}: {exc}")
    sys.exit(1 if failed else 0)
