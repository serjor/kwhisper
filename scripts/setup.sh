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
