"""Avatar bridge runner for experimental Wan2GP / HunyuanVideo-Avatar backend.
Invoked via: python runner.py --request /absolute/request.json --result /absolute/result.json
"""
import sys
import os
import json
import argparse
import time
from pathlib import Path

def render_avatar(req: dict) -> dict:
    source_image = req.get("source_image")
    audio_path = req.get("approved_master_wav")
    output_dir = req.get("output_dir")
    preview_seconds = req.get("preview_seconds")
    motion_prompt = req.get("motion_prompt", "natural speaking portrait, stable identity, subtle movement")

    if not source_image or not audio_path or not output_dir:
        raise ValueError("Missing required arguments in request: source_image, approved_master_wav, output_dir.")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    attempt_dir = out_dir / f"attempt_{int(time.time() * 1000)}"
    attempt_dir.mkdir(parents=True, exist_ok=True)

    output_video = attempt_dir / "avatar_output.mp4"

    # Verify if Wan2GP engine is configured
    engine_dir = os.getenv("AVATAR_ENGINE_DIR")
    if not engine_dir or not Path(engine_dir).exists():
        raise RuntimeError(
            "Wan2GP / HunyuanVideo-Avatar engine is not installed or configured in AVATAR_ENGINE_DIR."
        )

    # In production, call Wan2GP Python entrypoint here
    # Placeholder for actual engine invocation:
    return {
        "status": "success",
        "video_path": str(output_video),
        "duration_seconds": preview_seconds or 5.0,
        "backend_revision": "wan2gp-0.1-experimental",
        "model_config": {
            "motion_prompt": motion_prompt,
            "engine_dir": str(engine_dir),
        }
    }

def main():
    parser = argparse.ArgumentParser(description="Avatar Bridge Runner")
    parser.add_argument("--request", required=True, help="Path to request JSON")
    parser.add_argument("--result", required=True, help="Path to result JSON")
    args = parser.parse_args()

    req_path = Path(args.request)
    res_path = Path(args.result)

    try:
        with open(req_path, "r", encoding="utf-8") as f:
            req_data = json.load(f)

        res_data = render_avatar(req_data)

        with open(res_path, "w", encoding="utf-8") as f:
            json.dump(res_data, f, indent=2)

    except Exception as exc:
        err_res = {
            "status": "failed",
            "error": str(exc),
        }
        with open(res_path, "w", encoding="utf-8") as f:
            json.dump(err_res, f, indent=2)
        sys.exit(1)

if __name__ == "__main__":
    main()
