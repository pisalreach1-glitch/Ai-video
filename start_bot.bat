@echo off
chcp 65001 >nul
title Telegram Video Bot (Drive D)
echo ================================================================
echo   Telegram Video Auto-Caption Bot (Drive D)
echo   Directory: %~dp0
echo   Bot Status: ONLINE - Ready for Videos...
echo ================================================================
cd /d "%~dp0"
"C:\Users\USER\AppData\Local\Programs\Python\Python312\python.exe" bot.py
echo.
echo [!] Bot Stopped or Crashed.
pause
