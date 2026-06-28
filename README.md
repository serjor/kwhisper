# kwhisper

**Languages:** [English](README.md) · [Español](README.es.md)

**Local, private voice dictation for Linux** — a free & open-source alternative to
Wispr Flow, Dragon and cloud "voice typing". Hold a key, speak, release → the text
appears in whatever window is focused. **Everything runs on your machine: your
voice never leaves your computer.** Polished on **KDE Plasma 6 (Wayland)**, but the
core dictation runs without an NVIDIA GPU too.

<!-- TODO: a 20–30 s demo (GIF/WebM) belongs right here — it's worth more than any
     paragraph. Show: dictating a sentence with accents, an "open firefox" command,
     and the spoken question mode.   ![kwhisper demo](docs/demo.gif)  -->

An **optional** local LLM decides whether what you said is **dictation** (it gets
typed) or a **command** (it gets executed: open apps, press keys). Turn it off and
you get plain, fully private dictation.

- **STT**: `faster-whisper` — an NVIDIA GPU gives near-instant results, or it runs
  on **CPU** if you don't have one.
- **Dictation/command classification** *(optional)*: Ollama (`gemma3`).
- **Activation**: push-to-talk via `evdev` (hold the key down).
- **Injection**: clipboard + `Ctrl+V` (Spanish accents 100% reliable in KWin).
- **UI**: tray icon + floating overlay + sounds.
- **Voice (TTS, optional)**: reads confirmations and answers questions aloud
  (Piper in Castilian Spanish, or Kokoro/Chatterbox) from an isolated subprocess.
  Off by default.

## What's supported

kwhisper is **built and verified** on the author's machine. Here's the honest
breakdown so you know what to expect before installing:

| Setup | Status |
|---|---|
| KDE Plasma 6 Wayland · NVIDIA (incl. Blackwell `sm_120`) · PipeWire | ✅ **Verified** — near-instant dictation, overlay, terminal detection, reliable accents |
| KDE Plasma 6 Wayland · **no NVIDIA / CPU-only** | 🟡 **Works (CPU fallback)** — set `[stt] device = "cpu"`, `compute_type = "int8"` and a smaller model (`small` is the sweet spot). Verified: `small` transcribes at ~0.2× real-time on a modern multi-core CPU (i.e. several times faster than you speak), accents intact. Not the author's daily GPU path, but usable day-to-day |
| Other Wayland compositors (GNOME, Sway…) | 🧪 **Experimental** — basic paste (wl-clipboard + ydotool) may work, but the **anchored overlay and terminal detection rely on KWin**. Untested |
| X11 | ❌ Not targeted |

The design notes below explain *why* the verified setup looks so specific: they are
NVIDIA-Blackwell and KWin-on-Wayland workarounds, not arbitrary requirements.

---

## Why these decisions (they aren't the obvious ones)

Three Wayland/Blackwell pitfalls that shape the design:

1. **Blackwell GPU (`sm_120`)**: `faster-whisper` works, but **you have to use
   `float16`** — INT8 gives `CUBLAS_STATUS_NOT_SUPPORTED` on RTX 50xx with old
   CTranslate2. The CUDA 12 wheels run on your driver 610 thanks to backward
   compatibility.
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
- **GPU optional**: an NVIDIA GPU (recent driver; tested on the 50xx series, 16 GB
  VRAM is plenty) gives near-instant dictation. Without one, kwhisper falls back to
  CPU — slower, so pick a smaller model (`small`/`medium`).
- `uv`, `pipewire`. **`ollama` (with `gemma3`) is optional** — it only adds command
  classification and punctuation fixing; set `[llm] enabled = false` for raw dictation.

## Installation

```fish
# Clone it WHEREVER YOU WANT: setup.sh detects the path automatically.
cd /path/where/you/cloned/kwhisper
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

Command examples (natural language):

| You say | Action |
|---|---|
| «open firefox» | launches Firefox |
| «launch the konsole terminal» | opens Konsole |
| «press enter» | sends Return |
| «last year I went to Spain» | the text is **dictated** |

> When in doubt, the classifier types it (dictation). If Ollama isn't available,
> kwhisper keeps working as dictation only.

### Voice (TTS) — optional

With `[tts] enabled = true` (install the extra first, see Installation):

- **Spoken feedback**: command confirmations are read aloud (Kokoro).
- **Question mode**: if you open with an activation phrase ("oye asistente …",
  "oye kwhisper …"), what follows is sent to the LLM and the answer is **read**
  (not typed). E.g. "oye asistente, ¿qué hora es?". Press PTT again to cut a long
  answer (barge-in).

The neural engines run in an **isolated subprocess** so torch (Chatterbox) can't
break Blackwell's faster-whisper: if they fail, only TTS goes down, never dictation.

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

## License

[MPL-2.0](LICENSE) (Mozilla Public License 2.0): file-level copyleft.
You can use and redistribute kwhisper, even alongside closed commercial software.
But if you **modify** a covered file, you must publish the source code of **that
file** under MPL-2.0. Whatever you add in new files can be closed.
