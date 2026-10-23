"""Validation and normalization for voice reference audio."""
import hashlib
import json
import logging
from pathlib import Path
from typing import Callable
from app.config import config
from app.jobs.processes import run_process
from app.features.talking_photo.media import measure_audio_duration

logger = logging.getLogger(__name__)

async def validate_reference_audio(
    audio_path: Path,
    min_duration: float = 3.0,
    max_duration: float = 120.0,
) -> tuple[float, int, int]:
    """
    Validate that reference audio is readable, non-empty, and satisfies length bounds.
    Returns: (duration_seconds, sample_rate, channels)
    """
    if not audio_path.exists() or audio_path.stat().st_size < 1000:
        raise ValueError("ឯកសារសំឡេងគំរូទទេ ឬមិនត្រឹមត្រូវ (Audio file is empty or missing).")

    cmd = [
        config.ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(audio_path),
    ]
    res = await run_process(cmd, timeout=30.0)
    if res.returncode != 0:
        raise ValueError("មិនអាចអានឯកសារសំឡេងគំរូបានទេ (Cannot decode audio stream).")

    try:
        data = json.loads(res.stdout)
        audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
        if not audio_stream:
            raise ValueError("ឯកសារនេះមិនមាន audio track ទេ (No audio track found).")

        duration = float(audio_stream.get("duration") or 0.0)
        if duration <= 0:
            duration = await measure_audio_duration(audio_path)

        sample_rate = int(audio_stream.get("sample_rate", 24000))
        channels = int(audio_stream.get("channels", 1))
    except Exception as e:
        raise ValueError(f"បរាជ័យក្នុងការត្រួតពិនិត្យសំឡេងគំរូ៖ {e}")

    if duration < min_duration:
        raise ValueError(f"សំឡេងគំរូខ្លីពេក ({duration:.1f}s)។ សូមផ្ញើសំឡេងយ៉ាងតិច {min_duration:.0f} វិនាទី។")

    if duration > max_duration:
        raise ValueError(f"សំឡេងគំរូវែងពេក ({duration:.1f}s)។ សូមផ្ញើសំឡេងមិនលើសពី {max_duration:.0f} វិនាទី។")

    return duration, sample_rate, channels

async def normalize_reference_audio(
    input_path: Path,
    output_wav: Path,
    target_sr: int = 24000,
    on_pid: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[Path, str]:
    """
    Normalize reference audio to clean mono 16-bit PCM WAV at target sample rate.
    Returns: (output_wav, sha256_checksum)
    """
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-i", str(input_path),
        "-ar", str(target_sr),
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(output_wav),
    ]
    res = await run_process(cmd, timeout=60.0, on_pid=on_pid, cancel_check=cancel_check)
    if res.returncode != 0 or not output_wav.exists():
        raise RuntimeError(f"FFmpeg failed normalizing reference audio: {res.stderr[:200]}")

    hasher = hashlib.sha256()
    with open(output_wav, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    sha256 = hasher.hexdigest()

    return output_wav, sha256
