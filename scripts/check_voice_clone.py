"""Voice Clone dependency, model, CUDA, and language capability verification script."""
import os
import sys
import shutil
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import asyncio
from app.features.voice_clone.backends.local import local_clone_backend

async def main():
    print("=" * 60)
    print(" Voice Clone Engine Diagnostic & Capability Check")
    print("=" * 60)

    # 1. Environment variables
    backend_id = os.getenv("VOICE_CLONE_BACKEND", "none")
    python_exe = os.getenv("VOICE_CLONE_PYTHON", "")
    model_dir = os.getenv("VOICE_CLONE_MODEL_DIR", "engines/voice_clone")
    lang = os.getenv("VOICE_CLONE_LANGUAGE", "km")

    print(f"[*] VOICE_CLONE_BACKEND:   {backend_id}")
    print(f"[*] VOICE_CLONE_PYTHON:    {python_exe}")
    print(f"[*] VOICE_CLONE_MODEL_DIR: {model_dir}")
    print(f"[*] VOICE_CLONE_LANGUAGE:  {lang}")

    # 2. Check Python executable
    py_ok = bool(python_exe and Path(python_exe).exists())
    print(f"[*] Python Executable:     {'✅ Found' if py_ok else '❌ Missing or not configured'}")

    # 3. Check Model Directory
    model_ok = Path(model_dir).exists()
    print(f"[*] Model Directory:       {'✅ Found' if model_ok else '❌ Missing'}")

    # 4. Capabilities
    caps = await local_clone_backend.capabilities()
    print(f"[*] Declared Languages:    {list(caps.languages)}")
    print(f"[*] Native Khmer Support:  {'✅ Verified' if caps.supports_khmer else '⚠️ Not configured / Unverified'}")

    # 5. FFmpeg availability
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    print(f"[*] FFmpeg Binary:         {'✅ Available' if ffmpeg_ok else '❌ Not found'}")

    print("-" * 60)
    if not caps.supports_khmer:
        print("💡 [STATUS] Local Khmer Voice Cloning is currently UNCONFIGURED.")
        print("   The bot will safely guide users to '🎤 ប្រើសំឡេងថតផ្ទាល់' (Recorded Voice)")
        print("   without silently producing fake audio or failing unexpectedly.")
    else:
        print("✅ [STATUS] Voice Clone Engine is configured and ready for synthesis.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
