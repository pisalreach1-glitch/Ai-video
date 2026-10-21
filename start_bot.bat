@echo off
chcp 65001 >nul
title Telegram Video Bot (Drive D)
echo ================================================================
echo   Telegram Video Auto-Caption Bot (Drive D)
echo   Directory: D:\bot video
echo   Bot Status: ONLINE - Ready for Videos...
echo ================================================================
cd /d "D:\bot video"
"C:\Users\USER\AppData\Local\Programs\Python\Python312\python.exe" bot.py
echo.
echo [!] Bot Stopped or Crashed.
pause
