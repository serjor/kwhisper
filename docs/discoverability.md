# Discoverability and accurate project metadata

kwhisper is local voice dictation for KDE Plasma 6 on Wayland, with
faster-whisper, optional Ollama voice commands, a personal dictionary and optional
spoken answers. Arch Linux/CachyOS is the installer target. Keep this description
consistent across the README, package metadata and GitHub About section.

## GitHub About: apply once with a maintainer account

At the September 2026 review, the public repository had no description, topics or
homepage, and GitHub Pages was disabled. Description and topics are repository
settings: committing files does not update them. With GitHub CLI installed and
authenticated to an account allowed to edit this repository, run:

```bash
gh repo edit serjor/kwhisper \
  --description 'Local voice dictation for KDE Plasma on Wayland, with faster-whisper and optional Ollama voice commands.' \
  --add-topic linux \
  --add-topic kde \
  --add-topic kde-plasma \
  --add-topic wayland \
  --add-topic speech-to-text \
  --add-topic voice-dictation \
  --add-topic voice-typing \
  --add-topic whisper \
  --add-topic faster-whisper \
  --add-topic ollama \
  --add-topic push-to-talk \
  --add-topic offline \
  --add-topic python \
  --add-topic text-to-speech
```

This adds relevant topics without removing existing ones. Alternatively, use the
gear next to **About** on the repository page. Leave the website field empty
until a real project website is published. Verify the result with:

```bash
gh repo view serjor/kwhisper --json description,repositoryTopics,url
```

[GitHub topics](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)
help people find related repositories. The command uses the documented
[GitHub CLI repository settings options](https://cli.github.com/manual/gh_repo_edit).

## What repository changes can and cannot do

Descriptive headings, useful English/Spanish documentation, relevant links and
accurate features help readers and search engines understand the project. Package
keywords/classifiers describe distribution metadata; they do not change GitHub
topics, publish to PyPI or guarantee search placement.

GitHub controls the HTML head, canonical URLs, robots rules and sitemaps on
github.com. Adding a root `robots.txt`, a sitemap, HTML meta tags or JSON-LD to a
repository README would not configure those settings for the repository page.
Search Console URL inspection requires ownership of the site being inspected;
owning a GitHub repository does not give control over github.com.

## Next steps for a separate public website

If a project website is published later, use its actual production URL in the
About field and README. Serve readable HTML with English and Spanish pages,
descriptive titles and summaries, self-canonical links and reciprocal `hreflang`
links. Include installation prerequisites, supported desktops and the privacy
conditions from the README. Publish a sitemap containing only live canonical
pages; a `robots.txt` must be served at the origin root to apply. A project Pages
path such as `/kwhisper/robots.txt` does not control the origin's crawler rules.

SoftwareApplication structured data should describe only implemented features;
do not invent reviews, ratings or compatibility claims. Verify ownership of the
website in Search Console, then submit its sitemap and inspect its URLs. These
steps are for a deployed website; this repository change does not publish one
or submit an indexing request.

Google explains the limits and process in its
[SEO starter guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide)
and [recrawling documentation](https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl).
Indexing and ranking are search-engine decisions, and changes take time.

## Evidence to keep claims honest

| Claim | Implementation to check |
|---|---|
| In-memory microphone capture and local Whisper inference | `src/kwhisper/audio.py`, `src/kwhisper/stt.py` |
| CUDA defaults; CPU must be selected explicitly | `src/kwhisper/config.py`, `STTEngine.load()` |
| Optional Ollama; configurable server; Spanish built-in prompts | `src/kwhisper/llm.py`, `src/kwhisper/config.py` |
| Open/close applications and send key combinations | `src/kwhisper/commands.py` |
| Clipboard paste and KWin integration | `src/kwhisper/inject.py`, `src/kwhisper/window.py` |
| User-taught vocabulary and replacement rules | `src/kwhisper/dictionary.py` |
| TTS disabled by default; Piper default; question mode needs Ollama | `src/kwhisper/config.py`, `src/kwhisper/app.py`, `src/kwhisper/tts.py` |
| Arch/CachyOS setup, including CUDA dependencies | `scripts/setup.sh`, `pyproject.toml` |

Record a real short demonstration on the supported desktop before adding a demo
image or video to the README. Link the repository from a maintainer-controlled
profile or project page. Release notes should describe tested changes and link
to installation instructions. Recheck the two READMEs when defaults or supported
platforms change; avoid universal compatibility or unqualified latency claims.
