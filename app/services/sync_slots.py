"""Plan from source timestamps, independently of translation-list ordering."""
from collections.abc import Sequence
from app.domain.dubbing import SourceSegment
from app.domain.sync import SpeechSlot, SyncPolicy, SyncPlanningError


def plan_speech_slots(
    segments: Sequence[SourceSegment],
    source_duration_ms: int,
    policy: SyncPolicy,
) -> dict[str, SpeechSlot]:
    if source_duration_ms <= 0 or not segments:
        raise SyncPlanningError("missing_source_timeline")
    ids = [s.segment_id for s in segments]
    if any(not i for i in ids) or len(ids) != len(set(ids)):
        raise SyncPlanningError("duplicate_or_empty_segment_id")
    ordered = sorted(segments, key=lambda s: (s.start_ms, s.end_ms, s.segment_id))
    result = {}
    for index, segment in enumerate(ordered):
        if not 0 <= segment.start_ms < segment.end_ms <= source_duration_ms:
            raise SyncPlanningError(f"invalid_source_timing:{segment.segment_id}")
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        if following and following.start_ms < segment.end_ms:
            # This serial assembler cannot safely mix simultaneous dialogue.
            raise SyncPlanningError(f"overlapping_source_segments:{segment.segment_id}:{following.segment_id}")
        next_bound = following.start_ms - policy.guard_ms if following else source_duration_ms
        target_end = min(segment.end_ms, next_bound, source_duration_ms)
        hard_end = min(segment.end_ms + policy.end_tolerance_ms, next_bound, source_duration_ms)
        if target_end <= segment.start_ms:
            raise SyncPlanningError(f"empty_speech_window:{segment.segment_id}")
        result[segment.segment_id] = SpeechSlot(
            segment.segment_id, segment.start_ms, segment.end_ms, target_end, hard_end
        )
    return result
