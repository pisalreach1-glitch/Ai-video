@echo off
chcp 65001 >nul
echo Closing Telegram Video Bot...
taskkill /F /FI "WINDOWTITLE eq Telegram Video Bot*" /T
echo Done!
pause
