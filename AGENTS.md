# Project Rules & Guidelines for AI Agents

## Mandatory GitHub Push Rule
- **Every change must be pushed to GitHub**: Whenever any code, documentation, test, or configuration is added or modified in this repository, it **MUST** immediately be committed and pushed to GitHub on the active branch (`origin feature/simple-voiceover-bot`).
- **Purpose**: The user regularly sends each commit to ChatGPT for code review and validation before merging. Leaving uncommitted or unpushed work locally prevents this workflow.
- **Pre-Push Validation**: Always run the test suite (`python -m pytest`) to ensure all tests pass before pushing.
- **Reporting**: Always provide the commit SHA, commit message summary, and the GitHub commit link in the response so the user can directly forward it to ChatGPT.

## Quality & Architecture Constraints
- **Telegram Callbacks**: Keep callback data length strictly $\le 64$ bytes per Telegram Bot API specification.
- **Audio & Video Processing**: Video narration, subtitles, and audio mixing must preserve full duration and synchronization.
- **Security & Privacy**: Never commit `.env` or print secret tokens/keys (`TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`).

## Bot Auto-Start & Background Execution
- **PC Startup Auto-Run**: The bot must always be configured to launch automatically in the background (hidden/silent, no blocking console window) on PC boot / Windows logon.
- **Background Launcher**: Use `start_bot_background.vbs` targeting `pythonw bot.py` placed or linked in the Windows Startup directory (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`).
- **Logging**: Running under background `pythonw` writes all logs to `runtime/bot.log`.

