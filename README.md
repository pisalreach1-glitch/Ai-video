# 🎬 Telegram Voiceover Bot (Khmer AI Voiceover & Subtitles)

A button-first Telegram Bot built with **Python 3.10+**, **aiogram 3**, **Edge-TTS**, **FFmpeg**, and **SQLite**. It turns uploaded videos or public links into viral voiceover videos with automatic AI narration in Khmer, animated subtitles, framing options, audio mixing, and realistic previews.

---

## ✨ Features & User Workflow

```
Video Upload OR Public Link
        ↓
Narration Text (from caption or sent as message)
        ↓
Voice & Video Settings (Defaults or Customize)
        ↓
Audio Preview (listen to generated AI voice)
        ↓
Video Preview (5-second realistic preview)
        ↓
Approve & Final Render
        ↓
Final MP4 + SRT Subtitles Delivery
```

- **🎙️ Natural Khmer Voices:** Real Edge-TTS `km-KH-SreymomNeural` (female) and `km-KH-PisethNeural` (male) with rate adjustments (-15%, 1.0x, +15%).
- **📝 High-Precision Subtitles:** Sentence/phrase timing events, styled ASS subtitles burned with bundled `Khmer OS Battambang` font, plus downloadable `.srt` files.
- **📐 Aspect Ratio & Framing:** Original ratio, vertical 9:16 (TikTok/Reel), or square 1:1, using fit (letterbox pad) or fill (center crop).
- **🔊 Smart Audio Mix:** Mute original audio or low-mix (duck source to 15%), gracefully handles source videos without audio.
- **🧊 Duration Flexibility:** When source video is shorter than narration, choose between extending the final frame (freeze), looping, or shortening text.
- **🔒 Security & Resilience:** SSRF protection on public video downloads, bounded worker queue, atomic queue claims, process-tree termination on cancellation or timeout, and delivery retry without re-rendering.

---

## 💻 System Requirements

- **Operating System:** Windows, Linux, or macOS
- **Python:** `3.10` – `3.12+` (Tested on `3.12.10`)
- **FFmpeg & FFprobe:** Installed with `--enable-libass` and available in `PATH` (or specified in `.env`)
- **Khmer Font:** Bundled at `assets/fonts/KhmerOSbattambang.ttf`
- **Internet Connection:** Required for Telegram polling, Edge-TTS synthesis, and URL downloads

---

## 🚀 Installation & Quick Start

### 1. Clone & Setup Virtual Environment
```bash
git clone https://github.com/pisalreach1-glitch/Ai-video.git
cd Ai-video

# Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and set your Telegram bot token:
```bash
copy .env.example .env
```
Edit `.env`:
```ini
TELEGRAM_BOT_TOKEN=123456789:ABCdef...
RUNTIME_DIR=runtime
MAX_MEDIA_MB=50
MAX_VIDEO_SECONDS=300
MAX_NARRATION_CHARS=2000
MAX_CONCURRENT_JOBS=1
JOB_RETENTION_HOURS=24
```

### 3. Verify System Health (Preflight Check)
Run the automated preflight check script:
```bash
python scripts/check_environment.py
```

### 4. Start the Bot
- **Windows Batch Script:** Double-click or run:
  ```cmd
  start_bot.bat
  ```
- **Command Line:**
  ```bash
  python bot.py
  ```

To stop the bot on Windows:
```cmd
stop_bot.bat
```

---

## 🧪 Running Automated Tests

Run the full automated test suite (all 13 test suites):
```bash
python -m pytest -v
```

Test suites included:
- `tests/test_navigation.py`: Keyboard callbacks, session isolation, and resume flow.
- `tests/test_link_downloads.py`: SSRF prevention and streaming byte limits.
- `tests/test_tts.py`: Live Khmer voice discovery and timing event extraction.
- `tests/test_subtitles.py`: Phrase grouping, SRT formatting, and styled ASS cues.
- `tests/test_duration_policy.py`: Video trim, freeze final frame (`tpad`), and looping.
- `tests/test_audio_mix.py`: AI-only voice, low source ducking, and source without audio.
- `tests/test_output_formats.py`: 9:16 vertical, 1:1 square, and original ratios.
- `tests/test_preferences.py`: User preference defaults, restoration, and job snapshot isolation.
- `tests/test_revision_cache.py`: Revision cache invalidation rules and revision counters.
- `tests/test_approval.py`: Double-click prevention, atomic queue claims, outdated revision rejection.
- `tests/test_cancellation.py`: Process-tree termination (`kill_process_tree`) and cancellation state.
- `tests/test_delivery.py`: Upload success, delivery failure handling, and retry without re-rendering.
- `tests/test_smoke_render.py`: Full end-to-end render on synthetic media with subtitle burning.

---

## 📂 Project Architecture

```
Ai-video/
  bot.py                      # Clean application launcher
  requirements.txt            # Runtime dependencies
  requirements-dev.txt        # Development & test dependencies
  .env.example                # Configuration template
  .gitignore                  # Git ignore rules
  README.md                   # Documentation
  start_bot.bat               # Windows startup script
  stop_bot.bat                # Windows shutdown script

  app/
    main.py                   # Startup/shutdown, dispatcher, polling
    config.py                 # Configuration loader and validator

    handlers/
      start.py                # /start, /help, main menu, my settings
      navigation.py           # Back, home, resume flow
      uploads.py              # Telegram video/file receiving & caption prompt
      links.py                # Public video URL input, SSRF checks, download
      narration.py            # Khmer text validation & confirmation
      settings.py             # Voice, speed, subtitle, audio, format menus
      previews.py             # Audio preview, video preview, approval
      jobs.py                 # Cancel, retry delivery, download MP4/SRT
      history.py              # User video history with pagination

    ui/
      keyboards.py            # Inline keyboards
      texts_km.py             # Khmer language message templates
      options.py              # UI option constants and labels

    domain/
      models.py               # Job, Revision, VoiceSettings, MediaInfo
      states.py               # JobState and WizardStep FSM

    services/
      downloader.py           # Direct URL download + yt-dlp fallback
      voices.py               # Edge-TTS voice discovery and sample caching
      tts.py                  # Khmer TTS audio & timing event generator
      subtitles.py            # SRT and styled ASS subtitle generation
      media.py                # FFmpeg probing, aspect framing, duration filters
      previews.py             # 5-second realistic video preview renderer
      render.py               # Final MP4 render & decodability validation
      delivery.py             # Telegram upload & delivery failure recovery

    jobs/
      worker.py               # Concurrency-controlled render queue worker
      processes.py            # Async subprocess runner with process-tree cancellation

    storage/
      database.py             # SQLite WAL database & atomic transactions
      sessions.py             # Per user & chat session persistence
      preferences.py          # User default settings persistence
      jobs.py                 # Atomic job, revision, and queue storage
      workspaces.py           # Job directory & revision file layout
      cleanup.py              # Retention policy cleanup

  assets/
    fonts/                    # Redistributable Khmer fonts (KhmerOSbattambang.ttf)

  scripts/
    check_environment.py      # Preflight system verification script

  tests/                      # 13 automated test suites (all passing)
```
