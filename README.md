# kwhisper — local voice dictation for KDE Plasma and Wayland

**Languages:** [English](README.md) · [Español](README.es.md)

**kwhisper turns speech into text and pastes it into the focused application on
your Linux desktop.** Hold a key, speak and release: speech recognition runs
locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
It is designed for **KDE Plasma 6 on Wayland**, with an installer for **Arch Linux
and CachyOS**, and is free and open-source software under [MPL-2.0](LICENSE).

If you are looking for voice typing or a local alternative to tools such as
Wispr Flow or Dragon on KDE, that is the use case. Supported platforms and
features are listed below; this is not a claim of feature parity.

- **Whisper dictation**: NVIDIA CUDA or explicitly configured CPU inference.
- **Optional voice control with Ollama**: punctuation correction, opening or
  closing applications, and key presses. `gemma3` is the default model.
- **Activation**: `evdev` push-to-talk, or a portal shortcut in toggle mode.
- **KDE integration**: clipboard paste, terminal detection, system tray and overlay.
- **Personal dictionary**: custom vocabulary and recurring transcription fixes.
- **Optional spoken answers**: Piper (default), Kokoro or Chatterbox;
  text-to-speech is disabled by default.

**Start here:** [Installation](#installation) · [CPU-only setup](#cpu-only-dictation) ·
[Usage](#usage) · [Privacy](#privacy-and-offline-use) ·
[Configuration](#configuration) · [Report an issue](https://github.com/serjor/kwhisper/issues)

## What's supported

kwhisper is **built and verified** on the author's machine. Here's the honest
breakdown so you know what to expect before installing:

| Setup | Status |
|---|---|
| KDE Plasma 6 Wayland · NVIDIA (incl. Blackwell `sm_120`) · PipeWire | ✅ **Author's primary environment** — dictation, overlay and terminal detection; latency depends on hardware and model |
| KDE Plasma 6 Wayland · **no NVIDIA / CPU-only** | **Configurable** — set `device = "cpu"`, `compute_type = "int8"` and a model such as `small`. There is no automatic CUDA-to-CPU fallback; performance depends on hardware |
| Other Wayland compositors (GNOME, Sway…) | 🧪 **Experimental** — basic paste (wl-clipboard + ydotool) may work, but the **anchored overlay and terminal detection rely on KWin**. Untested |
| X11 | ❌ Not targeted |

The design notes below explain *why* the verified setup looks so specific: they are
NVIDIA-Blackwell and KWin-on-Wayland workarounds, not arbitrary requirements.

---

## Why these decisions (they aren't the obvious ones)

Three Wayland/Blackwell pitfalls that shape the design:

1. **Blackwell GPU (`sm_120`)**: `faster-whisper` works, but **you have to use
   `float16`** — INT8 gives `CUBLAS_STATUS_NOT_SUPPORTED` on RTX 50xx with old
   CTranslate2. The default configuration uses `float16`.
2. **Push-to-talk**: KDE's shortcut portal **loses the key-release event** if you
   type while dictating (KWin bug 483183). That's why the keyboard is read with
   **`evdev`** (requires the `input` group). The portal remains as a *fallback*
   in toggle mode.
3. **Accents**: no tool types `ñ á ¿ ¡ ü` reliably in KWin (`ydotool type`
   breaks Unicode; `wtype` doesn't support KWin). That's why we use
   **clipboard + Ctrl+V**: the character travels as data and only a fixed
   shortcut is simulated.

---

## Requirements

- A **Wayland session** (KDE Plasma 6 recommended — that's where the overlay,
  terminal detection and accents are verified). Arch/CachyOS is the tested base.
- A **microphone** and PipeWire.
- **Python 3.11 or later** and PySide6 (the installer uses the system package).
- **GPU optional**: CUDA is enabled by default. Without an NVIDIA GPU, configure
  [CPU-only dictation](#cpu-only-dictation) before starting the application.
- `uv`, `pipewire`. **`ollama` (with `gemma3`) is optional** — it only adds command
  classification and punctuation fixing; set `[llm] enabled = false` for raw dictation.

## Installation

The installer uses `pacman` and targets Arch Linux/CachyOS; it is not a universal
Linux installer. Install Git and `uv` first.

```bash
git clone https://github.com/serjor/kwhisper.git
cd kwhisper
bash scripts/setup.sh
```

The script (idempotent, asks for confirmation before each `sudo` change):

1. Installs system packages: `pyside6 ydotool wl-clipboard libnotify libcanberra ffmpeg python-evdev`.
2. (Optional, AUR) `kdotool`. **Not required**: if it's missing, kwhisper detects
   the terminal natively through KWin's D-Bus (no AUR). Skip it without worry.
3. Creates the venv with `uv` (`--system-site-packages` to reuse pacman's PySide6) and installs kwhisper + CUDA libs.
4. Adds you to the `input` group (push-to-talk). **Requires logging out and back in.**
5. Enables `ydotool.service` (user) and installs the `kwhisper.service` unit.

The script also **offers (optional) voice/TTS**: it installs Piper and Kokoro and
downloads the default Piper voice models, and optionally Chatterbox with torch
cu128 for Blackwell.

Then:

```fish
# 1. Discover the name of your push-to-talk key
.venv/bin/kwhisper-findkey            # press the key; copy the name (e.g. KEY_PAUSE)

# 2. Put it in the config
$EDITOR ~/.config/kwhisper/config.toml   # [hotkey] key = "KEY_PAUSE"

# 3. Check that everything is in place
.venv/bin/kwhisper-doctor

# 4. Try it by hand (you'll see the icon in the tray)
.venv/bin/kwhisper
```

Once it works, leave it as a service:

```fish
systemctl --user enable --now kwhisper
```

## Quick verification

```fish
# STT + GPU + mic in a single test (records 4s and transcribes):
.venv/bin/python scripts/smoke_stt.py

# Accents through the clipboard (focus an editor; countdown then pastes the string):
bash scripts/test_inject.sh

# Pure logic:
.venv/bin/python tests/test_unit.py
```

## Usage

1. Hold down the PTT key. A tone plays and the overlay «🎙 Recording…» appears.
2. Speak.
3. Release. It transcribes, classifies and:
   - **Dictation** → the text is pasted into the focused window.
   - **Command** → it gets executed (notification with the result).

Command examples (Spanish, matching the built-in prompts):

| You say | Action |
|---|---|
| «abre firefox» | launches Firefox |
| «lanza la terminal konsole» | opens Konsole |
| «pulsa enter» | sends Return |
| «el año pasado fui a España» | the text is **dictated** |

> When in doubt, the classifier types it (dictation). If Ollama isn't available,
> kwhisper keeps working as dictation only.

### Voice (TTS) — optional

With `[tts] enabled = true` (install the extra first, see Installation),
plus `[tts] speak_answers = true` and `[llm] enabled = true` for question mode:

- **Spoken feedback**: command confirmations are read aloud using the configured engine (Piper by default).
- **Question mode**: if you open with an activation phrase ("oye asistente …",
  "oye kwhisper …"), what follows is sent to the LLM and the answer is **read**
  (not typed). E.g. "oye asistente, explica qué es una variable". Press PTT again to cut a long
  answer (barge-in).

The neural engines run in an **isolated subprocess** so torch (Chatterbox) can't
break Blackwell's faster-whisper: if they fail, only TTS goes down, never dictation.

### Personal dictionary — it adapts to you

kwhisper keeps a personal dictionary (`~/.config/kwhisper/dictionary.toml`) that
both **biases recognition** towards your own terms (names, jargon, acronyms) and
**fixes recurring mistakes** (literal `wrong → right` rules applied before pasting).

You teach it from the tray:

- **Correct last dictation…** — opens an editable copy of what was just pasted;
  fix it to how it should have read and kwhisper learns the words you changed
  (rare terms only — proper nouns and jargon, never everyday words). Wayland
  forbids silently reading another app's text field (the trick Wispr Flow uses on
  macOS/Windows), so you bring the text to the dialog; the learning is automatic.
- **Edit dictionary…** — open the TOML to add or prune terms by hand (restart the
  daemon after manual edits).

## CPU-only dictation

Edit or create `~/.config/kwhisper/config.toml` before starting kwhisper. If the
file already contains these sections, update their values instead of duplicating them:

```toml
[stt]
device = "cpu"
compute_type = "int8"
model = "small"
language = "en"

[llm]
enabled = false
```

This enables raw dictation without Ollama. The installer still downloads CUDA
dependencies: CPU configuration changes inference, not the package contents.

## Privacy and offline use

Audio is captured in memory and transcribed locally by Whisper. Once the models
are downloaded, dictation and optional features can run without cloud AI services
when Ollama uses its default local host (`http://127.0.0.1:11434`). Installation
and initial model downloads require an internet connection.

If you set `[llm] host` to a remote server, transcriptions and questions are sent
to that server. The code logs transcription excerpts at INFO level; the personal
dictionary is stored on disk, and text insertion uses the clipboard. Keep this
in mind when sharing diagnostics.

## Languages and assistant scope

The interface supports English and Spanish. Whisper supports other languages
through `[stt] language` (for example `"en"`, or `""` for automatic detection), but
the built-in command and question prompts target Spanish. Changing the interface
language does not translate those prompts.

Question mode is triggered within a user-started recording, not by an always-on
wake-word listener. It generates answers through Ollama; it does not browse the
web or use tools to retrieve the current time or live information.

## Configuration

`~/.config/kwhisper/config.toml` (created automatically the first time). After
editing: `systemctl --user restart kwhisper`. Useful keys:

- `[hotkey] backend` — `"evdev"` (push-to-talk) or `"portal"` (toggle, no input group).
- `[hotkey] key` — PTT key (use `kwhisper-findkey`).
- `[stt] model` — `large-v3-turbo` (fast) or `large-v3` (more accurate on difficult audio).
- `[stt] language` — `"es"`, `"en"`, … or `""` for autodetection.
- `[llm] enabled` — `false` disables the LLM completely (raw dictation, without
  fixing punctuation or classifying commands).
- `[commands] enabled` — `false` doesn't execute commands but, if `[llm] enabled`,
  dictation still benefits from the LLM's punctuation correction.
- `[inject] method` — `"clipboard"` (recommended) or `"dotool"`.
- `[commands] allow_launch` — allow opening applications by voice.
- `[commands] allow_close` — allow closing applications by voice ("cierra firefox";
  sends `SIGTERM` to the matching process so it can save and exit cleanly).
- `[ui] lang` — language of the interface (overlay, notifications, tray) and the
  CLI tools: `"auto"` (detect from the system locale), `"es"` or `"en"`.
- `[tts] enabled` — `false` (default) disables voice. `true` requires the TTS extra
  installed (`scripts/setup.sh` offers it).
- `[tts] speak_feedback` / `speak_answers` — read command confirmations / read the
  question-mode answers.
- `[tts] engine` — `"piper"` (Castilian es-ES, natural, recommended) · `"kokoro"`
  (multilingual, but Latin-American Spanish) · `"chatterbox"` (torch cu128, opt-in; needs Python <3.14).
- `[tts] voice` — per engine: Piper `es_ES-sharvard-medium#1` (female) / `#0` (male) /
  `es_ES-davefx-medium`; Kokoro `ef_dora` (f) · `em_alex` (m) · `em_santa` (m).
- `[tts] activation_phrases` — phrases that open question mode (the transcription
  must **start** with one). Keep them distinctive and multi-word.

## Troubleshooting

- **Doesn't record / "no keyboard permission"** → you're not in the `input` group.
  Run `sudo usermod -aG input $USER` and **log back in**, or use `backend = "portal"`.
- **Doesn't paste text** → check `systemctl --user status ydotool` and that
  `kwhisper-doctor` sees the socket. The cursor must be in a text field.
- **Broken accents** → make sure `method = "clipboard"` (not `dotool`).
- **Pasting shows what you had before in the clipboard** → the target app
  requested it late; raise `[inject] restore_delay` (e.g. to `0.8`).
- **CUDA / `libcudnn` error** → handled by the `LD_LIBRARY_PATH` re-exec; if it
  persists, don't mix it with the system's `python-pytorch` (use the isolated venv).
- **Works by hand but doesn't paste as a service (especially in konsole)** → under
  `systemctl --user` the `DBUS_SESSION_BUS_ADDRESS` is missing, so `gdbus` can't
  reach KWin and terminal detection falls back to `Ctrl+V` (konsole doesn't paste
  with that). kwhisper now derives it from `$XDG_RUNTIME_DIR/bus`; if it still
  fails, `kwhisper-doctor` will tell you whether the «D-Bus session bus» is absent.
  Reinstall the updated unit:
  `systemctl --user daemon-reload && systemctl --user restart kwhisper`.
- **Pastes wrong in a terminal** → terminal detection (to use `Ctrl+Shift+V`)
  uses KWin over D-Bus; check with `kwhisper-doctor` that the backend isn't
  «none». If it is, install `kdotool` or check `gdbus`/`journalctl`. You can also
  force `[inject] paste_key = "ctrl+shift+v"` if you dictate mostly in terminals.
- **View logs**: `journalctl --user -u kwhisper -f` (or `KWHISPER_LOG=DEBUG .venv/bin/kwhisper`).

## Architecture

```
HotkeyListener (evdev) ─KEY_DOWN→ record ─KEY_UP→ AudioRecorder (sounddevice 16k)
        │                                              │ float32 buffer
        ▼                                              ▼
   (1 PySide6 process)                         STTEngine (faster-whisper, VRAM)
   Tray + Overlay + Feedback                          │ text
                                                       ▼
                                       IntentRouter (Ollama gemma3, JSON)
                                          │ dictation          │ command
                                          ▼                    ▼
                                   TextInjector          CommandExecutor
                                (wl-copy + Ctrl+V)     (open app / press key)
```

External processes: `ollama` (:11434), `ydotoold` (--user), KWin/PipeWire.

## Roadmap

- [ ] Dedicated dual hotkey (one key = dictation, another = command) for zero ambiguity.
- [x] Graphical configuration dialog (PySide6) + first-run wizard (language, model, system prompt).
- [x] Voice output (TTS): spoken feedback + question mode with a spoken answer (Kokoro/Chatterbox).
- [ ] Fixed editing commands («new line», «delete that»).
- [ ] Optional panel plasmoid (status via D-Bus).
- [ ] PKGBUILD for the AUR.

## AI contribution disclosure

OpenAI Codex, an AI coding assistant, wrote the audio recovery changes, regression
tests, and Ruff fixes in [PR #13](https://github.com/serjor/kwhisper/pull/13).
Codex also ran the automated checks under the direction of the maintainer, serjor.
This credit applies to those contributions, not to the entire project.

## License

[MPL-2.0](LICENSE) (Mozilla Public License 2.0): file-level copyleft.
You can use and redistribute kwhisper, even alongside closed commercial software.
But if you **modify** a covered file, you must publish the source code of **that
file** under MPL-2.0. Whatever you add in new files can be closed.
