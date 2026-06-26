# kwhisper

**Idiomas:** [English](README.md) · [Español](README.es.md)

Dictado por voz **local** estilo Wispr Flow para **KDE Plasma 6 (Wayland)**.

Mantienes pulsada una tecla, hablas, la sueltas → el texto aparece en la ventana
enfocada. Un LLM local decide si lo que dijiste es **dictado** (se escribe) o un
**comando** (se ejecuta: abrir apps, pulsar teclas). Todo corre en tu máquina:
nada sale a internet.

- **STT**: `faster-whisper` (`large-v3-turbo`, float16) en GPU NVIDIA.
- **Clasificación dictado/comando**: Ollama (`gemma3`).
- **Activación**: push-to-talk vía `evdev` (mantener pulsado).
- **Inyección**: portapapeles + `Ctrl+V` (acentos del español 100% fiables en KWin).
- **UI**: icono de bandeja + overlay flotante + sonidos.
- **Voz (TTS, opcional)**: lee confirmaciones y responde preguntas en voz alta
  (Piper en castellano de España, o Kokoro/Chatterbox) desde un subproceso aislado.
  Desactivado por defecto.

> Diseñado y verificado para: CachyOS/Arch · KDE Plasma 6.7 Wayland · RTX 5070 Ti
> (Blackwell `sm_120`) · PipeWire. Debería valer en cualquier Arch+KDE con GPU NVIDIA.

---

## Por qué estas decisiones (no son las obvias)

Tres trampas de Wayland/Blackwell que condicionan el diseño:

1. **GPU Blackwell (`sm_120`)**: `faster-whisper` funciona, pero **hay que usar
   `float16`** — INT8 da `CUBLAS_STATUS_NOT_SUPPORTED` en RTX 50xx con CTranslate2
   antiguo. Los wheels CUDA 12 corren sobre tu driver 610 por retrocompatibilidad.
2. **Push-to-talk**: el portal de atajos de KDE **pierde el evento de soltar la
   tecla** si tecleas mientras dictas (bug KWin 483183). Por eso se lee el teclado
   con **`evdev`** (requiere grupo `input`). El portal queda como *fallback* en
   modo toggle.
3. **Acentos**: ninguna herramienta teclea `ñ á ¿ ¡ ü` de forma fiable en KWin
   (`ydotool type` rompe Unicode; `wtype` no soporta KWin). Por eso se usa
   **portapapeles + Ctrl+V**: el carácter viaja como dato y solo se simula un
   atajo fijo.

---

## Requisitos

- KDE Plasma 6 sobre Wayland, Arch/CachyOS.
- GPU NVIDIA con driver reciente (probado en 610 / serie 50xx). 16 GB VRAM sobran.
- `uv`, `ollama` (con `gemma3`), `pipewire`.

## Instalación

```fish
# Clónalo DONDE QUIERAS: setup.sh detecta la ruta automáticamente.
cd /ruta/donde/clonaste/kwhisper
bash scripts/setup.sh
```

El script (idempotente, pide confirmación antes de cada cambio con `sudo`):

1. Instala paquetes del sistema: `pyside6 ydotool wl-clipboard libnotify libcanberra ffmpeg python-evdev`.
2. (Opcional, AUR) `kdotool`. **No es necesario**: si no está, kwhisper detecta
   la terminal de forma nativa por el D-Bus de KWin (sin AUR). Sáltatelo sin miedo.
3. Crea el venv con `uv` (`--system-site-packages` para reutilizar el PySide6 de pacman) e instala kwhisper + libs CUDA.
4. Te añade al grupo `input` (push-to-talk). **Requiere cerrar sesión y volver a entrar.**
5. Activa `ydotool.service` (usuario) e instala la unidad `kwhisper.service`.

El script también **ofrece (opcional) la voz/TTS**: instala Kokoro y descarga sus
modelos, y opcionalmente Chatterbox con torch cu128 para Blackwell.

Después:

