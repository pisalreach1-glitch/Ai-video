"""Audio decode, validation, and PCM normalization for Voice Conversion."""
import hashlib
import json
import logging
from pathlib import Path
from typing import Tuple
from app.config import config
from app.jobs.processes import run_process

logger = logging.getLogger(__name__)

async def validate_audio_file(
    file_path: Path,
    min_duration: float = 3.0,
    max_duration: float = 300.0,
) -> Tuple[float, int, int]:
    """
    Validate that the file is decodable audio within allowed duration bounds.
    Returns: (duration_seconds, sample_rate, channels)
    """
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise ValueError("Audio file is empty or missing.")

    cmd = [
        config.ffprobe_path,
        "-v", "error",
        "-show_entries", "stream=codec_type,sample_rate,channels:format=duration",
        "-of", "json",
        str(file_path),
    ]

    res = await run_process(cmd, timeout=30.0)
    if res.returncode != 0:
        raise ValueError("File is not a valid audio format.")

    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        raise ValueError("Failed to parse audio probe data.")

    streams = data.get("streams", [])
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not audio_streams:
        raise ValueError("File does not contain an audio stream.")

    fmt = data.get("format", {})
    dur_str = fmt.get("duration")
    if not dur_str:
        dur_str = audio_streams[0].get("duration")

    if not dur_str:
        raise ValueError("Unable to determine audio duration.")

    duration = float(dur_str)
    sample_rate = int(audio_streams[0].get("sample_rate", 24000))
    channels = int(audio_streams[0].get("channels", 1))

    if duration < min_duration:
        raise ValueError(f"Audio is too short ({duration:.1f}s). Minimum is {min_duration:.1f}s.")
    if duration > max_duration:
        raise ValueError(f"Audio exceeds maximum limit ({duration:.1f}s > {max_duration:.1f}s).")

    return duration, sample_rate, channels

async def normalize_to_pcm_wav(
    source_path: Path,
    output_path: Path,
    target_sr: int = 24000,
) -> Tuple[Path, str]:
    """
    Convert any input audio to standard 16-bit mono PCM WAV.
    Returns: (output_path, sha256_checksum)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-i", str(source_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(target_sr),
        "-ac", "1",
        str(output_path),
    ]

    res = await run_process(cmd, timeout=60.0)
    if res.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"Failed to normalize audio to PCM WAV: {res.stderr[:200]}")

    hasher = hashlib.sha256()
    with open(output_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    sha256 = hasher.hexdigest()

    return output_path, sha256
