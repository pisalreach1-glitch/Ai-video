"""Audio assembly and PCM concatenation for multi-chunk voice synthesis."""
import hashlib
import logging
from pathlib import Path
from typing import Callable
from app.config import config
from app.jobs.processes import run_process
from app.features.talking_photo.media import measure_audio_duration

logger = logging.getLogger(__name__)

async def assemble_audio_chunks(
    chunk_paths: list[Path],
    output_master_wav: Path,
    pause_ms: int = 150,
    sample_rate: int = 48000,
    on_pid: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[Path, float, str]:
    """
    Concatenate synthesized audio chunks into a lossless master WAV track with explicit pauses.
    Returns: (output_master_wav, duration_seconds, sha256_checksum)
    """
    output_master_wav.parent.mkdir(parents=True, exist_ok=True)
    if not chunk_paths:
        raise ValueError("Cannot assemble audio from empty chunk list.")

    # Single chunk case: re-encode to master sample rate (48kHz mono)
    if len(chunk_paths) == 1:
        cmd = [
            config.ffmpeg_path,
            "-y",
            "-i", str(chunk_paths[0]),
            "-ar", str(sample_rate),
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(output_master_wav),
        ]
        res = await run_process(cmd, timeout=60.0, on_pid=on_pid, cancel_check=cancel_check)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg failed re-encoding single audio chunk: {res.stderr[:200]}")
    else:
        # Multi-chunk: generate pause silence and use concat filter
        pause_wav = output_master_wav.parent / "temp_pause.wav"
        pause_sec = pause_ms / 1000.0
        cmd_silence = [
            config.ffmpeg_path,
            "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={sample_rate}:cl=mono:d={pause_sec:.3f}",
            "-c:a", "pcm_s16le",
            str(pause_wav),
        ]
        await run_process(cmd_silence, timeout=30.0, cancel_check=cancel_check)

        # Build concat list
        concat_txt = output_master_wav.parent / "concat_list.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for i, c_path in enumerate(chunk_paths):
                # Normalize slashes for FFmpeg concat demuxer
                c_norm = str(c_path.resolve()).replace("\\", "/")
                f.write(f"file '{c_norm}'\n")
                if i < len(chunk_paths) - 1:
                    p_norm = str(pause_wav.resolve()).replace("\\", "/")
                    f.write(f"file '{p_norm}'\n")

        cmd = [
            config.ffmpeg_path,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_txt),
            "-ar", str(sample_rate),
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(output_master_wav),
        ]
        res = await run_process(cmd, timeout=120.0, on_pid=on_pid, cancel_check=cancel_check)

        # Clean up temporary files
        if pause_wav.exists():
            try:
                pause_wav.unlink()
            except Exception:
                pass
        if concat_txt.exists():
            try:
                concat_txt.unlink()
            except Exception:
                pass

        if res.returncode != 0 or not output_master_wav.exists():
            raise RuntimeError(f"FFmpeg audio chunk concatenation failed: {res.stderr[:200]}")

    # Measure duration
    dur = await measure_audio_duration(output_master_wav)

    # Compute SHA256 checksum
    hasher = hashlib.sha256()
    with open(output_master_wav, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    checksum = hasher.hexdigest()

    return output_master_wav, dur, checksum

async def create_telegram_playback_audio(
    master_wav: Path,
    output_audio: Path,
    on_pid: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """Create a compressed Opus or MP3 copy optimized for fast Telegram voice/audio playback."""
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-i", str(master_wav),
        "-c:a", "aac",
        "-b:a", "128k",
        str(output_audio),
    ]
    res = await run_process(cmd, timeout=60.0, on_pid=on_pid, cancel_check=cancel_check)
    if res.returncode != 0:
        return master_wav
    return output_audio
