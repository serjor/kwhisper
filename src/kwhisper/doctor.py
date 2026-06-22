"""Diagnóstico del entorno: ``kwhisper-doctor``.

Comprueba GPU/CUDA, herramientas de Wayland, permisos y Ollama, e informa de qué
falta para que kwhisper funcione. No modifica nada.
"""

from __future__ import annotations

import grp
import os
import shutil
import subprocess
import sys

OK = "\033[32m✔\033[0m"
WARN = "\033[33m‼\033[0m"
BAD = "\033[31m✗\033[0m"


def _line(status: str, label: str, detail: str = "") -> None:
    print(f"  {status} {label}" + (f" — {detail}" if detail else ""))


def _check_gpu() -> None:
    print("GPU / CUDA")
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            _line(OK, "nvidia-smi", out)
        except Exception as exc:  # noqa: BLE001
            _line(WARN, "nvidia-smi falló", str(exc))
    else:
        _line(BAD, "nvidia-smi no encontrado")
    try:
        import ctranslate2
        ver = ctranslate2.__version__
        status = OK if tuple(int(x) for x in ver.split(".")[:2]) >= (4, 7) else WARN
        _line(status, "ctranslate2", f"{ver} (recomendado ≥4.7 para int8 en sm_120; float16 va siempre)")
    except Exception as exc:  # noqa: BLE001
        _line(BAD, "ctranslate2 no importable", str(exc))
    try:
        import faster_whisper  # noqa: F401
        _line(OK, "faster-whisper importable")
    except Exception as exc:  # noqa: BLE001
        _line(BAD, "faster-whisper no importable", str(exc))
    for mod in ("nvidia.cublas.lib", "nvidia.cudnn.lib"):
        try:
            __import__(mod)
            _line(OK, f"{mod} presente")
        except Exception:  # noqa: BLE001
            _line(WARN, f"{mod} ausente", "se usará CUDA del sistema (revisa LD_LIBRARY_PATH)")


def _check_wayland_tools() -> None:
    print("\nWayland / inyección")
    for tool, required in (("ydotool", True), ("wl-copy", True), ("wl-paste", True),
                           ("kdotool", False), ("dotool", False)):
        if shutil.which(tool):
            _line(OK, tool)
        else:
            _line(BAD if required else WARN, f"{tool} no instalado",
                  "" if required else "opcional")
    # socket de ydotool
    sock = os.environ.get("YDOTOOL_SOCKET", f"/run/user/{os.getuid()}/.ydotool_socket")
    if os.path.exists(sock):
        _line(OK, "socket ydotoold", sock)
    else:
        _line(WARN, "socket ydotoold no existe", f"{sock} — arranca: systemctl --user enable --now ydotool")


def _check_permissions() -> None:
    print("\nPermisos")
    groups = {grp.getgrgid(g).gr_name for g in os.getgroups()}
    if "input" in groups:
        _line(OK, "grupo input", "push-to-talk evdev disponible")
    else:
        _line(WARN, "no estás en el grupo input",
              "sudo usermod -aG input $USER (relogin) — o usa backend=portal")
    if os.access("/dev/uinput", os.W_OK):
        _line(OK, "/dev/uinput escribible", "ydotool puede inyectar")
    else:
        _line(WARN, "/dev/uinput no escribible", "ACL de logind ausente; ¿sesión activa?")


def _check_ollama() -> None:
    print("\nOllama (clasificación de comandos)")
    try:
        import httpx
        from .config import load_config
        cfg = load_config()
        r = httpx.get(f"{cfg.llm.host}/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        _line(OK, "Ollama responde", cfg.llm.host)
        want = cfg.llm.model
        if any(m.split(":")[0] == want.split(":")[0] for m in models):
            _line(OK, f"modelo '{want}' disponible")
        else:
            _line(WARN, f"modelo '{want}' no está", f"ollama pull {want}  · tienes: {', '.join(models[:6])}")
    except Exception as exc:  # noqa: BLE001
        _line(WARN, "Ollama no disponible", f"{exc} (el dictado funciona igual, sin comandos)")


def main() -> int:
    print(f"kwhisper doctor — python {sys.version.split()[0]}\n")
    _check_gpu()
    _check_wayland_tools()
    _check_permissions()
    _check_ollama()
    from .config import CONFIG_PATH
    print(f"\nConfig: {CONFIG_PATH} ({'existe' if CONFIG_PATH.exists() else 'se creará al arrancar'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
