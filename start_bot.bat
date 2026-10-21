@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Telegram Voiceover Bot
echo ================================================================
echo   Telegram Voiceover Bot
echo   Directory: %~dp0
echo ================================================================
cd /d "%~dp0"

REM Find Python executable
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=python"
    ) else (
        echo [ERROR] Python was not found in .venv, venv, or system PATH.
        echo Please install Python 3.10+ and add it to PATH.
        pause
        exit /b 1
    )
)

REM Check environment
if not exist ".env" (
    echo [WARNING] .env file not found! Copying .env.example to .env...
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [!] Created .env from .env.example. Please set TELEGRAM_BOT_TOKEN in .env.
    ) else (
        echo [ERROR] Neither .env nor .env.example exists!
        pause
        exit /b 1
    )
)

REM Run environment preflight check
"%PYTHON_EXE%" scripts/check_environment.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Environment check failed. Please resolve the missing dependencies above.
    pause
    exit /b 1
)

echo.
echo [*] Starting Telegram Voiceover Bot...
"%PYTHON_EXE%" bot.py
echo.
echo [!] Bot Stopped or Exited.
pause
