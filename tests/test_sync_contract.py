"""Regression cases for source-window alignment and complete PCM placement."""
import asyncio
from pathlib import Path
import wave
from unittest.mock import AsyncMock
import pytest
from app.domain.dubbing import DubbingPlan, SourceSegment, TranslatedSegment, DubClip
from app.domain.sync import SyncPolicy, SyncPlanningError
from app.services.sync_slots import plan_speech_slots
from app.services.sync_fitting import fit_clip_to_slot, inspect_pcm
from app.services.sync_validation import build_absolute_placements, validate_sync


def pcm(path, duration_ms=500, channels=2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(b"\x01\x00" * channels * (duration_ms * 48))
    return path


def clip(path, sid="s001"):
    return DubClip(sid, "test-cache", str(path))


def plan_for(segments):
    return DubbingPlan(source_duration_ms=8000, segments=segments,
        translations=[TranslatedSegment(s.segment_id, "សួស្ដី", status="ready") for s in segments])


@pytest.mark.asyncio
@pytest.mark.parametrize("include_next", [True, False])
async def test_four_second_dub_cannot_use_gap_or_video_tail(tmp_path, include_next):
    segments = [SourceSegment("s001", 1000, 3000, "First")]
    if include_next:
        segments.append(SourceSegment("s002", 6000, 7000, "Second"))
    policy = SyncPolicy()
    slots = plan_speech_slots(segments, 8000, policy)
    original = pcm(tmp_path / "four_seconds.wav", 4000)
    writer = AsyncMock()
    result = await fit_clip_to_slot(clip(original), slots["s001"], policy, tmp_path / "fit", writer)
    assert result.status == "too_long"
    assert result.raw_duration_ms == 4000
    assert inspect_pcm(original, policy).duration_ms == 4000
    writer.assert_not_called()


@pytest.mark.asyncio
async def test_shorter_speech_stays_at_natural_speed(tmp_path):
    policy = SyncPolicy()
    slots = plan_speech_slots([SourceSegment("s001", 1000, 3000, "Hello")], 8000, policy)
    writer = AsyncMock()
    fitted = await fit_clip_to_slot(clip(pcm(tmp_path / "short.wav", 700)), slots["s001"], policy, tmp_path / "fit", writer)
    assert fitted.status == "ready" and fitted.tempo_factor == 1
    assert fitted.fitted_duration_ms == 700
    writer.assert_not_called()


@pytest.mark.asyncio
async def test_mild_fit_keeps_actual_duration_metadata(tmp_path):
    policy = SyncPolicy()
    plan = plan_for([SourceSegment("s001", 1000, 3000, "Hello")])
    slots = plan_speech_slots(plan.segments, 8000, policy)
    factors = []
    async def writer(source, dest, factor):
        factors.append(factor)
        return pcm(dest, 2025)  # Simulate finite FFmpeg output padding.
    fitted = await fit_clip_to_slot(clip(pcm(tmp_path / "raw.wav", 2160)), slots["s001"], policy, tmp_path / "fit", writer)
    assert fitted.status == "ready" and factors == [pytest.approx(1.08)]
    assert fitted.fitted_duration_ms == 2025  # Never relabel 2025 as 2000.
    plan.clips = [fitted]
    plan.placements = build_absolute_placements(plan, slots, policy)
    assert plan.placements[0].speech_end_ms == 3025
    assert validate_sync(plan, slots, policy) == []


@pytest.mark.asyncio
async def test_real_ffmpeg_atempo_is_measured(tmp_path):
    from app.services.audio_fit import apply_atempo
    policy = SyncPolicy()
    plan = plan_for([SourceSegment("s001", 1000, 3000, "Hello")])
    slots = plan_speech_slots(plan.segments, 8000, policy)
    fitted = await fit_clip_to_slot(clip(pcm(tmp_path / "raw_ffmpeg.wav", 2160)), slots["s001"], policy, tmp_path / "ffmpeg", apply_atempo)
    assert fitted.status == "ready"
    actual = inspect_pcm(fitted.fitted_audio_path, policy)
    assert fitted.fitted_duration_ms >= actual.duration_ms
    assert actual.frames <= slots["s001"].hard_frames(policy.sample_rate)


@pytest.mark.asyncio
async def test_partial_tempo_output_is_not_accepted(tmp_path):
    policy = SyncPolicy()
    slot = plan_speech_slots([SourceSegment("s001", 1000, 3000, "Hello")], 8000, policy)["s001"]
    async def partial_writer(source, dest, factor):
        return pcm(dest, 500)
    with pytest.raises(ValueError, match="fitted_audio_unexpectedly_short"):
        await fit_clip_to_slot(clip(pcm(tmp_path / "raw.wav", 2160)), slot, policy, tmp_path / "fit", partial_writer)


@pytest.mark.asyncio
async def test_next_utterance_remains_a_hard_boundary(tmp_path):
    policy = SyncPolicy()
    segments = [SourceSegment("s001", 1000, 3000, "A"), SourceSegment("s002", 3000, 4000, "B")]
    slot = plan_speech_slots(segments, 8000, policy)["s001"]
    assert slot.hard_end_ms == 3000
    factors = []
    async def padded_writer(source, dest, factor):
        factors.append(factor)
        return pcm(dest, 2100)
    fitted = await fit_clip_to_slot(clip(pcm(tmp_path / "raw.wav", 2160)), slot, policy, tmp_path / "fit", padded_writer)
    assert fitted.status == "too_long"
    assert len(factors) == 2
    assert fitted.fitted_duration_ms == 2160


@pytest.mark.parametrize("start,end", [(-1, 1000), (3000, 2000), (0, 9000)])
def test_invalid_source_timing_is_blocked(start, end):
    with pytest.raises(SyncPlanningError):
        plan_speech_slots([SourceSegment("s001", start, end, "Bad")], 8000, SyncPolicy())


def test_overlapping_speech_requires_review():
    with pytest.raises(SyncPlanningError, match="overlapping_source_segments"):
        plan_speech_slots([SourceSegment("a", 0, 2000, "A"), SourceSegment("b", 1500, 3000, "B")], 8000, SyncPolicy())


def test_unsorted_sources_are_planned_by_id():
    slots = plan_speech_slots([SourceSegment("b", 4000, 6000, "B"), SourceSegment("a", 1000, 3000, "A")], 8000, SyncPolicy())
    assert slots["a"].target_end_ms == 3000
    assert slots["b"].start_sample(48000) == 192000


@pytest.mark.parametrize("kind", ["missing", "empty", "mono", "corrupt"])
def test_invalid_pcm_is_rejected(tmp_path, kind):
    path = tmp_path / "input.wav"
    if kind == "empty":
        pcm(path, 0)
    elif kind == "mono":
        pcm(path, 500, channels=1)
    elif kind == "corrupt":
        path.write_bytes(b"invalid wav")
    with pytest.raises(ValueError):
        inspect_pcm(path, SyncPolicy())


@pytest.mark.asyncio
async def test_validator_catches_old_ready_but_late_clip(tmp_path):
    policy = SyncPolicy()
    plan = plan_for([SourceSegment("s001", 1000, 3000, "Hello")])
    slots = plan_speech_slots(plan.segments, 8000, policy)
    old_clip = clip(pcm(tmp_path / "old.wav", 4000))
    old_clip.status = "ready"
    plan.clips = [old_clip]
    plan.placements = build_absolute_placements(plan, slots, policy)
    assert "late_end" in {i.issue_type for i in validate_sync(plan, slots, policy)}


def test_review_translation_is_not_ready(tmp_path):
    policy = SyncPolicy()
    plan = plan_for([SourceSegment("s001", 1000, 3000, "Hello")])
    slots = plan_speech_slots(plan.segments, 8000, policy)
    plan.translations[0].status = "needs_review"
    c = clip(pcm(tmp_path / "valid.wav"))
    c.status = "ready"
    plan.clips = [c]
    plan.placements = build_absolute_placements(plan, slots, policy)
    assert "unready_translation" in {i.issue_type for i in validate_sync(plan, slots, policy)}


@pytest.mark.asyncio
async def test_cancellation_after_tempo_does_not_return_ready(tmp_path):
    policy = SyncPolicy()
    slot = plan_speech_slots([SourceSegment("s001", 1000, 3000, "Hello")], 8000, policy)["s001"]
    cancelled = False
    async def writer(source, dest, factor):
        nonlocal cancelled
        pcm(dest, 2000)
        cancelled = True
        return dest
    with pytest.raises(asyncio.CancelledError):
        await fit_clip_to_slot(clip(pcm(tmp_path / "raw.wav", 2160)), slot, policy, tmp_path / "fit", writer, lambda: cancelled)


def test_cumulative_positions_and_corrupt_placement_are_detected(tmp_path):
    policy = SyncPolicy()
    starts = [137, 1703, 3491, 6107]
    plan = plan_for([SourceSegment(f"s{i}", start, start + 600, "Hi") for i, start in enumerate(starts)])
    slots = plan_speech_slots(plan.segments, 8000, policy)
    for s in plan.segments:
        c = clip(pcm(tmp_path / f"{s.segment_id}.wav", 500), s.segment_id)
        c.status = "ready"
        plan.clips.append(c)
    plan.translations.reverse()
    plan.placements = build_absolute_placements(plan, slots, policy)
    assert [p.start_sample for p in plan.placements] == [round(start * 48) for start in starts]
    assert validate_sync(plan, slots, policy) == []
    plan.placements[1].sample_count = 1
    assert "placement_audio_mismatch" in {i.issue_type for i in validate_sync(plan, slots, policy)}
