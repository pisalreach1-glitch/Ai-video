"""Pre-flight environment and dependency checker for Telegram Voiceover Bot."""
import os
import sys
import shutil
import subprocess
from pathlib import Path
from dotenv import load_dotenv

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

def check() -> bool:
    print("================================================================")
    print("       Telegram Voiceover Bot - Environment Preflight Check     ")
    print("================================================================")
    all_ok = True

    # 1. Python version
    py_version = sys.version_info
    py_str = f"{py_version.major}.{py_version.minor}.{py_version.micro}"
    if py_version >= (3, 10):
        print(f" [OK] Python version: {py_str}")
    else:
        print(f" [FAIL] Python version: {py_str} (Python 3.10+ required)")
        all_ok = False

    # 2. Required Python libraries
    required_libs = [
        ("aiogram", "aiogram"),
        ("edge_tts", "edge-tts"),
        ("yt_dlp", "yt-dlp"),
        ("psutil", "psutil"),
        ("aiohttp", "aiohttp"),
        ("dotenv", "python-dotenv"),
    ]
    for mod_name, pkg_name in required_libs:
        try:
            __import__(mod_name)
            print(f" [OK] Python package: {pkg_name}")
        except ImportError:
            print(f" [FAIL] Python package missing: {pkg_name} (run: pip install -r requirements.txt)")
            all_ok = False

    # 3. FFmpeg binary
    explicit_ffmpeg = os.getenv("FFMPEG_PATH", "").strip()
    ffmpeg_bin = explicit_ffmpeg if (explicit_ffmpeg and os.path.exists(explicit_ffmpeg)) else shutil.which("ffmpeg")
    if ffmpeg_bin:
        print(f" [OK] FFmpeg found: {ffmpeg_bin}")
        # Check libass support
        try:
            res = subprocess.run([ffmpeg_bin, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if "--enable-libass" in res.stdout:
                print(" [OK] FFmpeg has libass subtitle support enabled")
            else:
                print(" [WARNING] FFmpeg might lack libass. Subtitles may require fallback.")
        except Exception:
            pass
    else:
        print(" [FAIL] FFmpeg not found in PATH or FFMPEG_PATH.")
        all_ok = False

    # 4. FFprobe binary
    explicit_ffprobe = os.getenv("FFPROBE_PATH", "").strip()
    ffprobe_bin = explicit_ffprobe if (explicit_ffprobe and os.path.exists(explicit_ffprobe)) else shutil.which("ffprobe")
    if ffprobe_bin:
        print(f" [OK] FFprobe found: {ffprobe_bin}")
    else:
        print(" [FAIL] FFprobe not found in PATH or FFPROBE_PATH.")
        all_ok = False

    # 5. Khmer Font
    font_path_env = os.getenv("KHMER_FONT_PATH", "assets/fonts/KhmerOSbattambang.ttf")
    font_path = Path(font_path_env).resolve()
    if font_path.exists():
        print(f" [OK] Khmer Font found: {font_path.name}")
    else:
        print(f" [WARNING] Khmer font not found at {font_path}. Using fallback system fonts.")

    # 6. Telegram Bot Token
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    if token and not token.startswith("YOUR_") and len(token) > 10:
        print(" [OK] TELEGRAM_BOT_TOKEN is set")
    else:
        print(" [WARNING] TELEGRAM_BOT_TOKEN is missing or default in .env.")
        print("           (The bot will require a valid token before polling updates)")

    # 7. Runtime directory
    runtime_dir = Path(os.getenv("RUNTIME_DIR", "runtime")).resolve()
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        print(f" [OK] Runtime directory writable: {runtime_dir}")
    except Exception as e:
        print(f" [FAIL] Cannot write to runtime dir: {e}")
        all_ok = False

    print("================================================================")
    if all_ok:
        print(" All critical system checks PASSED! Ready to start.")
        print("================================================================")
        return True
    else:
        print(" Preflight check detected issues. Please fix errors above.")
        print("================================================================")
        return False

if __name__ == "__main__":
    success = check()
    sys.exit(0 if success else 1)
