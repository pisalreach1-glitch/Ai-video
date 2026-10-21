"""Deterministic sample-based timeline assembly and sync report generation."""
from __future__ import annotations
import wave
import json
import logging
from pathlib import Path
from typing import Any
from app.domain.dubbing import DubbingPlan, Placement, DubbingIssue

logger = logging.getLogger(__name__)

def assemble_timeline_pcm(
    plan: DubbingPlan,
    output_wav_path: Path | str,
) -> tuple[list[Placement], dict[str, Any]]:
    """
    Assembles fitted audio clips onto an absolute silence timeline matching the source video length.
    Uses exact PCM sample positions (48kHz, 16-bit signed stereo).
    Returns (placements, sync_report).
    """
    dest = Path(output_wav_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    sample_rate = plan.sample_rate # 48000
    channels = 2
    bytes_per_sample = 2 # 16-bit
    bytes_per_frame = channels * bytes_per_sample # 4 bytes

    total_frames = int(round((plan.source_duration_ms / 1000.0) * sample_rate))
    total_bytes = total_frames * bytes_per_frame
    timeline_buffer = bytearray(total_bytes)

    placements: list[Placement] = []
    issues: list[DubbingIssue] = []
    slots_report: list[dict[str, Any]] = []
    clips_report: list[dict[str, Any]] = []

    prev_speech_end_ms = 0

    for clip in plan.clips:
        s_seg = plan.get_segment(clip.segment_id)
        if not s_seg:
            continue

        slot_start_ms = s_seg.start_ms
        slot_end_ms = s_seg.end_ms
        slot_duration_ms = s_seg.duration_ms
        effective_dur_ms = clip.effective_duration_ms

        slots_report.append({
            "segment_id": clip.segment_id,
            "start_ms": slot_start_ms,
            "end_ms": slot_end_ms,
            "duration_ms": slot_duration_ms,
        })

        clips_report.append({
            "segment_id": clip.segment_id,
            "raw_duration_ms": clip.raw_duration_ms,
            "fitted_duration_ms": clip.fitted_duration_ms,
            "tempo_factor": clip.tempo_factor,
            "status": clip.status,
        })

        # Check collision with previous utterance
        if slot_start_ms < prev_speech_end_ms:
            issues.append(DubbingIssue(
                segment_id=clip.segment_id,
                issue_type="collision",
                message=f"Collision detected: Speech starts at {slot_start_ms}ms before previous speech ended at {prev_speech_end_ms}ms.",
                severity="blocking",
            ))

        start_sample = int(round((slot_start_ms / 1000.0) * sample_rate))
        clip_wav_path = Path(clip.fitted_audio_path or clip.raw_audio_path)

        clip_frames_bytes = b""
        actual_sample_count = 0

        if clip_wav_path.exists() and clip_wav_path.stat().st_size > 0:
            with wave.open(str(clip_wav_path), "rb") as wf:
                actual_sample_count = wf.getnframes()
                clip_frames_bytes = wf.readframes(actual_sample_count)

        speech_end_ms = slot_start_ms + int(round((actual_sample_count / float(sample_rate)) * 1000))
        prev_speech_end_ms = speech_end_ms

        # Check overrun beyond source video duration
        if speech_end_ms > plan.source_duration_ms:
            issues.append(DubbingIssue(
                segment_id=clip.segment_id,
                issue_type="overrun",
                message=f"Speech ends at {speech_end_ms}ms exceeding source video duration {plan.source_duration_ms}ms.",
                severity="blocking",
            ))

        placement = Placement(
            segment_id=clip.segment_id,
            timeline_start_ms=slot_start_ms,
            slot_end_ms=slot_end_ms,
            speech_end_ms=speech_end_ms,
            start_sample=start_sample,
            sample_count=actual_sample_count,
        )
        placements.append(placement)

        # Place PCM bytes into buffer
        start_byte = start_sample * bytes_per_frame
        end_byte = min(total_bytes, start_byte + len(clip_frames_bytes))
        copy_len = end_byte - start_byte
        if copy_len > 0:
            timeline_buffer[start_byte:end_byte] = clip_frames_bytes[:copy_len]

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
        "placements": [p.to_dict() for p in placements],
        "issues": [i.to_dict() for i in plan.issues],
        "validation_passed": not plan.has_blocking_issues,
    }

    return placements, sync_report
