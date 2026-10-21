# 🎬 Telegram Bot: AI Video Auto-Cut & Creative Remotion Subtitles

An automated video editing Telegram bot powered by **Remotion (React)**, **Google Gemini AI**, and **Faster-Whisper**. It creates short-form vertical viral videos with word-by-word subtitles, kinetic animations, audio ducking, automated SFX, smart silence cuts, and visual story overlays.

---

## 💻 System Requirements & Supported Versions

| Dependency | Supported Version | Notes |
|---|---|---|
| **Python** | `3.10` – `3.12+` (Tested on `3.12.10`) | Backend orchestrator, Telegram handlers, Whisper |
| **Node.js** | `v18.0.0` – `v20.x+` (Tested on `v20.18.0`) | Remotion engine runtime |
| **npm** | `9.x` – `10.x+` | Package manager |
| **FFmpeg** | `4.4+` – `7.x+` (or bundled `imageio-ffmpeg`) | Audio/Video processing & probe |

---

## 🚀 Installation & Setup

### 1. Clone & Set Up Python Environment
```bash
git clone https://github.com/pisalreach1-glitch/Ai-video.git
cd Ai-video

# Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Set Up Remotion (Node.js)
```bash
cd remotion
npm install
cd ..
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your keys:
```bash
copy .env.example .env
```

Key environment options:
```ini
# Required
TELEGRAM_BOT_TOKEN=123456789:ABCdef...

# Optional MTProto (Required for videos > 20MB/50MB up to 2GB)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash

# Optional Google Gemini (Cloud transcription & Mode 2 director)
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash

# Local Whisper Model (Offline / fallback mode)
WHISPER_MODEL=base

# Subprocess & Job Controls
FFMPEG_TIMEOUT=180.0
REMOTION_RENDER_TIMEOUT=600.0
JOB_RETENTION_HOURS=24.0
MAX_CONCURRENT_JOBS=2
MAX_USER_CONCURRENT_JOBS=1
```

---

## 🎨 Asset Generation Commands

The repository includes standalone scripts to generate background music, sound effects, and font catalogs:

- **Generate SFX Catalog:**
  ```bash
  python generate_sfx.py
  ```
- **Generate Background Audio / BGM Library:**
  ```bash
  python generate_bgm.py
  ```
- **Generate AI Story Visuals / B-Roll:**
  ```bash
  python image_story_generator.py
  ```

---

## 🎙️ Local Whisper Mode vs. Optional Gemini Mode

| Feature | Local Whisper Mode | Google Gemini Cloud Mode |
|---|---|---|
| **API Key Required** | ❌ No API key needed | ✅ Requires `GEMINI_API_KEY` |
| **Cost** | 100% Free / Local | Google Gemini Free / Pay-as-you-go |
| **Languages** | Multilingual (Khmer, English, etc.) | High-accuracy Khmer & Multilingual |
| **Failover / Fallback** | Default offline baseline | Automatically falls back to Whisper on quota/network issues |
| **Internet Dependency** | Works offline once weights are loaded | Requires internet access |

---

## 📦 Telegram Bot API vs. Optional MTProto Requirements

- **Telegram Bot API (Default):**
  - Download limit: `20 MB`
  - Upload limit: `50 MB`
  - Suitable for short low-bitrate clips.
- **Pyrogram MTProto (High-Performance 2GB Mode):**
  - Download & Upload limit: up to `2,000 MB (2 GB)`
  - Requires `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from [my.telegram.org](https://my.telegram.org).
  - Recommended for full HD / 4K smartphone videos.

---

## ⚙️ Operational Behavior: Startup, Shutdown, Cancellation & Cleanup

### 1. Startup & Running
Run the bot via script or terminal:
```bash
# Windows
start_bot.bat

