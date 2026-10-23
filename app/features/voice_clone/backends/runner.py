"""Subprocess execution runner for external Voice Cloning engines."""
import os
import json
import logging
from pathlib import Path
from typing import Callable, Any
from app.jobs.processes import run_process

logger = logging.getLogger(__name__)

async def run_backend_subprocess(
    python_exe: str,
    script_path: Path,
    request_data: dict[str, Any],
    output_dir: Path,
    timeout: float = 300.0,
    on_pid: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """
    Launch isolated engine subprocess passing request JSON and expecting result JSON.
    Never uses shell interpolation. Enforces process tree termination on cancel.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    req_file = output_dir / "clone_request.json"
    res_file = output_dir / "clone_result.json"

    with open(req_file, "w", encoding="utf-8") as f:
        json.dump(request_data, f, ensure_ascii=False, indent=2)

    cmd = [
        python_exe,
        str(script_path),
        "--request", str(req_file),
        "--output", str(res_file),
    ]

    logger.info(f"Launching voice clone engine subprocess: {python_exe} {script_path}")
    proc_res = await run_process(
        cmd,
        timeout=timeout,
        on_pid=on_pid,
        cancel_check=cancel_check,
        cwd=str(script_path.parent),
    )

    if cancel_check and cancel_check():
        raise RuntimeError("Voice clone synthesis was cancelled by user.")

    if proc_res.returncode != 0:
        err_msg = proc_res.stderr[-400:] if proc_res.stderr else f"Exit code {proc_res.returncode}"
        raise RuntimeError(f"Voice clone engine failed: {err_msg}")

    if not res_file.exists():
        raise RuntimeError("Voice clone engine finished with 0 but produced no clone_result.json")

    with open(res_file, "r", encoding="utf-8") as f:
        return json.load(f)
