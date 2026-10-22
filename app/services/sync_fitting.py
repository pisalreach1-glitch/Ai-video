"""Fit whole PCM clips; preserve overlong clips for review instead of truncation."""
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import wave
from app.domain.dubbing import DubClip
from app.domain.sync import SpeechSlot, SyncPolicy

TempoWriter = Callable[[Path, Path, float], Awaitable[Path]]


@dataclass(frozen=True)
class PcmInfo:
    frames: int
    sample_rate: int

    @property
    def duration_ms(self) -> float:
        return self.frames * 1000 / self.sample_rate


def inspect_pcm(path: Path | str, policy: SyncPolicy) -> PcmInfo:
    path = Path(path)
    if not path.is_file():
        raise ValueError("missing_audio_file")
    try:
        with wave.open(str(path), "rb") as stream:
            if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth(), stream.getcomptype()) != (
                policy.sample_rate, 2, 2, "NONE"
            ):
                raise ValueError("invalid_pcm_format")
            frames = stream.getnframes()
            data = stream.readframes(frames)
            if frames <= 0 or len(data) != frames * 4:
                raise ValueError("empty_or_incomplete_pcm")
            return PcmInfo(frames, stream.getframerate())
    except (wave.Error, EOFError) as exc:
        raise ValueError("invalid_wav_file") from exc


async def fit_clip_to_slot(
    clip: DubClip,
    slot: SpeechSlot,
    policy: SyncPolicy,
    output_dir: Path,
    tempo_writer: TempoWriter,
    cancel_check: Callable[[], bool] | None = None,
) -> DubClip:
    """Call from a bounded worker using an immutable per-task output directory."""
    def checkpoint():
        if cancel_check and cancel_check():
            raise asyncio.CancelledError("sync_fit_cancelled")

    checkpoint()
    if clip.segment_id != slot.segment_id:
        raise ValueError("clip_slot_id_mismatch")
    raw_path = Path(clip.raw_audio_path)
    clip.status = "failed"
    raw = inspect_pcm(raw_path, policy)
    target_frames = slot.target_frames(policy.sample_rate)
    if target_frames <= 0 or slot.hard_frames(policy.sample_rate) < target_frames:
        raise ValueError("invalid_speech_slot")
    clip.raw_duration_ms = math.ceil(raw.duration_ms)
    clip.fitted_audio_path = str(raw_path)
    clip.fitted_duration_ms = math.ceil(raw.duration_ms)
    clip.tempo_factor = 1.0
    clip.status = "too_long"
    if raw.frames <= target_frames:
        clip.status = "ready"
        return clip
    factor = raw.frames / target_frames
    if factor > policy.max_tempo:
        return clip
    output_dir.mkdir(parents=True, exist_ok=True)
    # Hash the ID so source-derived identifiers cannot become path components.
    safe_id = hashlib.sha256(slot.segment_id.encode("utf-8")).hexdigest()[:16]
    for attempt in range(2):
        checkpoint()
        if factor > policy.max_tempo:
            break
        # Each retry starts from the complete original PCM, never the previous fit.
        destination = output_dir / f"{safe_id}.fit-{attempt}.wav"
        await tempo_writer(raw_path, destination, factor)
        checkpoint()
        measured = inspect_pcm(destination, policy)
        expected_frames = raw.frames / factor
        filter_slack = policy.filter_duration_tolerance_ms * policy.sample_rate / 1000
        if measured.frames < expected_frames - filter_slack:
            raise ValueError("fitted_audio_unexpectedly_short")
        if measured.frames <= slot.hard_frames(policy.sample_rate):
            clip.fitted_audio_path = str(destination)
            clip.fitted_duration_ms = math.ceil(measured.duration_ms)
            clip.tempo_factor = factor
            clip.status = "ready"
            return clip
        factor *= measured.frames / target_frames
    # Original audio and its full measured duration remain available for review.
    return clip
