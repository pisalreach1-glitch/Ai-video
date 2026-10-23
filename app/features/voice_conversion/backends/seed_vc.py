"""Seed-VC adapter conforming to VoiceConversionBackend protocol."""
import os
import sys
import json
import logging
from pathlib import Path
from typing import Callable
from app.features.voice_conversion.domain import ConversionRequest, ConvertedAudio
from app.jobs.processes import run_process

logger = logging.getLogger(__name__)

class SeedVCBackend:
    @property
    def backend_id(self) -> str:
        return "seed_vc"

    async def is_available(self) -> bool:
        return True

    async def convert(
        self,
        request: ConversionRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
        on_pid: Callable[[int], None] | None = None,
    ) -> ConvertedAudio:
        out_dir = Path(request.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        req_json = out_dir / "vc_req.json"
        res_json = out_dir / "vc_res.json"
        output_wav = out_dir / "converted_master.wav"

        # Explicit mapping:
        # --source = full_source_wav (content / delivery)
        # --target = target_reference_wav (timbre)
        payload = {
            "full_source_wav": str(request.full_source_wav),
            "target_reference_wav": str(request.target_reference_wav),
            "output_wav": str(output_wav),
            "preserve_source_delivery": request.preserve_source_delivery,
            "input_digest": request.input_digest,
        }
        with open(req_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        py_env = os.getenv("SEED_VC_PYTHON")
        python_exe = py_env if (py_env and Path(py_env).is_file()) else sys.executable
        runner_script = Path(__file__).resolve().parent.parent.parent.parent.parent / "engines" / "seed_vc_bridge" / "runner.py"

        cmd = [
            python_exe,
            str(runner_script),
            "--request", str(req_json),
            "--result", str(res_json),
        ]

        proc = await run_process(cmd, timeout=300.0, on_pid=on_pid, cancel_check=cancel_check)
        if cancel_check and cancel_check():
            raise RuntimeError("Voice conversion cancelled.")

        if proc.returncode != 0 or not res_json.exists():
            raise RuntimeError(f"Seed-VC conversion failed: {proc.stderr[:200]}")

        with open(res_json, "r", encoding="utf-8") as f:
            res_data = json.load(f)

        if res_data.get("status") != "success":
            raise RuntimeError(f"Seed-VC conversion returned error: {res_data.get('error')}")

        return ConvertedAudio(
            artifact_id=request.artifact_id,
            master_wav=Path(res_data["wav_path"]),
            sha256=res_data["sha256"],
            sample_rate=int(res_data.get("sample_rate", 24000)),
            sample_count=int(res_data.get("sample_count", 0)),
            duration_seconds=float(res_data.get("duration_seconds", 0.0)),
            manifest_path=res_json,
        )

seed_vc_backend = SeedVCBackend()
