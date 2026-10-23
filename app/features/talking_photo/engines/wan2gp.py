"""Wan2GP / HunyuanVideo-Avatar backend adapter (Experimental)."""
import os
import sys
import json
import logging
from pathlib import Path
from typing import Callable

from app.features.talking_photo.domain import AvatarRequest, AvatarResult
from app.jobs.processes import run_process

logger = logging.getLogger(__name__)

class Wan2GPAvatarBackend:
    @property
    def backend_id(self) -> str:
        return "wan2gp_hunyuan"

    async def is_available(self) -> bool:
        python_exe = os.getenv("AVATAR_PYTHON")
        engine_dir = os.getenv("AVATAR_ENGINE_DIR")
        if not python_exe or not Path(python_exe).exists():
            return False
        if not engine_dir or not Path(engine_dir).exists():
            return False
        return True

    async def render(
        self,
        request: AvatarRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
        on_pid: Callable[[int], None] | None = None,
    ) -> AvatarResult:
        if not await self.is_available():
            raise RuntimeError(
                "Wan2GP / HunyuanVideo-Avatar backend is not configured or missing weights. "
                "Please use the verified SadTalker backend or configure AVATAR_ENGINE_DIR in .env."
            )

        python_exe = os.getenv("AVATAR_PYTHON", sys.executable)
        runner_script = Path(__file__).resolve().parent.parent.parent.parent.parent / "engines" / "avatar_bridge" / "runner.py"

        out_dir = Path(request.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        req_json = out_dir / "wan2gp_req.json"
        res_json = out_dir / "wan2gp_res.json"

        payload = {
            "source_image": str(request.source_image),
            "approved_master_wav": str(request.approved_master_wav),
            "output_dir": str(out_dir),
            "preview_seconds": request.preview_seconds,
            "motion_prompt": request.motion_prompt or "natural speaking portrait, stable identity, subtle movement",
        }
        with open(req_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        cmd = [
            python_exe,
            str(runner_script),
            "--request", str(req_json),
            "--result", str(res_json),
        ]

        proc = await run_process(cmd, timeout=300.0, on_pid=on_pid, cancel_check=cancel_check)
        if cancel_check and cancel_check():
            raise RuntimeError("Wan2GP avatar render cancelled.")

        if proc.returncode != 0 or not res_json.exists():
            raise RuntimeError(f"Wan2GP avatar runner failed: {proc.stderr[:300]}")

        with open(res_json, "r", encoding="utf-8") as f:
            res_data = json.load(f)

        if res_data.get("status") != "success":
            raise RuntimeError(f"Wan2GP rendering failed: {res_data.get('error')}")

        return AvatarResult(
            video_path=res_data["video_path"],
            manifest_path=str(res_json),
            duration_seconds=float(res_data.get("duration_seconds", 5.0)),
            backend_revision="wan2gp-0.1-experimental",
        )

wan2gp_avatar_backend = Wan2GPAvatarBackend()
