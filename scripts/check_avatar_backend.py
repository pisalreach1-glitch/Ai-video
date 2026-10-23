"""Health check for Talking Photo avatar backends (SadTalker & Wan2GP / HunyuanVideo-Avatar)."""
import os
import sys
import json
import subprocess
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def check_sadtalker() -> dict:
    python_exe = os.getenv("SADTALKER_PYTHON")
    engine_dir = os.getenv("SADTALKER_DIR")
    ckpts = os.getenv("SADTALKER_CHECKPOINT_DIR")

    info = {
        "name": "SadTalker",
        "configured": False,
        "cuda": False,
        "status": "unconfigured",
        "detail": "",
    }
    if not python_exe or not Path(python_exe).exists():
        info["detail"] = f"Python executable missing: {python_exe}"
        return info
    if not engine_dir or not Path(engine_dir).exists():
        info["detail"] = f"Engine directory missing: {engine_dir}"
        return info

    try:
        proc = subprocess.run(
            [python_exe, "-c", "import torch; print(torch.cuda.is_available())"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if proc.returncode == 0 and "True" in proc.stdout:
            info["configured"] = True
            info["cuda"] = True
            info["status"] = "ready"
        else:
            info["detail"] = f"CUDA check in SadTalker venv returned: {proc.stdout.strip()} (err: {proc.stderr[:100]})"
    except Exception as e:
        info["detail"] = f"Failed to probe SadTalker: {e}"

    return info

def check_wan2gp() -> dict:
    python_exe = os.getenv("AVATAR_PYTHON")
    engine_dir = os.getenv("AVATAR_ENGINE_DIR")
    model_dir = os.getenv("AVATAR_MODEL_DIR")

    info = {
        "name": "Wan2GP / HunyuanVideo-Avatar",
        "configured": False,
        "cuda": False,
        "status": "unconfigured",
        "detail": "",
    }
    if not python_exe or not Path(python_exe).exists():
        info["detail"] = f"AVATAR_PYTHON is not set or missing: {python_exe}"
        return info
    if not engine_dir or not Path(engine_dir).exists():
        info["detail"] = f"AVATAR_ENGINE_DIR is not set or missing: {engine_dir}"
        return info

    info["configured"] = True
    info["status"] = "configured_experimental"
    return info

def main():
    print("=== AVATAR BACKENDS HEALTH & CAPABILITY REPORT ===")
    st = check_sadtalker()
    print(f"[{st['name']}] Status: {st['status']} | Configured: {st['configured']} | CUDA: {st['cuda']}")
    if st["detail"]:
        print(f"  Detail: {st['detail']}")

    w2 = check_wan2gp()
    print(f"[{w2['name']}] Status: {w2['status']} | Configured: {w2['configured']}")
    if w2["detail"]:
        print(f"  Detail: {w2['detail']}")

if __name__ == "__main__":
    main()
