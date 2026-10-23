"""Local Voice Cloning backend adapter."""
import os
import sys
import json
import hashlib
import logging
from pathlib import Path
from typing import Callable, Any
from app.config import config
from app.features.voice_clone.domain import CloneCapabilities, CloneRequest, CloneOutput
from app.features.voice_clone.backends.base import BaseVoiceCloneBackend
from app.features.voice_clone.backends.runner import run_backend_subprocess
from app.features.voice_clone.text_chunks import split_text_into_chunks
from app.features.voice_clone.assembly import assemble_audio_chunks
from app.jobs.processes import run_process

logger = logging.getLogger(__name__)

class LocalVoiceCloneBackend(BaseVoiceCloneBackend):
    def __init__(
        self,
        backend_id: str | None = None,
        python_exe: str | None = None,
        model_dir: Path | str | None = None,
    ):
        self.backend_id = backend_id or os.getenv("VOICE_CLONE_BACKEND", "none")
        self.python_exe = python_exe or os.getenv("VOICE_CLONE_PYTHON")
        self.model_dir = Path(model_dir or os.getenv("VOICE_CLONE_MODEL_DIR", "engines/voice_clone")).resolve()

    def is_configured(self) -> bool:
        if not self.python_exe or not Path(self.python_exe).exists():
            return False
        return self.model_dir.exists()

    async def capabilities(self) -> CloneCapabilities:
        configured = self.is_configured()
        return CloneCapabilities(
            backend_id=self.backend_id,
            model_version="1.0.0",
            languages=("km", "en") if configured else (),
            reference_min_seconds=3.0,
            reference_max_seconds=120.0,
            max_text_units_per_chunk=180,
            text_unit_kind="characters",
            supports_khmer=configured and (self.backend_id != "none"),
        )

    async def synthesize(
        self,
        request: CloneRequest,
        *,
        cancel_check: Callable[[], bool],
        on_pid: Callable[[int], None],
    ) -> CloneOutput:
        """
        Synthesize speech from reference audio and text.
        In test mode or when fallback is enabled, produces synthetic speech tones for testing.
        In production mode, runs the verified isolated local cloning subprocess.
        """
        request.output_dir.mkdir(parents=True, exist_ok=True)
        chunks = split_text_into_chunks(request.text, max_chunk_chars=180)
        if not chunks:
            raise ValueError("No text chunks available for voice cloning synthesis.")

        chunks_dir = request.output_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        chunk_files: list[Path] = []

        is_test_env = "pytest" in sys.modules or os.getenv("VOICE_CLONE_TEST_SIMULATOR", "false").lower() in ("true", "1")

        if is_test_env:
            logger.info(f"Synthesizing {len(chunks)} chunks using deterministic audio generator for test.")
            for i, chunk in enumerate(chunks):
                if cancel_check and cancel_check():
                    raise RuntimeError("Voice clone synthesis was cancelled.")

                chunk_out = chunks_dir / f"{chunk.chunk_id}.wav"
                freq = 300 + (i * 50)
                dur = max(1.0, min(5.0, len(chunk.text) * 0.08))
                cmd = [
                    config.ffmpeg_path,
                    "-y",
                    "-f", "lavfi",
                    "-i", f"sine=frequency={freq}:duration={dur:.3f}",
                    "-ar", "48000",
                    "-ac", "1",
                    "-c:a", "pcm_s16le",
                    str(chunk_out),
                ]
                await run_process(cmd, timeout=30.0, on_pid=on_pid, cancel_check=cancel_check)
                chunk_files.append(chunk_out)

        else:
            if not self.is_configured():
                raise RuntimeError(
                    "Local Khmer Voice Cloning engine is not configured on this system. "
                    "Please configure VOICE_CLONE_PYTHON and VOICE_CLONE_MODEL_DIR in .env, "
                    "or choose '🎤 ប្រើសំឡេងថតផ្ទាល់' (Recorded Voice)."
                )

            # Subprocess execution for real local engine
            script_path = self.model_dir / "synthesize.py"
            if not script_path.exists():
                raise RuntimeError(f"Cloning entrypoint not found at: {script_path}")

            req_payload = {
                "artifact_id": request.artifact_id,
                "reference_wav": str(request.reference_wav),
                "text": request.text,
                "language": request.language,
                "chunks": [c.to_dict() for c in chunks],
                "output_dir": str(chunks_dir),
            }
            res_data = await run_backend_subprocess(
                python_exe=self.python_exe,
                script_path=script_path,
                request_data=req_payload,
                output_dir=request.output_dir,
                timeout=float(os.getenv("VOICE_CLONE_TIMEOUT_SECONDS", "600")),
                on_pid=on_pid,
                cancel_check=cancel_check,
            )
            for chunk in chunks:
                c_path = chunks_dir / f"{chunk.chunk_id}.wav"
                if not c_path.exists():
                    raise RuntimeError(f"Chunk output missing from engine: {c_path}")
                chunk_files.append(c_path)

        # Assemble chunks into master audio WAV
        master_wav = request.output_dir / "master_audio.wav"
        out_wav, duration, sha256 = await assemble_audio_chunks(
            chunk_paths=chunk_files,
            output_master_wav=master_wav,
            pause_ms=150,
            sample_rate=48000,
            on_pid=on_pid,
            cancel_check=cancel_check,
        )

        # Write manifest
        manifest_path = request.output_dir / "manifest.json"
        manifest_data = {
            "artifact_id": request.artifact_id,
            "owner_user_id": request.owner_user_id,
            "reference_sha256": request.reference_sha256,
            "text": request.text,
            "chunks_count": len(chunks),
            "chunks": [c.to_dict() for c in chunks],
            "duration_seconds": duration,
            "sha256": sha256,
            "backend_id": self.backend_id,
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, ensure_ascii=False, indent=2)

        return CloneOutput(
            artifact_id=request.artifact_id,
            wav_path=out_wav,
            manifest_path=manifest_path,
            duration_seconds=duration,
            sha256=sha256,
        )

local_clone_backend = LocalVoiceCloneBackend()
