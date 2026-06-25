# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pruebas unitarias puras (sin GPU, sin Wayland, sin Ollama).

Ejecuta:  python -m pytest tests/  ·  o directamente:  python tests/test_unit.py
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
    # Ctrl+Shift+V → orden correcto de press/release anidado
    assert _paste_args("ctrl+shift+v") == ["29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]


def test_pick_clipboard_type_prefers_plain():
    # konsole ofrece text/html PRIMERO; guardar/restaurar ese tipo contaminaba
    # los alias de texto con HTML crudo. Debe preferirse text/plain.
    from kwhisper.inject import _pick_clipboard_type
    konsole = "text/html\ntext/plain\ntext/plain;charset=utf-8\nTEXT\nSTRING\nUTF8_STRING"
    assert _pick_clipboard_type(konsole) == "text/plain"
    # Sin texto plano (p.ej. una imagen) se conserva el primer tipo ofrecido.
    assert _pick_clipboard_type("image/png\nimage/bmp") == "image/png"
    # Solo text/plain con charset: se respeta tal cual.
    assert _pick_clipboard_type("text/html\ntext/plain;charset=utf-8") == "text/plain;charset=utf-8"
    # Lista vacía → cadena vacía (no revienta).
    assert _pick_clipboard_type("") == ""


def test_config_defaults():
    from kwhisper.config import Config
    cfg = Config()
    assert cfg.stt.compute_type == "float16"  # crítico en Blackwell
    assert cfg.hotkey.backend == "evdev"
    assert cfg.inject.method == "clipboard"


def test_intent_fallback_to_dictation():
    # El modelo Intent por defecto es dictado (lo que usa el fallback).
    from kwhisper.llm import Intent
    i = Intent(tipo="dictado", texto="hola mundo")
    assert i.tipo == "dictado" and i.texto == "hola mundo"
    assert i.accion == "ninguna"


def test_invalid_backend_rejected():
    # Literal: un backend con typo debe fallar la validación (no caer en evdev).
    from pydantic import ValidationError
    from kwhisper.config import Config
    try:
        Config.model_validate({"hotkey": {"backend": "banana"}})
    except ValidationError:
        return
    raise AssertionError("backend inválido debería lanzar ValidationError")


def test_ensure_session_bus_derives_from_runtime_dir(tmp_path=None):
    # Sin DBUS_SESSION_BUS_ADDRESS pero con $XDG_RUNTIME_DIR/bus presente, se
    # deriva la dirección del bus (caso systemd --user que rompía el pegado).
    import os
    from kwhisper.window import ensure_session_bus

    saved = {k: os.environ.get(k) for k in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")}
    runtime = Path(__file__).resolve().parent / "_busdir_tmp"
    try:
        runtime.mkdir(exist_ok=True)
        (runtime / "bus").write_bytes(b"")  # marcador del socket (basta que exista)
        os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
        os.environ["XDG_RUNTIME_DIR"] = str(runtime)
        ensure_session_bus()
        assert os.environ["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={runtime / 'bus'}"
        # Idempotente: no pisa un valor ya presente.
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


def test_command_key_resolution():
    # Resolución de teclas amigables → keycodes evdev (necesita python-evdev).
    try:
        from evdev import ecodes
    except ImportError:
        return  # entorno sin evdev: omitir
    from kwhisper.commands import _KEY_ALIASES
    assert ecodes.ecodes[_KEY_ALIASES["enter"]] == ecodes.ecodes["KEY_ENTER"]
    assert ecodes.ecodes[_KEY_ALIASES["ctrl"]] == ecodes.ecodes["KEY_LEFTCTRL"]


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
