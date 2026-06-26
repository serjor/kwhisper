#!/usr/bin/env bash
# kwhisper installer for CachyOS / Arch + KDE Plasma 6 (Wayland).
# Idempotent: you can run it multiple times. Asks for confirmation before
# system changes (sudo). Run:  bash scripts/setup.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYS_PYTHON="$(command -v python3 || command -v python)"
VENV="$PROJECT_DIR/.venv"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m  ✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ‼ %s\033[0m\n' "$*"; }
ask()  { read -rp "  $1 [s/N] " r; [[ "$r" =~ ^[sSyY]$ ]]; }

# 1) System packages (official repos) -----------------------------------------
say "Paquetes del sistema (pacman)"
# gcc + linux-api-headers: needed to compile the evdev module (sdist only on PyPI).
PKGS=(pyside6 ydotool wl-clipboard libnotify libcanberra ffmpeg python-evdev gcc linux-api-headers)
MISSING=()
for p in "${PKGS[@]}"; do pacman -Qq "$p" &>/dev/null || MISSING+=("$p"); done
if ((${#MISSING[@]})); then
  echo "  Faltan: ${MISSING[*]}"
  if ask "¿Instalar con sudo pacman?"; then
    sudo pacman -S --needed "${MISSING[@]}"
  else
    warn "Sáltatelo bajo tu responsabilidad; kwhisper puede no funcionar."
  fi
else
  ok "Todos los paquetes presentes."
fi

# 2) kdotool: OPTIONAL. There's a native KWin D-Bus fallback, no AUR needed.
say "kdotool (OPCIONAL — hay detección de terminal nativa por KWin/D-Bus)"
if command -v kdotool &>/dev/null; then
  ok "kdotool instalado (se usará como backend preferente)."
else
  ok "kdotool no instalado: kwhisper detectará terminales vía KWin D-Bus (sin AUR)."
fi

# 3) Python environment (uv + venv with system site-packages for PySide6) ------
say "Entorno Python (uv)"
command -v uv &>/dev/null || { echo "uv no está instalado: sudo pacman -S uv"; exit 1; }
if [[ ! -d "$VENV" ]]; then
  uv venv --system-site-packages --python "$SYS_PYTHON" "$VENV"
  ok "venv creado en $VENV (usa el PySide6 del sistema)."
else
  ok "venv ya existe."
fi
say "Instalando kwhisper y dependencias (esto descarga las libs CUDA, puede tardar)"
VIRTUAL_ENV="$VENV" uv pip install --python "$VENV/bin/python" -e "$PROJECT_DIR"
ok "kwhisper instalado en el venv."

# 3b) TTS: OPTIONAL voice output (spoken feedback + answers) -------------------
say "Voz (TTS) — OPCIONAL: feedback y respuestas habladas"
if ask "¿Instalar la salida de voz (Kokoro, CPU, sin torch)?"; then
  VIRTUAL_ENV="$VENV" uv pip install --python "$VENV/bin/python" -e "$PROJECT_DIR[tts]" \
    || warn "No pude instalar el extra TTS (kokoro-onnx)."
  # Voice models (not shipped by pip). Idempotent download into the XDG data dir
  # that TTSConfig.model_dir defaults to. Default engine is Piper (Castilian es-ES).
  MODELS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/kwhisper/models"
  PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium"
  mkdir -p "$MODELS_DIR"
  for f in es_ES-davefx-medium.onnx es_ES-davefx-medium.onnx.json; do
    if [[ -s "$MODELS_DIR/$f" ]]; then
      ok "$f ya descargado."
    elif curl -fsSL -o "$MODELS_DIR/$f" "$PIPER_BASE/$f"; then
      ok "$f → $MODELS_DIR"
    else
      warn "No pude descargar $f (voz Piper es_ES)."
    fi
  done
  echo "    Voz por defecto: Piper es_ES-davefx-medium (castellano de España)."
  echo "    Para usar Kokoro: [tts] engine = \"kokoro\" y descarga sus modelos (ver README)."
  if ask "¿Instalar además Chatterbox (respuestas neuronales, torch cu128, descarga grande)?"; then
    VIRTUAL_ENV="$VENV" uv pip install --python "$VENV/bin/python" -e "$PROJECT_DIR[tts-chatterbox]" \
      || warn "No pude instalar chatterbox-tts."
    # Blackwell sm_120: override Chatterbox's torch==2.6.0 pin (no sm_120 kernels)
    # with cu128 wheels AFTER installing it. PyPI doesn't serve cu128 → index-url.
    VIRTUAL_ENV="$VENV" uv pip install --python "$VENV/bin/python" --upgrade \
      torch torchaudio --index-url https://download.pytorch.org/whl/cu128 \
      || warn "No pude forzar torch cu128; Chatterbox puede fallar en la RTX 50xx."
    # Forcing torch may pull a cuDNN/cuBLAS that breaks faster-whisper/ct2. Re-pin the
    # cuDNN and VERIFY with a REAL GPU inference: an import alone won't surface a
    # cuBLAS/cuDNN ABI clash, which only fails at the first transcription.
    VIRTUAL_ENV="$VENV" uv pip install --python "$VENV/bin/python" "nvidia-cudnn-cu12==9.*" || true
    if "$VENV/bin/python" - <<'PY' 2>/dev/null
import numpy as np
from faster_whisper import WhisperModel
m = WhisperModel("tiny", device="cuda", compute_type="float16")
list(m.transcribe(np.zeros(16000, dtype="float32"))[0])  # 1s silence forces cuBLAS/cuDNN
PY
    then
      ok "faster-whisper sigue transcribiendo en GPU tras instalar torch cu128."
    else
      warn "La STT en GPU ya NO funciona (choque de cuDNN/cuBLAS con torch cu128)."
      echo "    Aísla Chatterbox en un venv SOLO para el worker (necesita kwhisper+kokoro+sounddevice):"
      echo "      uv venv --system-site-packages /ruta/tts-venv"
      echo "      uv pip install --python /ruta/tts-venv/bin/python -e \"$PROJECT_DIR[tts,tts-chatterbox]\""
      echo "      uv pip install --python /ruta/tts-venv/bin/python --upgrade torch torchaudio --index-url https://download.pytorch.org/whl/cu128"
      echo "      export KWHISPER_TTS_PYTHON=/ruta/tts-venv/bin/python"
    fi
  fi
else
  ok "TTS omitido (puedes instalarlo luego:  uv pip install -e \"$PROJECT_DIR[tts]\")."
fi

# 4) input group (evdev push-to-talk) -----------------------------------------
say "Permiso de teclado para push-to-talk (grupo input)"
if id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
  ok "Ya estás en el grupo input."
else
  warn "NO estás en el grupo input. evdev (push-to-talk real) lo necesita."
  echo "  Implica acceso de lectura global al teclado (como un keylogger del daemon)."
  echo "  Alternativa sin esto: backend=portal (modo toggle) en config.toml."
  if ask "¿Añadirte al grupo input ahora (sudo)?"; then
    sudo usermod -aG input "$USER"
    warn "Hecho. CIERRA SESIÓN y vuelve a entrar para que tenga efecto."
  fi
fi

# 5) ydotoold user service ----------------------------------------------------
say "Servicio ydotoold (inyección de texto)"
systemctl --user enable --now ydotool.service 2>/dev/null || warn "No pude activar ydotool.service (revisa: systemctl --user status ydotool)"
ok "ydotool.service activado (si no dio error)."

# 6) kwhisper user service ----------------------------------------------------
say "Servicio systemd de usuario kwhisper"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
sed "s#@KWHISPER_BIN@#$VENV/bin/kwhisper#g" "$PROJECT_DIR/packaging/kwhisper.service.in" > "$UNIT_DIR/kwhisper.service"
systemctl --user daemon-reload
# Import the graphical environment into the user's systemd in case Plasma
# doesn't do it on its own (otherwise the unit could silently end up "condition failed").
systemctl --user import-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_RUNTIME_DIR DISPLAY 2>/dev/null || true
ok "Unidad instalada en $UNIT_DIR/kwhisper.service"
echo "  Actívala cuando quieras:  systemctl --user enable --now kwhisper"

# 7) Ollama model --------------------------------------------------------------
say "Modelo de clasificación (Ollama)"
if command -v ollama &>/dev/null && ollama list 2>/dev/null | grep -q '^gemma3'; then
  ok "gemma3 disponible en Ollama."
else
  warn "gemma3 no está. Para comandos por voz:  ollama pull gemma3  (o ajusta [llm].model)"
fi

say "Listo."
echo "  1) Descubre tu tecla PTT:        $VENV/bin/kwhisper-findkey"
echo "  2) Edítala en:                   ~/.config/kwhisper/config.toml  (key = \"...\")"
echo "  3) Diagnóstico:                  $VENV/bin/kwhisper-doctor"
echo "  4) Arranca a mano para probar:   $VENV/bin/kwhisper"
echo "  5) O como servicio:              systemctl --user enable --now kwhisper"
