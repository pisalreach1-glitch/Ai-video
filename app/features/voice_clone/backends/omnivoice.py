"""OmniVoice backend adapter for local Khmer voice cloning."""
import os
import sys
import json
import logging
from pathlib import Path
from typing import Callable

from app.features.voice_clone.domain import CloneCapabilities, CloneRequest, CloneOutput
from app.features.voice_clone.text_chunks import split_text_into_chunks, verify_chunk_coverage
from app.features.voice_clone.assembly import assemble_audio_chunks
from app.jobs.processes import run_process

logger = logging.getLogger(__name__)

class OmniVoiceBackend:
    def __init__(self):
        self.backend_id = "omnivoice"
        self.model_version = os.getenv("OMNIVOICE_MODEL_REVISION", "1.0.0")
        py_env = os.getenv("OMNIVOICE_PYTHON")
        self.python_exe = py_env if (py_env and Path(py_env).is_file()) else sys.executable
        self.runner_script = Path(__file__).resolve().parent.parent.parent.parent.parent / "engines" / "omnivoice_bridge" / "runner.py"

    async def capabilities(self) -> CloneCapabilities:
        model_dir = os.getenv("OMNIVOICE_MODEL_DIR")
        is_configured = bool(model_dir and Path(model_dir).exists())
        return CloneCapabilities(
            backend_id=self.backend_id,
            model_version=self.model_version,
            languages=("km", "en", "zh"),
            reference_min_seconds=3.0,
            reference_max_seconds=120.0,
            max_text_units_per_chunk=300,
            text_unit_kind="characters",
            supports_khmer=True,
        )

    async def synthesize(
        self,
        request: CloneRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
        on_pid: Callable[[int], None] | None = None,
    ) -> CloneOutput:
        output_dir = request.output_dir
        chunks_dir = output_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        # 1. Chunking text with stable IDs
        chunks = split_text_into_chunks(request.text, max_chunk_chars=250)
        verify_chunk_coverage(request.text, chunks)

        chunk_wav_paths = []
        for chunk in chunks:
            if cancel_check and cancel_check():
                raise RuntimeError("OmniVoice synthesis cancelled.")

            chunk_out_wav = chunks_dir / f"{chunk.chunk_id}.wav"
            req_json = chunks_dir / f"{chunk.chunk_id}_req.json"
            res_json = chunks_dir / f"{chunk.chunk_id}_res.json"

            payload = {
                "target_text": chunk.text,
                "reference_wav": str(request.reference_wav),
                "reference_text": request.reference_text,
                "output_wav": str(chunk_out_wav),
                "model_dir": os.getenv("OMNIVOICE_MODEL_DIR", ""),
            }
            with open(req_json, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            cmd = [
                self.python_exe,
                str(self.runner_script),
                "--request", str(req_json),
                "--result", str(res_json),
            ]

            proc = await run_process(cmd, timeout=120.0, on_pid=on_pid, cancel_check=cancel_check)
            if cancel_check and cancel_check():
                raise RuntimeError("OmniVoice synthesis cancelled.")

            if proc.returncode != 0 or not chunk_out_wav.exists():
                err = proc.stderr[:300] if proc.stderr else "Unknown error"
                raise RuntimeError(f"OmniVoice chunk {chunk.chunk_id} synthesis failed: {err}")

            chunk_wav_paths.append(chunk_out_wav)

        # 2. Assemble lossless PCM master audio
        master_wav_path = output_dir / "master_audio.wav"
        manifest_path = output_dir / "manifest.json"

        assembled_path, dur, sha256 = await assemble_audio_chunks(
            chunk_wav_paths,
            master_wav_path,
            pause_ms=250,
            sample_rate=24000,
            on_pid=on_pid,
            cancel_check=cancel_check,
        )

        manifest_data = {
            "artifact_id": request.artifact_id,
            "duration_seconds": dur,
            "sha256": sha256,
            "chunks_count": len(chunks),
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        return CloneOutput(
            artifact_id=request.artifact_id,
            wav_path=assembled_path,
            manifest_path=manifest_path,
            duration_seconds=dur,
            sha256=sha256,
        )

omnivoice_backend = OmniVoiceBackend()
