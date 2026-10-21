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
