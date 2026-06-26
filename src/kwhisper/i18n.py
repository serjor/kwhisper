# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Minimal internationalization for user-facing strings (overlay, notifications,
tray menu and the CLI tools).

Lightweight on purpose: a flat dict catalog per language and a ``t(key, **kw)``
lookup with ``str.format`` interpolation. English (``en``) is the base catalog
and the fallback when a key is missing in another language.

Diagnostic logs and internal/programmer errors are NOT translated here — they
stay in English by convention (they are read in ``journalctl``/tracebacks).

Language selection:
* ``set_language("es"|"en")`` forces a language.
* ``set_language("auto")`` (or an empty/unknown value) detects it from the
  locale environment (``LC_ALL``/``LC_MESSAGES``/``LANG``), defaulting to ``en``.

At import time the language is auto-detected from the locale, so tools that do
not read the config (e.g. ``kwhisper-findkey``) still get the right language.
The daemon and the other CLI tools override it with the configured ``[ui] lang``.
"""

from __future__ import annotations

import os

SUPPORTED = ("en", "es")

_CATALOG: dict[str, dict[str, str]] = {
    "en": {
        # --- app: overlay ---
        "overlay.recording": "🎙  Recording…",
        "overlay.processing": "⏳  Processing…",
        "overlay.error": "⚠  Error",
        # --- app: notifications ---
        "notify.command": "Command",
        "ready": "Ready to dictate.",
        "stt.load_error": "Error loading STT: {error}",
        "recording.too_short": "Recording too short.",
        "model.loading": "The model is still loading.",
        "no_speech": "No speech detected.",
        "mic.error": "Microphone error: {error}",
        "error.generic": "Error: {error}",
        "dictation.on": "Dictation enabled",
        "dictation.off": "Dictation disabled",
        # --- hotkey (evdev) ---
        "hotkey.no_permission_short": "No keyboard permission (input group). "
                                      "Check the logs or use backend=portal.",
        "hotkey.start_failed": "Could not start the hotkey. Check the logs.",
        "hotkey.unknown_key": "Unknown key: {key}. Use `kwhisper-findkey` to "
                              "discover the correct name (e.g. KEY_PAUSE).",
        "hotkey.no_input_permission": "No permission to read /dev/input. Add yourself to the input group:\n"
                                      "  sudo usermod -aG input $USER   (then log back in)\n"
                                      'Or use the portal fallback:  [hotkey] backend = "portal"',
        "hotkey.no_device": "No device exposes the key {key}. "
                            "Check with `kwhisper-findkey` or set [hotkey] device.",
        # --- hotkey (portal) ---
        "portal.no_response": "The shortcuts portal did not respond (timeout). "
                              "Is xdg-desktop-portal-kde running? The hotkey will not work.",
        "portal.no_session": "The portal did not return a session_handle; the hotkey will not work.",
        "portal.shortcut_desc": "kwhisper: dictate (toggle)",
        # --- tray ---
        "tray.idle": "kwhisper: ready",
        "tray.recording": "kwhisper: recording…",
        "tray.processing": "kwhisper: processing…",
        "tray.error": "kwhisper: error",
        "tray.disabled": "kwhisper: disabled",
        "tray.edit_config": "Edit configuration…",
        "tray.quit": "Quit",
        # --- settings dialog ---
        "settings.menu": "Settings…",
        "settings.title": "kwhisper — Settings",
        "settings.language": "Interface language",
        "settings.lang_auto": "Automatic (system)",
        "settings.model": "Ollama model",
        "settings.model_refresh": "Refresh",
        "settings.model_found": "{count} model(s) found in Ollama.",
        "settings.model_none": "Ollama is not responding — type the model name manually.",
        "settings.advanced": "Advanced",
        "settings.system_prompt": "System prompt (LLM)",
        "settings.prompt_warning": "Editing the system prompt can BREAK command "
                                   "recognition and dictation punctuation. Change it only "
                                   "if you know what you are doing — use “Restore default "
                                   "prompt” to roll back.",
        "settings.restore_default": "Restore default prompt",
        "settings.save": "Save",
        "settings.cancel": "Cancel",
        "settings.saved": "Settings saved.",
        # --- first-run wizard ---
        "wizard.title": "Welcome to kwhisper",
        "wizard.intro": "Let’s set up the basics. You can change these anytime from the "
                        "tray menu → Settings.",
        "wizard.finish": "Finish",
        # --- commands ---
        "cmd.no_action": "No action.",
        "cmd.open_no_app": "'open' command without an application.",
        "cmd.launch_disabled": "Launching applications is disabled in the config.",
        "cmd.opening": "Opening {app}",
        "cmd.app_not_found": "Application '{app}' not found.",
        "cmd.open_error": "Error opening {app}: {error}",
        "cmd.close_no_app": "'close' command without an application.",
        "cmd.close_disabled": "Closing applications is disabled in the config.",
        "cmd.closing": "Closing {app}",
        "cmd.app_not_running": "'{app}' does not seem to be running.",
        "cmd.close_error": "Error closing {app}: {error}",
        "cmd.press_no_key": "'press' command without a key.",
        "cmd.no_evdev": "python-evdev not available to resolve keys.",
        "cmd.unknown_key": "Unknown key: {key}",
        "cmd.pressed": "Pressed {combo}",
        "cmd.press_failed": "Failed to press {combo}: {error}",
        "cmd.no_ydotool": "ydotool not installed.",
        # --- inject ---
        "inject.unknown_paste_key": "Unknown key in paste combination: {key}",
        "inject.clipboard_requires": "Clipboard injection requires 'ydotool' and 'wl-copy'. "
                                     "Install: sudo pacman -S ydotool wl-clipboard",
        "inject.paste_failed": "Paste failed: {error}",
        "inject.dotool_failed": "dotool failed: {error}",
        # --- findkey ---
        "findkey.no_evdev": "python-evdev is missing. Install with: sudo pacman -S python-evdev",
        "findkey.no_keyboard": "No keyboard found. Are you in the 'input' group?",
        "findkey.no_keyboard_hint": "  sudo usermod -aG input $USER   (then log out and back in)",
        "findkey.prompt": "Press the key you want to use for push-to-talk (Ctrl+C to exit)…\n",
        "findkey.key_line": "  key: {name}   (code={code})   device: {path} — {dev}",
        "findkey.config_hint": '\n  → put in ~/.config/kwhisper/config.toml:  key = "{name}"\n',
        "findkey.done": "\nDone.",
        # --- doctor: section headers ---
        "doctor.title": "kwhisper doctor — python {ver}",
        "doctor.sec_gpu": "GPU / CUDA",
        "doctor.sec_wayland": "Wayland / injection",
        "doctor.sec_permissions": "Permissions",
        "doctor.sec_ollama": "Ollama (command classification)",
        # --- doctor: gpu ---
        "doctor.nvidia_smi_failed": "nvidia-smi failed",
        "doctor.nvidia_smi_not_found": "nvidia-smi not found",
        "doctor.ct2_detail": "{ver} (recommended ≥4.7 for int8 on sm_120; float16 always works)",
        "doctor.ct2_not_importable": "ctranslate2 not importable",
        "doctor.fw_importable": "faster-whisper importable",
        "doctor.fw_not_importable": "faster-whisper not importable",
        "doctor.mod_present": "{mod} present",
        "doctor.mod_absent": "{mod} absent",
        "doctor.mod_absent_detail": "system CUDA will be used (check LD_LIBRARY_PATH)",
        # --- doctor: wayland ---
        "doctor.tool_not_installed": "{tool} not installed",
        "doctor.optional": "optional",
        "doctor.ydotool_socket": "ydotoold socket",
        "doctor.ydotool_socket_missing": "ydotoold socket does not exist",
        "doctor.ydotool_socket_hint": "{sock} — start: systemctl --user enable --now ydotool",
        "doctor.dbus_bus": "D-Bus session bus",
        "doctor.dbus_bus_absent": "D-Bus session bus absent",
        "doctor.dbus_bus_absent_detail": "no DBUS_SESSION_BUS_ADDRESS nor $XDG_RUNTIME_DIR/bus — KWin is unreachable",
        "doctor.term_detect": "terminal detection",
        "doctor.term_detect_none": "no backend — always Ctrl+V (install kdotool or KWin/gdbus)",
        "doctor.term_detect_backend": "backend: {backend}",
        # --- doctor: permissions ---
        "doctor.input_group": "input group",
        "doctor.input_group_detail": "evdev push-to-talk available",
        "doctor.no_input_group": "you are not in the input group",
        "doctor.no_input_group_detail": "sudo usermod -aG input $USER (relogin) — or use backend=portal",
        "doctor.uinput_writable": "/dev/uinput writable",
        "doctor.uinput_writable_detail": "ydotool can inject",
        "doctor.uinput_not_writable": "/dev/uinput not writable",
        "doctor.uinput_not_writable_detail": "logind ACL absent; is the session active?",
        # --- doctor: ollama ---
        "doctor.ollama_responds": "Ollama responds",
        "doctor.model_available": "model '{model}' available",
        "doctor.model_missing": "model '{model}' not present",
        "doctor.model_missing_detail": "ollama pull {model}  · you have: {have}",
        "doctor.ollama_unavailable": "Ollama not available",
        "doctor.ollama_unavailable_detail": "{error} (dictation still works, without commands)",
        # --- doctor: footer ---
        "doctor.config_exists": "exists",
        "doctor.config_will_create": "will be created at startup",
        "doctor.config_line": "Config: {path} ({state})",
        # --- smoke_stt ---
        "smoke.loading": "Loading model '{model}' ({compute}) on {device}…",
        "smoke.model_ready": "Model ready in {secs:.1f}s.\n",
        "smoke.speak": "🎙  Speak for {seconds:.0f} s…",
        "smoke.recorded": "Recorded {secs:.1f}s. Transcribing…\n",
        "smoke.transcribed_in": "⏱  Transcription in {secs:.2f}s",
        # --- TTS (voice output) ---
        "overlay.thinking": "🤔  Thinking…",
        "answer.failed": "No answer.",
        "settings.tts_enable": "Voice output (TTS)",
        "settings.tts_feedback": "Speak confirmations",
        "settings.tts_answers": "Speak answers (question mode)",
        "settings.tts_voice": "Voice",
        "doctor.sec_tts": "TTS (voice output)",
        "doctor.tts_disabled": "TTS disabled in config ([tts] enabled = false)",
        "doctor.tts_model_present": "{model} present",
        "doctor.tts_model_absent": "{model} missing",
        "doctor.tts_model_absent_detail": "download it (scripts/setup.sh) into {dir}",
        "doctor.tts_kokoro_ok": "kokoro-onnx importable",
        "doctor.tts_kokoro_fail": "kokoro-onnx not importable (install the 'tts' extra)",
        "doctor.tts_torch_gpu": "torch CUDA available (Chatterbox can run on GPU)",
        "doctor.tts_torch_cpu": "torch present but CUDA unavailable (Chatterbox would fail)",
        "doctor.tts_chatterbox_fail": "chatterbox/torch not importable (install the 'tts-chatterbox' extra)",
    },
    "es": {
        # --- app: overlay ---
        "overlay.recording": "🎙  Grabando…",
        "overlay.processing": "⏳  Procesando…",
        "overlay.error": "⚠  Error",
        # --- app: notifications ---
        "notify.command": "Comando",
        "ready": "Listo para dictar.",
        "stt.load_error": "Error cargando STT: {error}",
        "recording.too_short": "Grabación demasiado corta.",
        "model.loading": "El modelo aún se está cargando.",
        "no_speech": "No se detectó voz.",
        "mic.error": "Error de micrófono: {error}",
        "error.generic": "Error: {error}",
        "dictation.on": "Dictado activado",
        "dictation.off": "Dictado desactivado",
        # --- hotkey (evdev) ---
        "hotkey.no_permission_short": "Sin permiso de teclado (grupo input). "
                                      "Mira los logs o usa backend=portal.",
        "hotkey.start_failed": "No se pudo iniciar el hotkey. Revisa los logs.",
        "hotkey.unknown_key": "Tecla desconocida: {key}. Usa `kwhisper-findkey` "
                              "para descubrir el nombre correcto (p.ej. KEY_PAUSE).",
        "hotkey.no_input_permission": "Sin permiso para leer /dev/input. Añádete al grupo input:\n"
                                      "  sudo usermod -aG input $USER   (y vuelve a iniciar sesión)\n"
                                      'O usa el fallback del portal:  [hotkey] backend = "portal"',
        "hotkey.no_device": "Ningún dispositivo expone la tecla {key}. "
                            "Comprueba con `kwhisper-findkey` o fija [hotkey] device.",
        # --- hotkey (portal) ---
        "portal.no_response": "El portal de atajos no respondió (timeout). "
                              "¿xdg-desktop-portal-kde activo? El hotkey no funcionará.",
        "portal.no_session": "El portal no devolvió session_handle; el hotkey no funcionará.",
        "portal.shortcut_desc": "kwhisper: dictar (toggle)",
        # --- tray ---
        "tray.idle": "kwhisper: listo",
        "tray.recording": "kwhisper: grabando…",
        "tray.processing": "kwhisper: procesando…",
        "tray.error": "kwhisper: error",
        "tray.disabled": "kwhisper: desactivado",
        "tray.edit_config": "Editar configuración…",
        "tray.quit": "Salir",
        # --- settings dialog ---
        "settings.menu": "Ajustes…",
        "settings.title": "kwhisper — Ajustes",
        "settings.language": "Idioma de la interfaz",
        "settings.lang_auto": "Automático (sistema)",
        "settings.model": "Modelo de Ollama",
        "settings.model_refresh": "Actualizar",
        "settings.model_found": "{count} modelo(s) encontrado(s) en Ollama.",
        "settings.model_none": "Ollama no responde — escribe el nombre del modelo a mano.",
        "settings.advanced": "Avanzado",
        "settings.system_prompt": "Prompt de sistema (LLM)",
        "settings.prompt_warning": "Editar el prompt de sistema puede ROMPER el "
                                   "reconocimiento de comandos y la puntuación del dictado. "
                                   "Cámbialo solo si sabes lo que haces — usa “Restaurar "
                                   "prompt por defecto” para deshacer.",
        "settings.restore_default": "Restaurar prompt por defecto",
        "settings.save": "Guardar",
        "settings.cancel": "Cancelar",
        "settings.saved": "Ajustes guardados.",
        # --- first-run wizard ---
        "wizard.title": "Bienvenido a kwhisper",
        "wizard.intro": "Vamos a configurar lo básico. Puedes cambiarlo cuando quieras "
                        "desde el menú de la bandeja → Ajustes.",
        "wizard.finish": "Finalizar",
        # --- commands ---
        "cmd.no_action": "Sin acción.",
        "cmd.open_no_app": "Comando 'abrir' sin aplicación.",
        "cmd.launch_disabled": "Lanzar aplicaciones está desactivado en la config.",
        "cmd.opening": "Abriendo {app}",
        "cmd.app_not_found": "No encuentro la aplicación '{app}'.",
        "cmd.open_error": "Error al abrir {app}: {error}",
        "cmd.close_no_app": "Comando 'cerrar' sin aplicación.",
        "cmd.close_disabled": "Cerrar aplicaciones está desactivado en la config.",
        "cmd.closing": "Cerrando {app}",
        "cmd.app_not_running": "'{app}' no parece estar en ejecución.",
        "cmd.close_error": "Error al cerrar {app}: {error}",
        "cmd.press_no_key": "Comando 'pulsar' sin tecla.",
        "cmd.no_evdev": "python-evdev no disponible para resolver teclas.",
        "cmd.unknown_key": "Tecla desconocida: {key}",
        "cmd.pressed": "Pulsado {combo}",
        "cmd.press_failed": "Fallo al pulsar {combo}: {error}",
        "cmd.no_ydotool": "ydotool no instalado.",
        # --- inject ---
        "inject.unknown_paste_key": "Tecla desconocida en combinación de pegado: {key}",
        "inject.clipboard_requires": "Inyección por portapapeles requiere 'ydotool' y 'wl-copy'. "
                                     "Instala: sudo pacman -S ydotool wl-clipboard",
        "inject.paste_failed": "Fallo al pegar: {error}",
        "inject.dotool_failed": "dotool falló: {error}",
        # --- findkey ---
        "findkey.no_evdev": "Falta python-evdev. Instala con: sudo pacman -S python-evdev",
        "findkey.no_keyboard": "No se encontró ningún teclado. ¿Estás en el grupo 'input'?",
        "findkey.no_keyboard_hint": "  sudo usermod -aG input $USER   (luego cierra sesión y vuelve a entrar)",
        "findkey.prompt": "Pulsa la tecla que quieras usar para push-to-talk (Ctrl+C para salir)…\n",
        "findkey.key_line": "  tecla: {name}   (code={code})   dispositivo: {path} — {dev}",
        "findkey.config_hint": '\n  → pon en ~/.config/kwhisper/config.toml:  key = "{name}"\n',
        "findkey.done": "\nFin.",
        # --- doctor: section headers ---
        "doctor.title": "kwhisper doctor — python {ver}",
        "doctor.sec_gpu": "GPU / CUDA",
        "doctor.sec_wayland": "Wayland / inyección",
        "doctor.sec_permissions": "Permisos",
        "doctor.sec_ollama": "Ollama (clasificación de comandos)",
        # --- doctor: gpu ---
        "doctor.nvidia_smi_failed": "nvidia-smi falló",
        "doctor.nvidia_smi_not_found": "nvidia-smi no encontrado",
        "doctor.ct2_detail": "{ver} (recomendado ≥4.7 para int8 en sm_120; float16 va siempre)",
        "doctor.ct2_not_importable": "ctranslate2 no importable",
        "doctor.fw_importable": "faster-whisper importable",
        "doctor.fw_not_importable": "faster-whisper no importable",
        "doctor.mod_present": "{mod} presente",
        "doctor.mod_absent": "{mod} ausente",
        "doctor.mod_absent_detail": "se usará CUDA del sistema (revisa LD_LIBRARY_PATH)",
        # --- doctor: wayland ---
        "doctor.tool_not_installed": "{tool} no instalado",
        "doctor.optional": "opcional",
        "doctor.ydotool_socket": "socket ydotoold",
        "doctor.ydotool_socket_missing": "socket ydotoold no existe",
        "doctor.ydotool_socket_hint": "{sock} — arranca: systemctl --user enable --now ydotool",
        "doctor.dbus_bus": "bus de sesión D-Bus",
        "doctor.dbus_bus_absent": "bus de sesión D-Bus ausente",
        "doctor.dbus_bus_absent_detail": "sin DBUS_SESSION_BUS_ADDRESS ni $XDG_RUNTIME_DIR/bus — KWin no es alcanzable",
        "doctor.term_detect": "detección de terminal",
        "doctor.term_detect_none": "sin backend — siempre Ctrl+V (instala kdotool o KWin/gdbus)",
        "doctor.term_detect_backend": "backend: {backend}",
        # --- doctor: permissions ---
        "doctor.input_group": "grupo input",
        "doctor.input_group_detail": "push-to-talk evdev disponible",
        "doctor.no_input_group": "no estás en el grupo input",
        "doctor.no_input_group_detail": "sudo usermod -aG input $USER (relogin) — o usa backend=portal",
        "doctor.uinput_writable": "/dev/uinput escribible",
        "doctor.uinput_writable_detail": "ydotool puede inyectar",
        "doctor.uinput_not_writable": "/dev/uinput no escribible",
        "doctor.uinput_not_writable_detail": "ACL de logind ausente; ¿sesión activa?",
        # --- doctor: ollama ---
        "doctor.ollama_responds": "Ollama responde",
        "doctor.model_available": "modelo '{model}' disponible",
        "doctor.model_missing": "modelo '{model}' no está",
        "doctor.model_missing_detail": "ollama pull {model}  · tienes: {have}",
        "doctor.ollama_unavailable": "Ollama no disponible",
        "doctor.ollama_unavailable_detail": "{error} (el dictado funciona igual, sin comandos)",
        # --- doctor: footer ---
        "doctor.config_exists": "existe",
        "doctor.config_will_create": "se creará al arrancar",
        "doctor.config_line": "Config: {path} ({state})",
        # --- smoke_stt ---
        "smoke.loading": "Cargando modelo '{model}' ({compute}) en {device}…",
        "smoke.model_ready": "Modelo listo en {secs:.1f}s.\n",
        "smoke.speak": "🎙  Habla durante {seconds:.0f} s…",
        "smoke.recorded": "Grabados {secs:.1f}s. Transcribiendo…\n",
        "smoke.transcribed_in": "⏱  Transcripción en {secs:.2f}s",
        # --- TTS (voice output) ---
        "overlay.thinking": "🤔  Pensando…",
        "answer.failed": "Sin respuesta.",
        "settings.tts_enable": "Salida de voz (TTS)",
        "settings.tts_feedback": "Leer confirmaciones",
        "settings.tts_answers": "Leer respuestas (modo pregunta)",
        "settings.tts_voice": "Voz",
        "doctor.sec_tts": "TTS (salida de voz)",
        "doctor.tts_disabled": "TTS desactivado en la config ([tts] enabled = false)",
        "doctor.tts_model_present": "{model} presente",
        "doctor.tts_model_absent": "{model} ausente",
        "doctor.tts_model_absent_detail": "descárgalo (scripts/setup.sh) en {dir}",
        "doctor.tts_kokoro_ok": "kokoro-onnx importable",
        "doctor.tts_kokoro_fail": "kokoro-onnx no importable (instala el extra 'tts')",
        "doctor.tts_torch_gpu": "torch con CUDA (Chatterbox puede usar GPU)",
        "doctor.tts_torch_cpu": "torch presente pero CUDA no disponible (Chatterbox fallaría)",
        "doctor.tts_chatterbox_fail": "chatterbox/torch no importable (instala el extra 'tts-chatterbox')",
    },
}


def _detect() -> str:
    """Detect the language from the locale environment; default to English."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val:
            code = val.split(".")[0].split("_")[0].lower()
            return code if code in _CATALOG else "en"
    return "en"


_lang = _detect()


def set_language(lang: str | None) -> None:
    """Set the active language. ``"auto"``/empty/unknown → locale autodetection."""
    global _lang
    if not lang or lang == "auto":
        _lang = _detect()
    elif lang in _CATALOG:
        _lang = lang
    else:
        _lang = "en"


def get_language() -> str:
    return _lang


def t(key: str, **kwargs) -> str:
    """Translate ``key`` into the active language (falling back to English).

    Remaining ``kwargs`` are interpolated with ``str.format``.
    """
    table = _CATALOG.get(_lang, _CATALOG["en"])
    text = table.get(key)
    if text is None:
        text = _CATALOG["en"].get(key, key)
    return text.format(**kwargs) if kwargs else text