```fish
# 1. Descubre el nombre de tu tecla de push-to-talk
.venv/bin/kwhisper-findkey            # pulsa la tecla; copia el nombre (p.ej. KEY_PAUSE)

# 2. Ponla en la config
$EDITOR ~/.config/kwhisper/config.toml   # [hotkey] key = "KEY_PAUSE"

# 3. Comprueba que todo está en su sitio
.venv/bin/kwhisper-doctor

# 4. Pruébalo a mano (verás el icono en la bandeja)
.venv/bin/kwhisper
```

Cuando funcione, déjalo como servicio:

```fish
systemctl --user enable --now kwhisper
```

## Verificación rápida

```fish
# STT + GPU + micro en un solo test (graba 4s y transcribe):
.venv/bin/python scripts/smoke_stt.py

# Acentos por portapapeles (enfoca un editor; cuenta atrás y pega la cadena):
bash scripts/test_inject.sh

# Lógica pura:
.venv/bin/python tests/test_unit.py
```

## Uso

1. Mantén pulsada la tecla PTT. Suena un tono y aparece el overlay «🎙 Grabando…».
2. Habla.
3. Suelta. Se transcribe, se clasifica y:
   - **Dictado** → el texto se pega en la ventana enfocada.
   - **Comando** → se ejecuta (notificación con el resultado).

Ejemplos de comandos (lenguaje natural, en español):

| Dices | Acción |
|---|---|
| «abre firefox» | lanza Firefox |
| «lanza la terminal konsole» | abre Konsole |
| «pulsa enter» | envía Return |
| «el año pasado fui a España» | se **dicta** el texto |

> Ante la duda, el clasificador escribe (dictado). Si Ollama no está disponible,
> kwhisper sigue funcionando solo como dictado.

### Voz (TTS) — opcional

Con `[tts] enabled = true` (instala antes el extra, ver Instalación):

- **Feedback hablado**: las confirmaciones de comandos se leen en voz alta (Kokoro).
- **Modo pregunta**: si empiezas por una frase de activación («oye asistente …»,
  «oye kwhisper …»), lo que sigue se manda al LLM y la respuesta se **lee** (no se
  escribe). Ej.: «oye asistente, ¿qué hora es?». Pulsa PTT de nuevo para cortar una
  respuesta larga (barge-in).

Los motores neuronales corren en un **subproceso aislado** para que torch
(Chatterbox) no rompa el faster-whisper de Blackwell: si fallan, solo cae el TTS,
nunca el dictado.

## Configuración

`~/.config/kwhisper/config.toml` (se crea solo la primera vez). Tras editar:
`systemctl --user restart kwhisper`. Claves útiles:

- `[hotkey] backend` — `"evdev"` (push-to-talk) o `"portal"` (toggle, sin grupo input).
- `[hotkey] key` — tecla PTT (usa `kwhisper-findkey`).
- `[stt] model` — `large-v3-turbo` (rápido) o `large-v3` (más preciso en audio difícil).
- `[stt] language` — `"es"`, `"en"`, … o `""` para autodetección.
- `[llm] enabled` — `false` desactiva el LLM por completo (dictado crudo, sin
  corregir puntuación ni clasificar comandos).
- `[commands] enabled` — `false` no ejecuta comandos pero, si `[llm] enabled`,
  el dictado sigue beneficiándose de la corrección de puntuación del LLM.
- `[inject] method` — `"clipboard"` (recomendado) o `"dotool"`.
- `[commands] allow_launch` — permitir abrir aplicaciones por voz.
- `[commands] allow_close` — permitir cerrar aplicaciones por voz («cierra firefox»;
  envía `SIGTERM` al proceso correspondiente para que guarde y salga limpiamente).
- `[ui] lang` — idioma de la interfaz (overlay, notificaciones, bandeja) y de las
  herramientas de línea de comandos: `"auto"` (detectar del locale del sistema),
  `"es"` o `"en"`.
- `[tts] enabled` — `false` (por defecto) desactiva la voz. `true` requiere el extra
  TTS instalado (`scripts/setup.sh` lo ofrece).
- `[tts] speak_feedback` / `speak_answers` — leer confirmaciones de comando / leer
  las respuestas del modo pregunta.
- `[tts] engine` — `"piper"` (castellano es-ES, natural, recomendado) · `"kokoro"`
  (multilingüe, pero español latino) · `"chatterbox"` (torch cu128, opt-in; requiere Python <3.14).
