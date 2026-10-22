"""Tests for review gate, issue life cycle, evidence matching, and content digest approval."""
import pytest
from app.domain.dubbing import DubbingPlan, SourceSegment, TranslatedSegment
from app.domain.speakers import SpeakerAssignment, VoiceChoice, ReviewIssue
from app.domain.models import VoiceSettings
from app.services.speaker_review import (
    assert_final_ready,
    audit_speaker_plan,
    compute_plan_content_digest,
    compute_subject_key,
    ReviewRequired,
)


def test_review_gate_requires_matching_full_preview_approval():
    """Criteria 18: Full export requires approval of current full-preview content digest."""
    plan = DubbingPlan(
        segments=[SourceSegment(segment_id="s001", start_ms=0, end_ms=1000, source_text="Hello")],
        translations=[TranslatedSegment(segment_id="s001", translated_text="សួស្តី")],
        speaker_assignments=[SpeakerAssignment(segment_id="s001", speaker_id="Speaker A", evidence_key="ev1")],
        speaker_voice_map={"Speaker A": VoiceChoice(voice_id="km-KH-SreymomNeural", confirmed=True)},
    )
    available_voices = {"km-KH-SreymomNeural"}
    settings = VoiceSettings()

    current_digest = compute_plan_content_digest(plan, settings)

    # Rejection when full preview digest has not been approved
    with pytest.raises(ReviewRequired) as exc1:
        assert_final_ready(
            segment_ids=["s001"],
            assignments={a.segment_id: a for a in plan.speaker_assignments},
            voice_map=plan.speaker_voice_map,
            available_voice_ids=available_voices,
            issues=[],
            plan_digest=current_digest,
            approved_full_preview_digest=None,
        )
    assert "full_preview_required" in str(exc1.value)

    # Rejection when an old or different digest was approved
    with pytest.raises(ReviewRequired) as exc2:
        assert_final_ready(
            segment_ids=["s001"],
            assignments={a.segment_id: a for a in plan.speaker_assignments},
            voice_map=plan.speaker_voice_map,
            available_voice_ids=available_voices,
            issues=[],
            plan_digest=current_digest,
            approved_full_preview_digest="stale_digest_12345",
        )
    assert "full_preview_required" in str(exc2.value)

    # Success when matching digest is approved
    assert_final_ready(
        segment_ids=["s001"],
        assignments={a.segment_id: a for a in plan.speaker_assignments},
        voice_map=plan.speaker_voice_map,
        available_voice_ids=available_voices,
        issues=[],
        plan_digest=current_digest,
        approved_full_preview_digest=current_digest,
    )


def test_manually_confirmed_uncertainty_invalidates_on_edit():
    """Criteria 6: Confirmation stays resolved only for matching evidence; editing text/time invalidates approval."""
    seg = SourceSegment(segment_id="s001", start_ms=1000, end_ms=3000, source_text="Old text")
    old_key = compute_subject_key(seg.segment_id, seg.source_text, seg.start_ms, seg.end_ms, "Speaker A")

    # Issue confirmed for old subject key
    issue = ReviewIssue(
        issue_id="unscored_s001",
        segment_id="s001",
        reason="unscored_assignment",
        subject_key=old_key,
        allow_confirmation=True,
        confirmed_for_key=old_key,
    )
    # When subject_key matches confirmed_for_key, issue is resolved (not is_open)
    assert not issue.is_open

    # Now simulate text edit -> new subject key
    new_text = "Edited text"
    new_key = compute_subject_key(seg.segment_id, new_text, seg.start_ms, seg.end_ms, "Speaker A")
    assert new_key != old_key

    edited_issue = ReviewIssue(
        issue_id="unscored_s001",
        segment_id="s001",
        reason="unscored_assignment",
        subject_key=new_key,
        allow_confirmation=True,
        confirmed_for_key=old_key,  # confirmation was for old key!
    )
    # Now issue is OPEN again because confirmation key does not match!
    assert edited_issue.is_open


def test_blocking_speaker_issue_prevents_final_ready():
    """Criteria 7: Blocking issues prevent final ready even if clips are fitted."""
    available_voices = {"km-KH-SreymomNeural"}
    open_issue = ReviewIssue(
        issue_id="missing_voice_s001",
        segment_id="s001",
        reason="missing_voice",
        subject_key="k1",
        blocking=True,
        allow_confirmation=False,
    )
    with pytest.raises(ReviewRequired) as exc:
        assert_final_ready(
            segment_ids=["s001"],
            assignments={"s001": SpeakerAssignment(segment_id="s001", speaker_id="Speaker A", evidence_key="ev1")},
            voice_map={"Speaker A": VoiceChoice(voice_id="km-KH-SreymomNeural", confirmed=True)},
            available_voice_ids=available_voices,
            issues=[open_issue],
            plan_digest="d1",
            approved_full_preview_digest="d1",
        )
    assert "unresolved_issues" in str(exc.value)