# Or terminal
python bot.py
```
On startup:
- Tests FFmpeg executable path.
- Connects Telegram Bot application and optional Pyrogram MTProto client.
- Starts the non-blocking background cleanup task.

### 2. User Experience & Commands
- `/start` — Welcome guide, workflow overview, and instructions.
- `/status` — Displays current job ID, active progress, queue position, system concurrency, and retention policy.
- `/cancel` — Immediately terminates running FFmpeg / Node process trees and cancels queued jobs.
- `/new` — Resets the user's active session, allowing fresh video submissions.
- `/help` — Detailed instructions on subtitle editing and syntax.

### 3. Process Cancellation
- Merely cancelling an asyncio Future is **not** sufficient: the bot registers the active OS process ID (PID) of running FFmpeg / Node / Chromium processes and recursively terminates the entire process tree using `psutil`.

### 4. Retention & Cleanup Policy
- Configurable via `JOB_RETENTION_HOURS` (default: 24 hours).
- **Never deletes active or queued jobs:** Running and queued job directories are strictly protected.
- Expired job folders, generated props, and previews older than the retention threshold are swept periodically every 30 minutes.
- Path traversal guards prevent deletion outside designated temp/cache roots.

### 5. Graceful Shutdown & Restart Recovery
To stop the bot cleanly:
```bash
# Windows
stop_bot.bat
```
Gracefully shuts down the background worker pool, MTProto session, and Telegram polling.

#### Restart Recovery:
- On startup, `db.recover_interrupted_jobs()` automatically identifies any in-progress jobs that were interrupted by a system shutdown or reboot, and sets their status to `interrupted`.
- Unfinished jobs are **never** labeled completed.

---

## 🧙‍♂️ 5-Step Video Wizard & Navigation

The bot separates interactive wizard state from background rendering job state:

1. **Step 1 (`mode`):** Choose between Auto, Quick Viral Pop, Motion Explainer, or Custom AI Agent.
2. **Step 2 (`upload`):** Upload video up to 2GB via MTProto or Telegram Bot API.
3. **Step 3 (`style`):** Select visual theme (TikTok Viral, Bold Gold, Clean White), custom font, and BGM track.
4. **Step 4 (`length`):** Set target pacing: Auto (smart silence cut), Short (<30s), Medium (<60s), or Full.
5. **Step 5 (`review`):** Comprehensive summary with optional custom instructions, and `[ 🚀 Confirm & Start Render ]`.

### Non-Destructive Navigation:
- **`[ ⬅️ Back ]`:** Moves back a step without losing uploaded media or chosen styles.
- **`[ 🏠 Main Menu ]`:** Returns to main menu without silently cancelling active background jobs.
- **`[ ⏯️ Resume ]`:** If an active or approval-pending job exists, `/start` and the main menu provide a one-click Resume button.

---

## 🛡️ Sandbox Security & Execution Isolation

- **Secret Scrubbing:** Sensitive environment variables (`TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `TELEGRAM_API_HASH`, etc.) are explicitly scrubbed from the subprocess environment before passing to Remotion CLI.
- **Composition Whitelist:** Only approved compositions (`ShortComposition`, `PreviewComposition`) can be executed.
- **Props Validation:** Guard against path traversal in `videoSrc` or overlay image paths.
- **Zero Arbitrary Installs:** The rendering runtime does not automatically install unverified npm packages.
- **Bounded Retries:** If Remotion rendering experiences an unexpected transient failure, it retries a bounded maximum of 2 times before failing cleanly.

---

## 🤖 Antigravity Agent Bridge & Assisted Fallback

- The bot checks `ANTIGRAVITY_BRIDGE_ENABLED` (defaults to `false` without external cloud sidecars).
- When custom agent features are requested without a live automated sidecar bridge, the bot honestly degrades to assisted mode:
  - Generates structured pair-programming briefs (`agent_brief.md` and `agent_brief.json`).
  - Sets job state to `awaiting_manual_agent`.
  - Allows immediate one-click fallback to standard template rendering.

---

## ⚠️ Actual Limitations & Expectations

1. **AI-Generated Subtitles:**
   Speech-to-text is performed by AI and can make mistakes on background noise, fast colloquial slang, or indistinct accents. Users are strongly advised to review and edit subtitle lines before initiating rendering.
2. **Estimated Render Time:**
   Rendering time depends on hardware capability (CPU cores, GPU NVENC support) and input video duration/resolution. Typical renders take from under a minute up to several minutes for longer 4K videos.
3. **Queue Limits & Concurrency:**
   To preserve local PC stability, default configuration enforces `MAX_RENDER_CONCURRENCY=1`, `1` active job per user, and a bounded queue size of `20` jobs in SQLite.

---

## 📦 Delivery Resilience & Audit Verification (42 Tests)

1. **Delivery Failure Guarantee:**
   - If Telegram `send_video` fails (e.g. timeout, 50MB Bot API limit, connection reset), the job status is set to `delivery_failed` and is **never** falsely marked `completed`.
   - The rendered MP4 output path is safely preserved on the local filesystem.
   - An interactive `[ 🔄 ព្យាយាមផ្ញើវីដេអូម្តងទៀត (Retry Delivery) ]` button allows resending without rerendering.
2. **Real Preview Snippet (`Upload → Preview → Approve → MP4`):**
   - Before full render, a 5-second burned subtitle preview video clip is generated and delivered to the user.
   - The user reviews the actual video and font style before clicking `[ 🚀 យល់ព្រម Render វីដេអូពេញលេញ (Approve) ]`.
3. **Atomic Job Claiming:**
   - Jobs are claimed from SQLite using atomic transactions with revision guards, preventing race conditions under concurrency.
4. **Duration & Custom Prompt Slicing:**
   - Target pacing (`short_30s`, `medium_60s`, `full`) slices speech transcript accurately.
   - Custom prompts guide visual story scene extraction.
5. **Automated Verification:**
   - 42 comprehensive unit, integration, and smoke tests pass cleanly with mocked external APIs.
