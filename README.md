# kwhisper

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
cd ~/Projects/kde/kwhisper
bash scripts/setup.sh
```

El script (idempotente, pide confirmación antes de cada cambio con `sudo`):

1. Instala paquetes del sistema: `pyside6 ydotool wl-clipboard libnotify libcanberra ffmpeg python-evdev`.
2. (Opcional, AUR) `kdotool`. **No es necesario**: si no está, kwhisper detecta
   la terminal de forma nativa por el D-Bus de KWin (sin AUR). Sáltatelo sin miedo.
3. Crea el venv con `uv` (`--system-site-packages` para reutilizar el PySide6 de pacman) e instala kwhisper + libs CUDA.
4. Te añade al grupo `input` (push-to-talk). **Requiere cerrar sesión y volver a entrar.**
5. Activa `ydotool.service` (usuario) e instala la unidad `kwhisper.service`.

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

## Configuración

`~/.config/kwhisper/config.toml` (se crea solo la primera vez). Tras editar:
`systemctl --user restart kwhisper`. Claves útiles:

- `[hotkey] backend` — `"evdev"` (push-to-talk) o `"portal"` (toggle, sin grupo input).
- `[hotkey] key` — tecla PTT (usa `kwhisper-findkey`).
- `[stt] model` — `large-v3-turbo` (rápido) o `large-v3` (más preciso en audio difícil).
- `[stt] language` — `"es"` o `""` para autodetección.
- `[llm] enabled` — `false` para desactivar comandos (solo dictado).
- `[inject] method` — `"clipboard"` (recomendado) o `"dotool"`.
- `[commands] allow_launch` — permitir abrir aplicaciones por voz.

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
- [ ] Diálogo de configuración gráfico (PySide6).
- [ ] Comandos de edición fijos («nueva línea», «borra eso»).
- [ ] Plasmoid de panel opcional (estado vía D-Bus).
- [ ] PKGBUILD para AUR.

## Licencia

GPL-3.0-or-later.
