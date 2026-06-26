# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Environment diagnostics: ``kwhisper-doctor``.

Checks GPU/CUDA, Wayland tools, permissions and Ollama, and reports what is
missing for kwhisper to work. It does not modify anything.
"""

from __future__ import annotations

import grp
import os
import shutil
import subprocess
import sys

from .i18n import set_language, t

OK = "\033[32m✔\033[0m"
WARN = "\033[33m‼\033[0m"
BAD = "\033[31m✗\033[0m"


def _line(status: str, label: str, detail: str = "") -> None:
    print(f"  {status} {label}" + (f" — {detail}" if detail else ""))


def _check_gpu() -> None:
    print(t("doctor.sec_gpu"))
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            _line(OK, "nvidia-smi", out)
        except Exception as exc:  # noqa: BLE001
            _line(WARN, t("doctor.nvidia_smi_failed"), str(exc))
    else:
        _line(BAD, t("doctor.nvidia_smi_not_found"))
    try:
        import ctranslate2
        ver = ctranslate2.__version__
        status = OK if tuple(int(x) for x in ver.split(".")[:2]) >= (4, 7) else WARN
        _line(status, "ctranslate2", t("doctor.ct2_detail", ver=ver))
    except Exception as exc:  # noqa: BLE001
        _line(BAD, t("doctor.ct2_not_importable"), str(exc))
    try:
        import faster_whisper  # noqa: F401
        _line(OK, t("doctor.fw_importable"))
    except Exception as exc:  # noqa: BLE001
        _line(BAD, t("doctor.fw_not_importable"), str(exc))
    for mod in ("nvidia.cublas.lib", "nvidia.cudnn.lib"):
        try:
            __import__(mod)
            _line(OK, t("doctor.mod_present", mod=mod))
        except Exception:  # noqa: BLE001
            _line(WARN, t("doctor.mod_absent", mod=mod), t("doctor.mod_absent_detail"))


def _check_wayland_tools() -> None:
    print("\n" + t("doctor.sec_wayland"))
    for tool, required in (("ydotool", True), ("wl-copy", True), ("wl-paste", True),
                           ("kdotool", False), ("dotool", False)):
        if shutil.which(tool):
            _line(OK, tool)
        else:
            _line(BAD if required else WARN, t("doctor.tool_not_installed", tool=tool),
                  "" if required else t("doctor.optional"))
    # ydotool socket
    sock = os.environ.get("YDOTOOL_SOCKET", f"/run/user/{os.getuid()}/.ydotool_socket")
    if os.path.exists(sock):
        _line(OK, t("doctor.ydotool_socket"), sock)
    else:
        _line(WARN, t("doctor.ydotool_socket_missing"), t("doctor.ydotool_socket_hint", sock=sock))
    # D-Bus session bus (needed for terminal detection via KWin; under systemd
    # it may not propagate, and then pasting falls back to Ctrl+V in konsole).
    from .window import ensure_session_bus
    ensure_session_bus()
    bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if bus:
        _line(OK, t("doctor.dbus_bus"), bus)
    else:
        _line(WARN, t("doctor.dbus_bus_absent"), t("doctor.dbus_bus_absent_detail"))
    # terminal detection (Ctrl+Shift+V)
    try:
        from .window import WindowDetector
        backend = WindowDetector().backend
        if backend == "none":
            _line(WARN, t("doctor.term_detect"), t("doctor.term_detect_none"))
        else:
            _line(OK, t("doctor.term_detect"), t("doctor.term_detect_backend", backend=backend))
    except Exception as exc:  # noqa: BLE001
        _line(WARN, t("doctor.term_detect"), str(exc))


def _check_permissions() -> None:
    print("\n" + t("doctor.sec_permissions"))
    groups = {grp.getgrgid(g).gr_name for g in os.getgroups()}
    if "input" in groups:
        _line(OK, t("doctor.input_group"), t("doctor.input_group_detail"))
    else:
        _line(WARN, t("doctor.no_input_group"), t("doctor.no_input_group_detail"))
    if os.access("/dev/uinput", os.W_OK):
        _line(OK, t("doctor.uinput_writable"), t("doctor.uinput_writable_detail"))
    else:
        _line(WARN, t("doctor.uinput_not_writable"), t("doctor.uinput_not_writable_detail"))


def _check_ollama() -> None:
    print("\n" + t("doctor.sec_ollama"))
    try:
        import httpx
        from .config import load_config
        cfg = load_config()
        r = httpx.get(f"{cfg.llm.host}/api/tags", timeout=3)
        # Ollama exposes the model name under "name" (or "model" in recent
        # versions of /api/tags); we accept both so detection doesn't fail.
        models = [m.get("name") or m.get("model", "") for m in r.json().get("models", [])]
        models = [m for m in models if m]
        _line(OK, t("doctor.ollama_responds"), cfg.llm.host)
        want = cfg.llm.model
        if any(m.split(":")[0] == want.split(":")[0] for m in models):
            _line(OK, t("doctor.model_available", model=want))
        else:
            _line(WARN, t("doctor.model_missing", model=want),
                  t("doctor.model_missing_detail", model=want, have=", ".join(models[:6])))
    except Exception as exc:  # noqa: BLE001
        _line(WARN, t("doctor.ollama_unavailable"), t("doctor.ollama_unavailable_detail", error=exc))


def _check_tts() -> None:
    print("\n" + t("doctor.sec_tts"))
    import os.path

    from .config import load_config
    from .tts import default_model_dir
    cfg = load_config().tts
    if not cfg.enabled:
        _line(WARN, t("doctor.tts_disabled"))
    model_dir = cfg.model_dir or str(default_model_dir())
    for f in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        if os.path.exists(os.path.join(model_dir, f)):
            _line(OK, t("doctor.tts_model_present", model=f))
        else:
            _line(WARN, t("doctor.tts_model_absent", model=f),
                  t("doctor.tts_model_absent_detail", dir=model_dir))
    try:
        import kokoro_onnx  # noqa: F401
        _line(OK, t("doctor.tts_kokoro_ok"))
    except Exception as exc:  # noqa: BLE001
        _line(WARN, t("doctor.tts_kokoro_fail"), str(exc))
    # Only import torch (heavy, loads CUDA) if Chatterbox is the chosen answer engine.
    if cfg.answer_engine == "chatterbox":
        try:
            import torch
            if torch.cuda.is_available():
                _line(OK, t("doctor.tts_torch_gpu"))
            else:
                _line(WARN, t("doctor.tts_torch_cpu"))
        except Exception as exc:  # noqa: BLE001
            _line(WARN, t("doctor.tts_chatterbox_fail"), str(exc))


def main() -> int:
    from .config import load_config
    set_language(load_config().ui.lang)
    print(t("doctor.title", ver=sys.version.split()[0]) + "\n")
    _check_gpu()
    _check_wayland_tools()
    _check_permissions()
    _check_ollama()
    _check_tts()
    from .config import CONFIG_PATH
    state = t("doctor.config_exists") if CONFIG_PATH.exists() else t("doctor.config_will_create")
    print("\n" + t("doctor.config_line", path=CONFIG_PATH, state=state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
