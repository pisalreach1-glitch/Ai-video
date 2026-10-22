"""Deterministic sample-based timeline assembly and sync report generation."""
from __future__ import annotations
import wave
import json
import logging
from pathlib import Path
from typing import Any
import hashlib
from app.config import config
from app.domain.dubbing import DubbingPlan, Placement, DubbingIssue
from app.domain.sync import SyncPolicy, SyncPlanningError, SpeechSlot
from app.services.sync_slots import plan_speech_slots
from app.services.sync_fitting import inspect_pcm
from app.services.sync_validation import validate_sync

logger = logging.getLogger(__name__)

def assemble_timeline_pcm(
    plan: DubbingPlan,
    output_wav_path: Path | str,
) -> tuple[list[Placement], dict[str, Any]]:
    """
    Assembles fitted audio clips onto an absolute silence timeline matching the source video length.
    Uses exact PCM sample positions (48kHz, 16-bit signed stereo).
    Guarantees no silent truncation: complete frames of every ready clip are placed.
    Returns (placements, sync_report).
    """
    dest = Path(output_wav_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    sample_rate = plan.sample_rate or config.dub_sample_rate
    channels = 2
    bytes_per_sample = 2 # 16-bit
    bytes_per_frame = channels * bytes_per_sample # 4 bytes

    total_frames = int(round((plan.source_duration_ms / 1000.0) * sample_rate))
    total_bytes = total_frames * bytes_per_frame
    timeline_buffer = bytearray(total_bytes)

    policy = SyncPolicy(
        max_tempo=config.dub_max_tempo,
        start_tolerance_ms=config.dub_sync_start_tolerance_ms,
        end_tolerance_ms=config.dub_sync_end_tolerance_ms,
        filter_duration_tolerance_ms=config.dub_sync_filter_duration_tolerance_ms,
        guard_ms=config.dub_sync_guard_ms,
        sample_rate=sample_rate,
    )

    slots: dict[str, SpeechSlot] = {}
    if plan.segments and plan.source_duration_ms > 0:
        try:
            slots = plan_speech_slots(plan.segments, plan.source_duration_ms, policy)
        except SyncPlanningError as spe:
            logger.warning(f"Speech slot planning in timeline assembly: {spe}")

    placements: list[Placement] = []
    issues: list[DubbingIssue] = []
    segments_report: list[dict[str, Any]] = []
    slots_report: list[dict[str, Any]] = []
    clips_report: list[dict[str, Any]] = []

    prev_speech_end_sample = 0

    # Sort clips by source segment start_ms
    sorted_clips = sorted(
        plan.clips,
        key=lambda c: (plan.get_segment(c.segment_id).start_ms if plan.get_segment(c.segment_id) else 0)
    )

    translations_map = {t.segment_id: t for t in plan.translations}
    assignments_map = {a.segment_id: a for a in plan.speaker_assignments}

    for clip in sorted_clips:
        s_seg = plan.get_segment(clip.segment_id)
        if not s_seg:
            continue

        slot = slots.get(clip.segment_id)
        slot_start_ms = s_seg.start_ms
        slot_end_ms = s_seg.end_ms
        target_end_ms = slot.target_end_ms if slot else slot_end_ms
        hard_end_ms = slot.hard_end_ms if slot else slot_end_ms

        slots_report.append({
            "segment_id": clip.segment_id,
            "start_ms": slot_start_ms,
            "end_ms": slot_end_ms,
            "duration_ms": s_seg.duration_ms,
            "target_end_ms": target_end_ms,
            "hard_end_ms": hard_end_ms,
        })

        clips_report.append({
            "segment_id": clip.segment_id,
            "raw_duration_ms": clip.raw_duration_ms,
            "fitted_duration_ms": clip.fitted_duration_ms,
            "tempo_factor": clip.tempo_factor,
            "status": clip.status,
        })

        start_sample = slot.start_sample(sample_rate) if slot else int(round((slot_start_ms / 1000.0) * sample_rate))
        clip_wav_path = Path(clip.fitted_audio_path or clip.raw_audio_path)

        clip_frames_bytes = b""
        actual_sample_count = 0

        if clip_wav_path.exists() and clip_wav_path.stat().st_size > 0:
            try:
                pcm_info = inspect_pcm(clip_wav_path, policy)
                actual_sample_count = pcm_info.frames
                with wave.open(str(clip_wav_path), "rb") as wf:
                    clip_frames_bytes = wf.readframes(actual_sample_count)
            except Exception as e:
                logger.warning(f"Error inspecting PCM for clip {clip.segment_id}: {e}")
                with wave.open(str(clip_wav_path), "rb") as wf:
                    actual_sample_count = wf.getnframes()
                    clip_frames_bytes = wf.readframes(actual_sample_count)

        actual_start_ms = start_sample * 1000.0 / sample_rate
        actual_end_ms = (start_sample + actual_sample_count) * 1000.0 / sample_rate
        speech_end_ms = int(round(actual_end_ms))
        start_offset_ms = actual_start_ms - slot_start_ms
        end_lag_ms = actual_end_ms - slot_end_ms # Honest negative if speech finishes early

        segment_blocking: list[str] = []

        # Check collision with previous utterance
        if start_sample < prev_speech_end_sample:
            collision_msg = f"Collision detected: Speech starts at {slot_start_ms}ms before previous speech ended at {round(prev_speech_end_sample * 1000 / sample_rate)}ms."
            issues.append(DubbingIssue(
                segment_id=clip.segment_id,
                issue_type="collision",
                message=collision_msg,
                severity="blocking",
                producer="timeline",
            ))
            segment_blocking.append("collision")

        prev_speech_end_sample = max(prev_speech_end_sample, start_sample + actual_sample_count)

        # Check overrun beyond source video duration
        if start_sample + actual_sample_count > total_frames:
            overrun_msg = f"Speech ends at {speech_end_ms}ms exceeding source video duration {plan.source_duration_ms}ms."
            issues.append(DubbingIssue(
                segment_id=clip.segment_id,
                issue_type="overrun",
                message=overrun_msg,
                severity="blocking",
                producer="timeline",
            ))
            segment_blocking.append("overrun")

        # Check hard end boundary
        if slot and (start_sample + actual_sample_count) > slot.hard_frames(sample_rate) + start_sample:
            late_msg = f"Speech ends at {speech_end_ms}ms exceeding hard speech window bound {hard_end_ms}ms."
            issues.append(DubbingIssue(
                segment_id=clip.segment_id,
                issue_type="late_end",
                message=late_msg,
                severity="blocking",
                producer="sync_validation",
            ))
            segment_blocking.append("late_end")

        placement = Placement(
            segment_id=clip.segment_id,
            timeline_start_ms=slot_start_ms,
            slot_end_ms=slot_end_ms,
            speech_end_ms=speech_end_ms,
            start_sample=start_sample,
            sample_count=actual_sample_count,
        )
        placements.append(placement)

        # Copy complete frames into buffer without truncation
        start_byte = start_sample * bytes_per_frame
        copy_len = len(clip_frames_bytes)
        if start_byte + copy_len <= total_bytes:
            timeline_buffer[start_byte:start_byte + copy_len] = clip_frames_bytes
        else:
            # Overrun error already flagged; place only up to buffer boundary
            safe_len = max(0, total_bytes - start_byte)
            if safe_len > 0:
                timeline_buffer[start_byte:total_bytes] = clip_frames_bytes[:safe_len]

        t_item = translations_map.get(clip.segment_id)
        asgn_item = assignments_map.get(clip.segment_id)
        voice_choice = plan.speaker_voice_map.get(asgn_item.speaker_id) if asgn_item and asgn_item.speaker_id else None

        segments_report.append({
            "segment_id": clip.segment_id,
            "source_start_ms": slot_start_ms,
            "source_end_ms": slot_end_ms,
            "target_end_ms": target_end_ms,
            "hard_end_ms": hard_end_ms,
            "actual_start_ms": round(actual_start_ms, 2),
            "actual_end_ms": round(actual_end_ms, 2),
            "start_offset_ms": round(start_offset_ms, 2),
            "end_lag_ms": round(end_lag_ms, 2),
            "raw_frames": int(round((clip.raw_duration_ms / 1000.0) * sample_rate)),
            "fitted_frames": actual_sample_count,
            "sample_rate": sample_rate,
            "tempo_factor": clip.tempo_factor,
            "translation_status": t_item.status if t_item else "ready",
            "voice_id": voice_choice.voice_id if voice_choice else "",
            "speaker_id": asgn_item.speaker_id if asgn_item else "",
            "stage_status": clip.status,
            "blocking_reasons": segment_blocking,
            "artifact_sha256": hashlib.sha256(clip_frames_bytes).hexdigest() if clip_frames_bytes else "",
        })

    # Write output WAV file
    with wave.open(str(dest), "wb") as out_wf:
        out_wf.setnchannels(channels)
        out_wf.setsampwidth(bytes_per_sample)
        out_wf.setframerate(sample_rate)
        out_wf.writeframes(timeline_buffer)

    plan.placements = placements
    if issues:
        plan.issues.extend(issues)

    sync_report = {
        "source_duration_ms": plan.source_duration_ms,
        "sample_rate": sample_rate,
        "slots": slots_report,
        "clips": clips_report,
        "segments": segments_report,
        "placements": [p.to_dict() for p in placements],
        "issues": [i.to_dict() for i in plan.issues],
        "validation_passed": not plan.has_blocking_issues,
    }

    return placements, sync_report
