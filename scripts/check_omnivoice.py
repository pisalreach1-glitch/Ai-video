"""Health check and capability verification for OmniVoice local voice cloning."""
import os
import sys
import json
import subprocess
from pathlib import Path

# Configure UTF-8 for Windows console
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def check_omnivoice() -> dict:
    result = {
        "configured": False,
        "python_path": os.getenv("OMNIVOICE_PYTHON", ""),
        "model_dir": os.getenv("OMNIVOICE_MODEL_DIR", ""),
        "supports_khmer": True, # OmniVoice natively includes 'km' / 'khm'
        "cuda_available": False,
        "status": "unconfigured",
        "reason": "",
    }

    python_exe = os.getenv("OMNIVOICE_PYTHON")
    model_dir = os.getenv("OMNIVOICE_MODEL_DIR")

    if not python_exe or not Path(python_exe).exists():
        result["reason"] = f"OMNIVOICE_PYTHON is not configured or not found: {python_exe}"
        return result

    if not model_dir or not Path(model_dir).exists():
        result["reason"] = f"OMNIVOICE_MODEL_DIR is not configured or directory does not exist: {model_dir}"
        return result

    # Check python environment for omnivoice and torch
    probe_code = (
        "import torch; import omnivoice; "
        "print(json.dumps({'torch': torch.__version__, 'cuda': torch.cuda.is_available(), 'omnivoice': True}))"
    )
    try:
        proc = subprocess.run(
            [python_exe, "-c", f"import json; {probe_code}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout.strip().splitlines()[-1])
            result["cuda_available"] = data.get("cuda", False)
            result["configured"] = True
            result["status"] = "ready"
        else:
            result["reason"] = f"OmniVoice python environment probe failed: {proc.stderr[:200]}"
    except Exception as e:
        result["reason"] = f"Execution error probing OmniVoice: {e}"

    return result

if __name__ == "__main__":
    status = check_omnivoice()
    print("=== OMNIVOICE HEALTH & CAPABILITY REPORT ===")
    print(f"Status: {status['status']}")
    print(f"Configured: {status['configured']}")
    print(f"Supports Khmer ('km'): {status['supports_khmer']} (Documented in k2-fsa/OmniVoice languages.md)")
    print(f"CUDA Available: {status['cuda_available']}")
    print(f"Python Executable: {status['python_path']}")
    print(f"Model Directory: {status['model_dir']}")
    if status['reason']:
        print(f"Detail: {status['reason']}")