- `[tts] voice` — según el motor: Piper `es_ES-sharvard-medium#1` (femenina) / `#0`
  (masculina) / `es_ES-davefx-medium`; Kokoro `ef_dora` (f) · `em_alex` (m) · `em_santa` (m).
- `[tts] activation_phrases` — frases que abren el modo pregunta (la transcripción
  debe **empezar** por una). Mantenlas distintivas y de varias palabras.

## Solución de problemas

- **No graba / “sin permiso de teclado”** → no estás en el grupo `input`. Ejecuta
  `sudo usermod -aG input $USER` y **vuelve a iniciar sesión**, o usa `backend = "portal"`.
- **No pega texto** → revisa `systemctl --user status ydotool` y que
  `kwhisper-doctor` vea el socket. El cursor debe estar en un campo de texto.
- **Acentos rotos** → asegúrate de `method = "clipboard"` (no `dotool`).
- **Al pegar aparece lo que tenías antes en el portapapeles** → la app destino lo
  pidió tarde; sube `[inject] restore_delay` (p.ej. a `0.8`).
- **Error CUDA / `libcudnn`** → lo gestiona el re-exec de `LD_LIBRARY_PATH`; si
  persiste, no mezcles con el `python-pytorch` del sistema (usa el venv aislado).
- **Funciona a mano pero como servicio no pega (sobre todo en konsole)** → bajo
  `systemctl --user` falta `DBUS_SESSION_BUS_ADDRESS`, así que `gdbus` no alcanza a
  KWin y la detección de terminal cae a `Ctrl+V` (konsole no pega con eso). kwhisper
  ya lo deriva de `$XDG_RUNTIME_DIR/bus`; si aún falla, `kwhisper-doctor` te dirá si
  el «bus de sesión D-Bus» está ausente. Reinstala la unidad actualizada:
  `systemctl --user daemon-reload && systemctl --user restart kwhisper`.
- **En terminal pega mal** → la detección de terminal (para usar `Ctrl+Shift+V`)
  usa KWin por D-Bus; comprueba con `kwhisper-doctor` que el backend no sea
  «ninguno». Si lo es, instala `kdotool` o revisa `gdbus`/`journalctl`. También
  puedes forzar `[inject] paste_key = "ctrl+shift+v"` si dictas sobre todo en terminales.
- **Ver logs**: `journalctl --user -u kwhisper -f` (o `KWHISPER_LOG=DEBUG .venv/bin/kwhisper`).

## Arquitectura

```
HotkeyListener (evdev) ─KEY_DOWN→ grabar ─KEY_UP→ AudioRecorder (sounddevice 16k)
        │                                              │ buffer float32
        ▼                                              ▼
   (1 proceso PySide6)                         STTEngine (faster-whisper, VRAM)
   Tray + Overlay + Feedback                          │ texto
                                                       ▼
                                       IntentRouter (Ollama gemma3, JSON)
                                          │ dictado            │ comando
                                          ▼                    ▼
                                   TextInjector          CommandExecutor
                                (wl-copy + Ctrl+V)     (abrir app / pulsar tecla)
```

Procesos externos: `ollama` (:11434), `ydotoold` (--user), KWin/PipeWire.

## Hoja de ruta

- [ ] Doble hotkey dedicado (una tecla = dictado, otra = comando) para cero ambigüedad.
- [x] Diálogo de configuración gráfico (PySide6) + asistente de primer arranque (idioma, modelo, prompt de sistema).
- [x] Salida de voz (TTS): feedback hablado + modo pregunta con respuesta leída (Kokoro/Chatterbox).
- [ ] Comandos de edición fijos («nueva línea», «borra eso»).
- [ ] Plasmoid de panel opcional (estado vía D-Bus).
- [ ] PKGBUILD para AUR.

## Licencia

[MPL-2.0](LICENSE) (Mozilla Public License 2.0): copyleft a nivel de fichero.
Puedes usar y redistribuir kwhisper, incluso junto a software comercial cerrado.
Pero si **modificas** un fichero cubierto, debes publicar el código fuente de
**ese fichero** bajo MPL-2.0. Lo que añadas en ficheros nuevos puede ser cerrado.
