#!/usr/bin/env bash
# Test de aceptación de acentos: cuenta atrás, enfoca un editor de texto y mira
# si aparece exactamente la cadena. Valida portapapeles + Ctrl+V vía ydotool.
#   bash scripts/test_inject.sh
set -euo pipefail
export YDOTOOL_SOCKET="${YDOTOOL_SOCKET:-/run/user/$(id -u)/.ydotool_socket}"
TXT='España, niño, ¿qué? ¡año! pingüino, déjà vu'

command -v wl-copy >/dev/null || { echo "Falta wl-clipboard"; exit 1; }
command -v ydotool >/dev/null || { echo "Falta ydotool"; exit 1; }

echo "Pon el cursor en un editor de texto (Kate, navegador, etc.)."
for i in 5 4 3 2 1; do printf "\r  Pegando en %ss… " "$i"; sleep 1; done
echo

wl-copy "$TXT"
sleep 0.1
ydotool key 29:1 47:1 47:0 29:0   # Ctrl+V
echo
echo "Esperado:  $TXT"
echo "Si ves eso EXACTO (con ñ, ¿, ¡, ü, à), la inyección funciona."
