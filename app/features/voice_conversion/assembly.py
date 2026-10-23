"""Lossless assembly of converted speech chunks into master audio."""
import hashlib
from pathlib import Path
from typing import List, Tuple, Callable
from app.config import config
from app.jobs.processes import run_process
from app.features.voice_conversion.media import validate_audio_file

async def assemble_converted_audio(
    chunk_paths: List[Path],
    output_master_wav: Path,
    target_sr: int = 24000,
    on_pid: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Tuple[Path, float, str]:
    """
    Concatenate converted audio chunks without lost speech or clipping.
    Returns: (output_master_wav, duration_seconds, sha256_checksum)
    """
    output_master_wav.parent.mkdir(parents=True, exist_ok=True)
    if not chunk_paths:
        raise ValueError("Cannot assemble audio from empty chunk list.")

    if len(chunk_paths) == 1:
        cmd = [
            config.ffmpeg_path,
            "-y",
            "-i", str(chunk_paths[0]),
            "-acodec", "pcm_s16le",
            "-ar", str(target_sr),
            "-ac", "1",
            str(output_master_wav),
        ]
        res = await run_process(cmd, timeout=60.0, on_pid=on_pid, cancel_check=cancel_check)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to encode single master chunk: {res.stderr[:200]}")
    else:
        concat_txt = output_master_wav.parent / "concat_list.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in chunk_paths:
                clean_p = str(p.resolve()).replace("\\", "/")
                f.write(f"file '{clean_p}'\n")

        cmd = [
            config.ffmpeg_path,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_txt),
            "-acodec", "pcm_s16le",
            "-ar", str(target_sr),
            "-ac", "1",
            str(output_master_wav),
        ]
        res = await run_process(cmd, timeout=120.0, on_pid=on_pid, cancel_check=cancel_check)
        if res.returncode != 0 or not output_master_wav.exists():
            raise RuntimeError(f"Failed to concat converted chunks: {res.stderr[:200]}")

    dur, _, _ = await validate_audio_file(output_master_wav, min_duration=0.5, max_duration=600.0)

    hasher = hashlib.sha256()
    with open(output_master_wav, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    sha256 = hasher.hexdigest()

    return output_master_wav, dur, sha256
