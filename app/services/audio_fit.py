"""Audio measurement, duration fitting with FFmpeg atempo, and overlong detection."""
from __future__ import annotations
import wave
import logging
from pathlib import Path
from typing import Callable, Any
from app.config import config
from app.domain.dubbing import DubClip, SourceSegment
from app.jobs.processes import run_process

logger = logging.getLogger(__name__)

def measure_wav_duration_ms(wav_path: Path | str) -> int:
    """Measure exact duration of a 16-bit PCM WAV file in milliseconds using sample count."""
    path = Path(wav_path)
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        if rate <= 0:
            return 0
        return int(round((frames / float(rate)) * 1000))

async def decode_mp3_to_wav(
    mp3_path: Path | str,
    wav_path: Path | str,
    sample_rate: int = 48000,
    channels: int = 2,
    trim_silence: bool = False,
) -> Path:
    """Decode any audio format to standardized 16-bit PCM stereo WAV, optionally trimming TTS silence padding."""
    dest = Path(wav_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-i", str(mp3_path),
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        str(dest),
    ]
    res = await run_process(cmd, timeout=30.0)
    if res.returncode != 0 or not dest.exists():
        raise RuntimeError(f"Failed to decode audio to WAV: {res.stderr[:200]}")

    if trim_silence and dest.exists():
        trimmed_dest = dest.with_suffix(".trimmed.wav")
        trim_cmd = [
            config.ffmpeg_path,
            "-y",
            "-i", str(dest),
            "-af", "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.03,areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.03,areverse",
            "-acodec", "pcm_s16le",
            "-ar", str(sample_rate),
            "-ac", str(channels),
            str(trimmed_dest),
        ]
        trim_res = await run_process(trim_cmd, timeout=15.0)
        if trim_res.returncode == 0 and trimmed_dest.exists():
            trimmed_ms = measure_wav_duration_ms(trimmed_dest)
            if trimmed_ms >= 100:
                trimmed_dest.replace(dest)
            else:
                trimmed_dest.unlink(missing_ok=True)

    return dest

async def apply_atempo(
    input_wav: Path | str,
    output_wav: Path | str,
    tempo: float,
    sample_rate: int = 48000,
    channels: int = 2,
    cancel_check: Callable[[], bool] | None = None,
    on_pid: Callable[[int], None] | None = None,
) -> Path:
    """Apply mild tempo adjustment using FFmpeg atempo filter without pitch alteration."""
    dest = Path(output_wav)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-i", str(input_wav),
        "-filter:a", f"atempo={tempo:.4f}",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        str(dest),
    ]
    res = await run_process(cmd, timeout=30.0, cancel_check=cancel_check, on_pid=on_pid)
    if res.cancelled:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise asyncio.CancelledError("atempo_cancelled")
    if res.timed_out:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise TimeoutError("atempo_timed_out")
    if res.returncode != 0 or not dest.exists():
        raise RuntimeError(f"Failed to apply atempo filter: {res.stderr[:200]}")
    return dest

async def fit_clip(
    clip: DubClip,
    source_segment: SourceSegment,
    max_tempo: float = 1.15,
    sample_rate: int = 48000,
    available_slot_ms: int | None = None,
) -> DubClip:
    """
    Measure decoded PCM duration against available slot.
    - If clip fits naturally: keep speed (tempo=1.0), leave trailing slot silent.
    - If clip is slightly overlong and required_tempo <= max_tempo:
      apply FFmpeg atempo and re-measure exact sample duration.
    - If required_tempo > max_tempo or still does not fit:
      mark status='too_long' without cutting or truncating speech.
    """
    raw_wav = Path(clip.raw_audio_path)
    if not raw_wav.exists():
        raise FileNotFoundError(f"Raw audio for segment {clip.segment_id} not found at {raw_wav}")

    raw_ms = measure_wav_duration_ms(raw_wav)
    clip.raw_duration_ms = raw_ms
    slot_ms = available_slot_ms if (available_slot_ms is not None and available_slot_ms > 0) else source_segment.duration_ms

    if slot_ms <= 0:
        clip.status = "too_long"
        return clip

    # Case 1: Fits naturally
    if raw_ms <= slot_ms:
        clip.fitted_audio_path = str(raw_wav)
        clip.fitted_duration_ms = raw_ms
        clip.tempo_factor = 1.0
        clip.status = "ready"
        return clip

    # Case 2: Requires tempo adjustment
    required_tempo = raw_ms / float(slot_ms)
    if required_tempo <= max_tempo:
        fitted_wav = raw_wav.parent / "fitted.wav"
        try:
            await apply_atempo(raw_wav, fitted_wav, tempo=required_tempo, sample_rate=sample_rate)
            measured_fitted_ms = measure_wav_duration_ms(fitted_wav)

            # Check if measured fitted PCM duration satisfies slot (with 10ms tolerance for sample-block rounding)
            if measured_fitted_ms <= slot_ms + 10:
                clip.fitted_audio_path = str(fitted_wav)
                clip.fitted_duration_ms = min(measured_fitted_ms, slot_ms)
                clip.tempo_factor = required_tempo
                clip.status = "ready"
                return clip
        except Exception as e:
            logger.warning(f"Failed to apply atempo for segment {clip.segment_id}: {e}")

    # Case 3: Overlong / Exceeds allowed tempo
    clip.status = "too_long"
    clip.fitted_audio_path = str(raw_wav)
    clip.fitted_duration_ms = raw_ms
    clip.tempo_factor = 1.0
    return clip
