@echo off
chcp 65001 >nul
echo Closing Telegram Voiceover Bot...
taskkill /F /FI "WINDOWTITLE eq Telegram Voiceover Bot*" /T 2>nul
echo Done!
pause
