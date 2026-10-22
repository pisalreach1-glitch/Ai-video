"""Recheck actual PCM and absolute placements before assembly and final export."""
from collections import Counter
from app.domain.dubbing import DubbingPlan, Placement
from app.domain.sync import SpeechSlot, SyncPolicy, SyncProblem
from app.services.sync_fitting import inspect_pcm


def build_absolute_placements(
    plan: DubbingPlan, slots: dict[str, SpeechSlot], policy: SyncPolicy
) -> list[Placement]:
    if plan.sample_rate != policy.sample_rate:
        raise ValueError("plan_sample_rate_mismatch")
    if len({c.segment_id for c in plan.clips}) != len(plan.clips):
        raise ValueError("duplicate_clip_id")
    clips = {c.segment_id: c for c in plan.clips}
    if set(clips) != set(slots):
        raise ValueError("incomplete_clip_coverage")
    placements = []
    for slot in sorted(slots.values(), key=lambda item: item.start_ms):
        clip = clips[slot.segment_id]
        if clip.status != "ready":
            raise ValueError(f"unready_clip:{slot.segment_id}")
        pcm = inspect_pcm(clip.fitted_audio_path or clip.raw_audio_path, policy)
        start = slot.start_sample(policy.sample_rate)
        placements.append(Placement(
            segment_id=slot.segment_id, timeline_start_ms=slot.start_ms,
            slot_end_ms=slot.source_end_ms,
            speech_end_ms=round((start + pcm.frames) * 1000 / policy.sample_rate),
            start_sample=start, sample_count=pcm.frames,
        ))
    return placements


def validate_sync(
    plan: DubbingPlan, slots: dict[str, SpeechSlot], policy: SyncPolicy
) -> list[SyncProblem]:
    issues = []
    def add(sid, kind, message):
        issues.append(SyncProblem(sid, kind, message))

    expected = {s.segment_id for s in plan.segments}
    if not expected or len(expected) != len(plan.segments) or set(slots) != expected:
        add("global", "invalid_sync_source", "Source IDs and speech-slot IDs must match exactly.")
    if plan.sample_rate != policy.sample_rate:
        add("global", "invalid_sample_rate", "Normalize all PCM and the plan to the configured sample rate.")
    for stage, items in (("translation", plan.translations), ("clip", plan.clips), ("placement", plan.placements)):
        counts = Counter(item.segment_id for item in items)
        for sid in expected | set(counts):
            if counts[sid] != 1 or sid not in expected:
                add(sid, f"invalid_{stage}_coverage", f"Exactly one current {stage} is required for each source ID.")
    translations = {t.segment_id: t for t in plan.translations}
    clips = {c.segment_id: c for c in plan.clips}
    placements = {p.segment_id: p for p in plan.placements}
    occupied = []
    for sid in sorted(expected):
        text, clip, placement, slot = translations.get(sid), clips.get(sid), placements.get(sid), slots.get(sid)
        if text and (text.status != "ready" or not text.translated_text.strip()):
            add(sid, "unready_translation", "Review and accept the complete translation first.")
        if clip and clip.status != "ready":
            add(sid, "unready_clip", f"Clip status is {clip.status}.")
        if not clip or not placement or not slot:
            continue
        try:
            pcm = inspect_pcm(clip.fitted_audio_path or clip.raw_audio_path, policy)
        except (ValueError, OSError) as exc:
            add(sid, "invalid_audio", str(exc))
            continue
        start = placement.start_sample
        end = start + pcm.frames
        start_ms = start * 1000 / policy.sample_rate
        end_ms = end * 1000 / policy.sample_rate
        if start < 0 or abs(start_ms - slot.start_ms) > policy.start_tolerance_ms:
            add(sid, "start_offset", f"Speech begins {start_ms - slot.start_ms:+.1f} ms from the source start.")
        if end > round(slot.hard_end_ms * policy.sample_rate / 1000):
            add(sid, "late_end", f"Speech ends {end_ms - slot.source_end_ms:+.1f} ms from the source end.")
        if placement.sample_count != pcm.frames or abs(placement.speech_end_ms - end_ms) > 1:
            add(sid, "placement_audio_mismatch", "Placement must describe every frame of the actual clip.")
        if abs(placement.timeline_start_ms - start_ms) > 1 or placement.slot_end_ms != slot.source_end_ms:
            add(sid, "placement_source_mismatch", "Placement metadata does not match its source slot.")
        occupied.append((start, end, sid))
    previous_end = -1
    for start, end, sid in sorted(occupied):
        if start < previous_end:
            add(sid, "collision", "Dubbed speech overlaps another utterance.")
        previous_end = max(previous_end, end)
    return issues
