"""Review gate and issue lifecycle management for multi-speaker dubbing."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence, Set
from typing import Any

from app.domain.speakers import ReviewIssue, SpeakerAssignment, VoiceChoice
from app.domain.models import VoiceSettings
from app.domain.dubbing import DubbingPlan
from app.services.speaker_voices import resolve_voice


class ReviewRequired(ValueError):
    """Raised when an operation cannot proceed due to unresolved review items."""
    pass


def assert_final_ready(
    segment_ids: Sequence[str],
    assignments: Mapping[str, SpeakerAssignment],
    voice_map: Mapping[str, VoiceChoice],
    available_voice_ids: Set[str],
    issues: Sequence[ReviewIssue],
    plan_digest: str,
    approved_full_preview_digest: str | None,
    plan_issues: Sequence[Any] | None = None,
) -> None:
    """
    Validates that all segments are assigned, voices resolved, all blocking issues
    (both speaker review issues and plan issues like too_long or missing_translation)
    are resolved or acknowledged where permitted, and that the approved full preview digest matches.
    """
    if not segment_ids or len(set(segment_ids)) != len(segment_ids):
        raise ReviewRequired("invalid_segments")

    # Check plan issues (e.g. missing translation, too_long, overrun)
    if plan_issues and any(getattr(i, "severity", "") == "blocking" for i in plan_issues):
        raise ReviewRequired("unresolved_plan_issues")

    # Check review issues or any blocking issues passed in
    for issue in issues:
        if getattr(issue, "severity", "") == "blocking":
            raise ReviewRequired("unresolved_plan_issues")
        if getattr(issue, "blocking", False) and getattr(issue, "is_open", True):
            raise ReviewRequired("unresolved_issues")

    for segment_id in segment_ids:
        assignment = assignments.get(segment_id)
        if assignment is None or assignment.segment_id != segment_id:
            raise ReviewRequired("missing_assignment")
        resolve_voice(assignment, voice_map, available_voice_ids, require_confirmed=True)

    if not plan_digest or approved_full_preview_digest != plan_digest:
        raise ReviewRequired("full_preview_required")


def compute_plan_content_digest(plan: DubbingPlan, settings: VoiceSettings) -> str:
    """
    Computes a deterministic SHA-256 digest of all semantic content in a DubbingPlan.
    Excludes volatile file paths, approval fields, and transport metadata.
    """
    segments_payload = [
        {
            "id": s.segment_id,
            "start": s.start_ms,
            "end": s.end_ms,
            "text": s.source_text.strip(),
            "speaker": s.speaker_id,
        }
        for s in plan.segments
    ]

    translations_payload = [
        {
            "id": t.segment_id,
            "text": t.translated_text.strip(),
        }
        for t in plan.translations
    ]

    assignments_payload = [
        {
            "seg_id": a.segment_id,
            "spk_id": a.speaker_id,
            "evidence": a.evidence_key,
        }
        for a in sorted(plan.speaker_assignments, key=lambda x: x.segment_id)
    ]

    voice_map_payload = {
        spk_id: {
            "voice": choice.voice_id,
            "rate": choice.rate,
        }
        for spk_id, choice in sorted(plan.speaker_voice_map.items())
    }

    render_settings_payload = {
        "aspect_ratio": settings.aspect_ratio,
        "framing_mode": settings.framing_mode,
        "duration_policy": settings.duration_policy,
        "source_audio_mode": settings.source_audio_mode,
        "subtitles_enabled": settings.subtitles_enabled,
        "subtitle_color": settings.subtitle_color,
        "subtitle_position": settings.subtitle_position,
    }

    payload = {
        "schema": 2,
        "mode": plan.mode,
        "speaker_mode": plan.speaker_mode,
        "plan_version": getattr(plan, "plan_version", 1),
        "sync_policy": getattr(plan, "sync_policy_metadata", {}),
        "source_fingerprint": plan.source_fingerprint,
        "analysis_key": plan.source_analysis_key,
        "segments": segments_payload,
        "translations": translations_payload,
        "assignments": assignments_payload,
        "voice_map": voice_map_payload,
        "settings": render_settings_payload,
    }

    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_subject_key(segment_id: str, text: str, start_ms: int, end_ms: int, speaker_id: str | None) -> str:
    """Computes a hash of the current subject inputs to bind human confirmations."""
    raw = f"{segment_id}:{start_ms}:{end_ms}:{speaker_id or ''}:{text.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def audit_speaker_plan(
    plan: DubbingPlan,
    available_voice_ids: Set[str],
    require_unscored_review: bool = True,
) -> list[ReviewIssue]:
    """
    Audits a multi-speaker plan and produces a list of ReviewIssue instances.
    Preserves existing confirmations if subject_key matches.
    """
    issues: list[ReviewIssue] = []
    existing_map = {i.issue_id: i for i in plan.review_issues}

    # Map assignments by segment_id
    assignment_map = {a.segment_id: a for a in plan.speaker_assignments}

    for seg in plan.segments:
        asgn = assignment_map.get(seg.segment_id)
        trans = plan.get_translation(seg.segment_id)
        text = trans.translated_text if trans else seg.source_text
        subj_key = compute_subject_key(seg.segment_id, text, seg.start_ms, seg.end_ms, asgn.speaker_id if asgn else None)

        if not asgn or not asgn.speaker_id:
            issue_id = f"unk_spk_{seg.segment_id}"
            prev = existing_map.get(issue_id)
            issues.append(
                ReviewIssue(
                    issue_id=issue_id,
                    segment_id=seg.segment_id,
                    reason="unknown_speaker",
                    subject_key=subj_key,
                    producer="speaker_review",
                    blocking=True,
                    allow_confirmation=False,
                )
            )
            continue

        spk_id = asgn.speaker_id
        # Check unscored or low confidence
        if asgn.confidence_kind == "unavailable" and require_unscored_review:
            issue_id = f"unscored_{seg.segment_id}"
            prev = existing_map.get(issue_id)
            confirmed_key = prev.confirmed_for_key if prev and prev.confirmed_for_key == subj_key else None
            issues.append(
                ReviewIssue(
                    issue_id=issue_id,
                    segment_id=seg.segment_id,
                    reason="unscored_assignment",
                    subject_key=subj_key,
                    producer="speaker_review",
                    blocking=True,
                    allow_confirmation=True,
                    confirmed_for_key=confirmed_key,
                )
            )
        elif asgn.confidence is not None and asgn.confidence < 0.65:
            issue_id = f"low_conf_{seg.segment_id}"
            prev = existing_map.get(issue_id)
            confirmed_key = prev.confirmed_for_key if prev and prev.confirmed_for_key == subj_key else None
            issues.append(
                ReviewIssue(
                    issue_id=issue_id,
                    segment_id=seg.segment_id,
                    reason="low_speaker_confidence",
                    subject_key=subj_key,
                    producer="speaker_review",
                    blocking=True,
                    allow_confirmation=True,
                    confirmed_for_key=confirmed_key,
                )
            )

        # Check voice choice
        choice = plan.speaker_voice_map.get(spk_id)
        if choice is None or not choice.confirmed:
            issue_id = f"missing_voice_{seg.segment_id}_{spk_id}"
            issues.append(
                ReviewIssue(
                    issue_id=issue_id,
                    segment_id=seg.segment_id,
                    reason="missing_voice",
                    subject_key=subj_key,
                    producer="speaker_review",
                    blocking=True,
                    allow_confirmation=False,
                )
            )
        elif choice.voice_id not in available_voice_ids:
            issue_id = f"invalid_voice_{seg.segment_id}_{choice.voice_id}"
            issues.append(
                ReviewIssue(
                    issue_id=issue_id,
                    segment_id=seg.segment_id,
                    reason="invalid_voice",
                    subject_key=subj_key,
                    producer="speaker_review",
                    blocking=True,
                    allow_confirmation=False,
                )
            )

    return issues
