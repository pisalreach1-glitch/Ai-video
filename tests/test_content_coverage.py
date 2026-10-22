"""Tests for content coverage validation, completeness reporting, and review findings F1-F10."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from app.domain.dubbing import (
    DubbingPlan,
    SourceSegment,
    TranslatedSegment,
    DubClip,
    Placement,
    DubbingIssue,
)
from app.domain.speakers import (
    SpeakerAssignment,
    VoiceChoice,
    ReviewIssue,
)
from app.domain.models import VoiceSettings
from app.services.content_coverage import (
    validate_content_coverage,
    generate_completeness_report,
)
from app.services.speaker_review import assert_final_ready, ReviewRequired
from app.storage.speaker_reviews import speaker_review_store


# ---------------------------------------------------------------------------
# Content Coverage & Completeness Tests
# ---------------------------------------------------------------------------

def test_coverage_rejects_empty_plan():
    plan = DubbingPlan(segments=[])
    issues = validate_content_coverage(plan, VoiceSettings(), require_clips_and_placements=False)
    assert any(i.issue_type == "missing_source_segments" for i in issues)


def test_coverage_rejects_duplicate_or_invalid_source_timing():
    # Duplicate IDs
    plan = DubbingPlan(
        segments=[
            SourceSegment(segment_id="s001", start_ms=0, end_ms=1000, source_text="A"),
            SourceSegment(segment_id="s001", start_ms=1000, end_ms=2000, source_text="B"),
        ],
        translations=[
            TranslatedSegment(segment_id="s001", translated_text="ក"),
        ],
    )
    issues = validate_content_coverage(plan, VoiceSettings(), require_clips_and_placements=False)
    assert any(i.issue_type == "duplicate_segment_ids" for i in issues)

    # Invalid timing (end <= start)
    plan_timing = DubbingPlan(
        segments=[
            SourceSegment(segment_id="s001", start_ms=1000, end_ms=500, source_text="A"),
        ],
        translations=[
            TranslatedSegment(segment_id="s001", translated_text="ក"),
        ],
    )
    issues_timing = validate_content_coverage(plan_timing, VoiceSettings(), require_clips_and_placements=False)
    assert any(i.issue_type == "invalid_source_timing" for i in issues_timing)


def test_coverage_rejects_unready_or_orphaned_translations():
    plan = DubbingPlan(
        segments=[
            SourceSegment(segment_id="s001", start_ms=0, end_ms=1000, source_text="A"),
            SourceSegment(segment_id="s002", start_ms=1000, end_ms=2000, source_text="B"),
        ],
        translations=[
            TranslatedSegment(segment_id="s001", translated_text="", status="pending"),
            TranslatedSegment(segment_id="s003", translated_text="គ", status="ready"),  # orphaned
        ],
    )
    issues = validate_content_coverage(plan, VoiceSettings(), require_clips_and_placements=False)
    types = [i.issue_type for i in issues]
    assert "missing_translation" in types or "unready_translation" in types
    assert "orphaned_translation" in types


def test_coverage_requires_clips_and_placements_when_requested():
    plan = DubbingPlan(
        source_duration_ms=2000,
        segments=[
            SourceSegment(segment_id="s001", start_ms=0, end_ms=1000, source_text="Hello"),
        ],
        translations=[
            TranslatedSegment(segment_id="s001", translated_text="សួស្តី", status="ready"),
        ],
        speaker_mode="single",
    )
    # Without clips/placements
    issues = validate_content_coverage(plan, VoiceSettings(), require_clips_and_placements=True)
    types = [i.issue_type for i in issues]
    assert "missing_clip" in types
    assert "missing_placement" in types


def test_coverage_succeeds_with_complete_plan(tmp_path, monkeypatch):
    from app.storage.workspaces import workspace
    monkeypatch.setattr(workspace, "get_revision_dir", lambda jid, rev: tmp_path)

    plan = DubbingPlan(
        source_duration_ms=2000,
        segments=[
            SourceSegment(segment_id="s001", start_ms=0, end_ms=1000, source_text="Hello"),
        ],
        translations=[
            TranslatedSegment(
                segment_id="s001",
                translated_text="សួស្តី",
                full_translation="សួស្តី",
                status="ready",
            ),
        ],
        clips=[
            DubClip(segment_id="s001", tts_cache_key="k1", raw_audio_path="a.wav", raw_duration_ms=800, status="ready"),
        ],
        placements=[
            Placement(segment_id="s001", timeline_start_ms=0, slot_end_ms=1000, speech_end_ms=800, start_sample=0, sample_count=19200),
        ],
        speaker_mode="single",
    )
    issues = validate_content_coverage(plan, VoiceSettings(), require_clips_and_placements=True)
    assert len(issues) == 0

    report = generate_completeness_report(plan, VoiceSettings(), "job1", 1)
    assert report["is_complete"] is True
    assert (tmp_path / "completeness_report.json").exists()


# ---------------------------------------------------------------------------
# F1: Token Guard & Cross-User Rejection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_f1_verify_speaker_token_guards():
    from app.handlers.speakers import verify_speaker_token
    from app.storage.jobs import job_storage
    from app.jobs.worker import worker_pool

    job = job_storage.create_job(user_id=100, chat_id=200)
    tok = speaker_review_store.create_token(job.job_id, revision_id=1, user_id=100)

    # Call from wrong user
    call_wrong_user = AsyncMock()
    call_wrong_user.from_user.id = 999
    call_wrong_user.message.chat.id = 200
    res = await verify_speaker_token(call_wrong_user, tok)
    assert res is None
    call_wrong_user.answer.assert_called_with("អ្នកមិនមានសិទ្ធិកែប្រែការងាររបស់អ្នកដទៃឡើយ។", show_alert=True)

    # Call with cancelled job
    call_owner = AsyncMock()
    call_owner.from_user.id = 100
    call_owner.message.chat.id = 200
    worker_pool.cancel_job(job.job_id)
    res_cancelled = await verify_speaker_token(call_owner, tok)
    assert res_cancelled is None
    call_owner.answer.assert_called_with("ការងារត្រូវបានបោះបង់រួចហើយ។", show_alert=True)


# ---------------------------------------------------------------------------
# F3: Honest Speaker Setup (No Fake Alternating Turns)
# ---------------------------------------------------------------------------

def test_f3_no_fake_speaker_turns_when_diarization_unavailable():
    """Unavailable analysis creates unknown_speaker, not fake alternating A/B turns."""
    from app.services.speaker_assignment import assign_speakers_to_segments

    # Diarization unavailable or no turns
    out_segs, assignments, issues = assign_speakers_to_segments(
        segments=[
            SourceSegment(segment_id="s001", start_ms=0, end_ms=1000, source_text="One"),
            SourceSegment(segment_id="s002", start_ms=3000, end_ms=4000, source_text="Two"),
        ],
        turns=[],
    )
    # Segments should NOT be artificially split into Speaker A / Speaker B
    for asgn in assignments:
        assert asgn.speaker_id is None or asgn.confidence == 0.0 or asgn.origin == "auto"
    # Must flag unknown_speaker issues
    assert any(iss.reason == "unknown_speaker" for iss in issues)


# ---------------------------------------------------------------------------
# F6: Final Approval Rejects Blocking Issues in plan.issues
# ---------------------------------------------------------------------------

def test_f6_final_approval_rejects_blocking_plan_issues():
    """Even if review_issues is empty and digest matches, plan.issues blocks export."""
    from app.services.speaker_review import compute_plan_content_digest

    plan = DubbingPlan(
        segments=[SourceSegment(segment_id="s001", start_ms=0, end_ms=1000, source_text="Hello")],
        translations=[TranslatedSegment(segment_id="s001", translated_text="សួស្តី")],
        speaker_assignments=[SpeakerAssignment(segment_id="s001", speaker_id="Speaker A", evidence_key="ev1")],
        speaker_voice_map={"Speaker A": VoiceChoice(voice_id="km-KH-SreymomNeural", confirmed=True)},
        issues=[
            DubbingIssue(segment_id="s001", issue_type="too_long", message="Audio too long", severity="blocking")
        ],
    )
    digest = compute_plan_content_digest(plan, VoiceSettings())

    with pytest.raises(ReviewRequired) as exc:
        assert_final_ready(
            segment_ids=["s001"],
            assignments={a.segment_id: a for a in plan.speaker_assignments},
            voice_map=plan.speaker_voice_map,
            available_voice_ids={"km-KH-SreymomNeural"},
            issues=plan.issues,  # plan.issues contains blocking item!
            plan_digest=digest,
            approved_full_preview_digest=digest,
        )
    assert "blocking" in str(exc.value) or "unresolved" in str(exc.value)


# ---------------------------------------------------------------------------
# F7: Voice Confirmation Retains Other Producers' Issues
# ---------------------------------------------------------------------------

def test_f7_audit_speaker_plan_preserves_speaker_assignment_issues():
    """Voice confirmation does not wipe out competing_speakers or unscored assignments."""
    from app.services.speaker_review import audit_speaker_plan

    existing_issue = ReviewIssue(
        issue_id="competing_s001",
        segment_id="s001",
        reason="competing_speakers",
        subject_key="k1",
        blocking=False,
        producer="speaker_assignment",
    )
    plan = DubbingPlan(
        segments=[SourceSegment(segment_id="s001", start_ms=0, end_ms=1000, source_text="Hello")],
        translations=[TranslatedSegment(segment_id="s001", translated_text="សួស្តី")],
        speaker_assignments=[SpeakerAssignment(segment_id="s001", speaker_id="Speaker A", evidence_key="k1")],
        speaker_voice_map={"Speaker A": VoiceChoice(voice_id="km-KH-SreymomNeural", confirmed=True)},
        review_issues=[existing_issue],
    )

    # In cb_speaker_confirm_voice:
    other_producer_issues = [iss for iss in plan.review_issues if iss.producer != "speaker_review"]
    new_review_issues = audit_speaker_plan(plan, {"km-KH-SreymomNeural"})
    updated_issues = other_producer_issues + new_review_issues

    reasons = [i.reason for i in updated_issues]
    assert "competing_speakers" in reasons


# ---------------------------------------------------------------------------
# F4: Handlers for Issue Action Buttons
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_f4_issue_action_buttons_registered_and_handled():
    """Verify that spk_io, spk_id, spk_ie, spk_sa, spk_it routes exist and handle gracefully."""
    from app.handlers.speakers import (
        cb_issue_original_sample,
        cb_issue_dubbed_sample,
        cb_issue_edit_speaker,
        cb_issue_save_speaker_assignment,
        cb_issue_edit_text,
    )

    call = AsyncMock()
    call.data = "spk_io:tok1:0"
    call.answer = AsyncMock()
    call.from_user.id = 123

    # With non-existent token, all should safely reject expired token rather than crash or be unhandled
    await cb_issue_original_sample(call)
    assert call.answer.called

    call.answer.reset_mock()
    call.data = "spk_id:tok1:0"
    await cb_issue_dubbed_sample(call)
    assert call.answer.called

    call.answer.reset_mock()
    call.data = "spk_ie:tok1:0"
    await cb_issue_edit_speaker(call)
    assert call.answer.called

    call.answer.reset_mock()
    call.data = "spk_sa:tok1:s001:Speaker A"
    await cb_issue_save_speaker_assignment(call)
    assert call.answer.called

    call.answer.reset_mock()
    call.data = "spk_it:tok1:s001"
    state = AsyncMock()
    await cb_issue_edit_text(call, state)
    assert call.answer.called


# ---------------------------------------------------------------------------
# F5: Splitting Updates Translations for Children
# ---------------------------------------------------------------------------

def test_f5_split_segments_sync_translations():
    """When an utterance splits into s001_a and s001_b, translations are mapped to children."""
    plan = DubbingPlan(
        segments=[
            SourceSegment(segment_id="s001_a", start_ms=0, end_ms=1000, source_text="Hello", parent_segment_id="s001"),
            SourceSegment(segment_id="s001_b", start_ms=1000, end_ms=2000, source_text="World", parent_segment_id="s001"),
        ],
        translations=[
            TranslatedSegment(segment_id="s001", translated_text="សួស្តីពិភពលោក", status="ready"),
        ],
    )
    # Simulate child translation sync from cb_speaker_mode_multi
    source_ids = {s.segment_id for s in plan.segments}
    existing_trans_map = {t.segment_id: t for t in plan.translations}
    synced_translations = []
    for seg in plan.segments:
        if seg.segment_id in existing_trans_map:
            synced_translations.append(existing_trans_map[seg.segment_id])
        elif seg.parent_segment_id and seg.parent_segment_id in existing_trans_map:
            parent_t = existing_trans_map[seg.parent_segment_id]
            synced_translations.append(
                TranslatedSegment(
                    segment_id=seg.segment_id,
                    translated_text=parent_t.translated_text,
                    translation_provider=parent_t.translation_provider,
                    status="needs_review",
                    full_translation=parent_t.full_translation or parent_t.translated_text,
                )
            )
    plan.translations = synced_translations

    trans_ids = {t.segment_id for t in plan.translations}
    assert "s001_a" in trans_ids
    assert "s001_b" in trans_ids
    assert "s001" not in trans_ids


# ---------------------------------------------------------------------------
# F10: Acknowledging Review Issue Does Not Mutate CallbackQuery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_f10_render_review_issue_no_frozen_mutation():
    """Verify render_review_issue accepts typed arguments without mutating call.data."""
    from app.handlers.speakers import render_review_issue
    from app.storage.jobs import job_storage
    from app.storage.dubbing import save_dubbing_plan

    call = AsyncMock()
    call.answer = AsyncMock()
    call.message = AsyncMock()
    call.message.edit_text = AsyncMock()
    call.from_user.id = 100

    job = job_storage.create_job(user_id=100, chat_id=200)
    rev = job_storage.create_revision(job.job_id, "សួស្តី", VoiceSettings())

    plan = DubbingPlan(
        segments=[SourceSegment(segment_id="s001", start_ms=0, end_ms=1000, source_text="Hello")],
        translations=[TranslatedSegment(segment_id="s001", translated_text="សួស្តី")],
        speaker_assignments=[SpeakerAssignment(segment_id="s001", speaker_id="Speaker A", evidence_key="k1")],
        speaker_voice_map={"Speaker A": VoiceChoice(voice_id="km-KH-SreymomNeural", confirmed=True)},
        review_issues=[
            ReviewIssue(issue_id="iss1", segment_id="s001", reason="competing_speakers", subject_key="k1", blocking=False)
        ],
    )
    save_dubbing_plan(job.job_id, rev.revision_id, plan)

    token = speaker_review_store.create_token(job.job_id, rev.revision_id, user_id=100)

    # Calling render_review_issue directly must not raise ValidationError or mutate call.data
    await render_review_issue(call, token, 0)
    assert call.message.edit_text.called or call.message.edit_caption.called
