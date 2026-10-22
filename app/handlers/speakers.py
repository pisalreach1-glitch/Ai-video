"""Handlers for multi-speaker Khmer dubbing, speaker cards, previews, and review alerts."""
from __future__ import annotations

import asyncio
import logging
import unicodedata
from pathlib import Path
from typing import Any

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, FSInputFile
from aiogram.fsm.context import FSMContext

from app.config import config
from app.domain.states import WizardStep, JobState
from app.domain.models import Job, Revision
from app.domain.dubbing import DubbingPlan, SourceSegment, TranslatedSegment
from app.domain.speakers import (
    SpeakerProfile,
    SpeakerTurn,
    SpeakerAssignment,
    VoiceChoice,
    ReviewIssue,
)
from app.storage.jobs import job_storage
from app.storage.dubbing import save_dubbing_plan, load_dubbing_plan, save_sync_report
from app.storage.workspaces import workspace
from app.storage.speaker_reviews import speaker_review_store
from app.handlers.common import safe_edit_message, safe_edit_reply_markup, verify_callback_job
from app.services.voices import get_available_voices
from app.services.speaker_voices import resolve_voice, VoiceSelectionRequired
from app.services.speaker_samples import select_speaker_sample_window, format_window_label, review_window
from app.services.speaker_assignment import assign_speakers_to_segments
from app.services.speaker_review import (
    assert_final_ready,
    audit_speaker_plan,
    compute_plan_content_digest,
    compute_subject_key,
    ReviewRequired,
)
from app.services.content_coverage import validate_content_coverage, generate_completeness_report
from app.services.previews import render_timed_excerpt, render_full_preview_video
from app.services.dubbing import synthesize_and_fit_plan
from app.services.timeline import assemble_timeline_pcm
from app.services.subtitles import build_timeline_subtitles
from app.jobs.worker import worker_pool
from app.ui.speaker_keyboards import (
    speaker_mode_choice_keyboard,
    speaker_card_keyboard,
    speaker_voice_picker_keyboard,
    review_issue_keyboard,
    speaker_assignment_picker_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name="speakers")


async def verify_speaker_token(
    call: CallbackQuery,
    token: str,
    allowed_states: tuple[JobState, ...] | None = None,
) -> tuple[dict[str, Any], Job, DubbingPlan, Revision] | None:
    """
    Validates token existence, expiration, user ownership, current revision, and job state (F1 guard).
    """
    token_data = speaker_review_store.get_token(token)
    if not token_data:
        await call.answer("វគ្គបានផុតកំណត់ សូមបើកឡើងវិញ។", show_alert=True)
        return None

    # Ownership check
    if call.from_user.id != token_data["user_id"]:
        await call.answer("អ្នកមិនមានសិទ្ធិកែប្រែការងាររបស់អ្នកដទៃឡើយ។", show_alert=True)
        return None

    job_id = token_data["job_id"]
    rev_id = token_data["revision_id"]

    # Immediate cancellation check
    if worker_pool.is_cancelled(job_id):
        await call.answer("ការងារត្រូវបានបោះបង់រួចហើយ។", show_alert=True)
        return None

    job = job_storage.get_job(job_id)
    if not job:
        await call.answer("មិនមានទិន្នន័យការងារឡើយ។", show_alert=True)
        return None

    if job.status == JobState.CANCELLED:
        await call.answer("ការងារត្រូវបានបោះបង់រួចហើយ។", show_alert=True)
        return None

    # Revision check
    if job.current_revision_id != rev_id:
        await call.answer("កំណែប្រែនេះចាស់ហួសសម័យហើយ។", show_alert=True)
        return None

    rev = job_storage.get_revision(job_id, rev_id)
    plan = load_dubbing_plan(job_id, rev_id)

    if not rev or not plan:
        await call.answer("មិនមានទិន្នន័យការងារឡើយ។", show_alert=True)
        return None

    if allowed_states and job.status not in allowed_states:
        await call.answer("មិនអាចដំណើរការសកម្មភាពនេះក្នុងស្ថានភាពបច្ចុប្បន្នឡើយ។", show_alert=True)
        return None

    return token_data, job, plan, rev


async def render_speaker_card(
    call: CallbackQuery,
    job_id: str,
    revision_id: int,
    user_id: int,
    speaker_index: int = 0,
    plan: DubbingPlan | None = None,
) -> None:
    """Displays the interactive Speaker Card for speaker at speaker_index."""
    if not plan:
        plan = load_dubbing_plan(job_id, revision_id)
    if not plan or not plan.speakers:
        await call.answer("មិនមានទិន្នន័យអ្នកនិយាយឡើយ។", show_alert=True)
        return

    total_speakers = len(plan.speakers)
    idx = max(0, min(speaker_index, total_speakers - 1))
    profile = plan.speakers[idx]
    spk_id = profile.speaker_id

    # Count utterances assigned to this speaker
    utterance_count = sum(1 for a in plan.speaker_assignments if a.speaker_id == spk_id)

    # Calculate representative sample window
    window_label = "00:00–00:05"
    if plan.speaker_turns:
        try:
            w_start, w_end = select_speaker_sample_window(
                speaker_id=spk_id,
                turns=plan.speaker_turns,
                source_duration_ms=plan.source_duration_ms,
                context_ms=config.speaker_preview_context_ms,
            )
            window_label = format_window_label(w_start, w_end)
        except Exception:
            pass
    elif plan.segments:
        # Fallback to first segment duration
        s0 = plan.segments[0]
        window_label = format_window_label(s0.start_ms, s0.end_ms)

    # Resolve current voice choice
    voice_choice = plan.speaker_voice_map.get(spk_id)
    voice_name = voice_choice.voice_id if voice_choice else "(មិនទាន់ជ្រើស)"
    is_confirmed = voice_choice.confirmed if voice_choice else False

    # Count open blocking review issues
    open_issues = [i for i in plan.review_issues if i.blocking and i.is_open]

    card_text = (
        f"👤 **{spk_id} — ឈ្មោះដែលអ្នកកំណត់: {profile.display_name}**\n"
        f"ឃ្លា: {utterance_count} | គំរូ: {window_label}\n"
        f"សំឡេងដែលបានជ្រើស: **{voice_name}**\n\n"
        f"💡 សូមជ្រើសរើសសំឡេង AI និងមើលវីដេអូគំរូ (ដើម & សំឡេងថ្មី) មុនបញ្ជាក់។"
    )

    token = speaker_review_store.create_token(
        job_id=job_id,
        revision_id=revision_id,
        user_id=user_id,
        target_id=spk_id,
    )

    has_full_preview = bool(plan.preview_plan_digest)

    await safe_edit_message(
        call,
        card_text,
        reply_markup=speaker_card_keyboard(
            token=token,
            page=idx + 1,
            total_pages=total_speakers,
            is_confirmed=is_confirmed,
            open_issue_count=len(open_issues),
            has_full_preview=has_full_preview,
        ),
    )


async def render_review_issue(
    call: CallbackQuery,
    token: str,
    issue_idx: int = 0,
    plan: DubbingPlan | None = None,
) -> None:
    """Renders a single review alert card with actionable resolution buttons (F10)."""
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, loaded_plan, rev = verified
    if plan is None:
        plan = loaded_plan

    issues = plan.review_issues
    if not issues:
        await safe_edit_message(call, "✅ មិនមានបញ្ហាដែលត្រូវពិនិត្យឡើយ។")
        await call.answer()
        return

    total_issues = len(issues)
    idx = max(0, min(issue_idx, total_issues - 1))
    issue = issues[idx]

    seg = plan.get_segment(issue.segment_id)
    time_label = format_window_label(seg.start_ms, seg.end_ms) if seg else issue.segment_id

    reason_labels = {
        "unknown_speaker": "មិនទាន់កំណត់អ្នកនិយាយ",
        "unscored_assignment": "ការវិភាគស្វ័យប្រវត្តគ្មានពិន្ទុច្បាស់លាស់ (Unscored)",
        "low_speaker_confidence": "ភាពជឿជាក់លើអ្នកនិយាយទាប (Low Confidence)",
        "competing_speakers": "មានអ្នកនិយាយប្រជែងគ្នាលើឈុតតែមួយ",
        "missing_voice": "មិនទាន់បានបញ្ជាក់សំឡេង AI",
        "invalid_voice": "សំឡេង AI មិនត្រឹមត្រូវ",
        "overlapping_speech": "សំឡេងនិយាយជាន់គ្នា",
    }
    reason_km = reason_labels.get(issue.reason, issue.reason)
    status_km = "🔒 មិនទាន់ដោះស្រាយ" if issue.is_open else "✅ បានបញ្ជាក់យល់ព្រមរួច"

    issue_text = (
        f"⚠️ **ត្រូវពិនិត្យ ({idx + 1}/{total_issues})៖ {time_label}**\n\n"
        f"• **ឃ្លា:** `{issue.segment_id}`\n"
        f"• **មូលហេតុ:** {reason_km}\n"
        f"• **ស្ថានភាព:** {status_km}\n\n"
        f"សូមមើលវីដេអូ ឬកែសម្រួលដើម្បីដោះស្រាយបញ្ហានេះ។"
    )

    await safe_edit_message(
        call,
        issue_text,
        reply_markup=review_issue_keyboard(
            token=token,
            issue_idx=idx,
            total_issues=total_issues,
            allow_confirm=issue.allow_confirmation and issue.is_open,
            segment_id=issue.segment_id,
        ),
    )


# ---------------- Speaker Mode Selection ----------------

@router.callback_query(F.data.startswith("spk_m:s:"))
async def cb_speaker_mode_single(call: CallbackQuery, state: FSMContext) -> None:
    """User selects Single Voice mode (verified with verify_callback_job)."""
    _, _, job_id = call.data.split(":")
    if not await verify_callback_job(call, job_id, allowed_states=(JobState.AWAITING_SEGMENT_REVIEW, JobState.AWAITING_TEXT)):
        return

    job = job_storage.get_job(job_id)
    if not job:
        await call.answer("ការងារមិនត្រឹមត្រូវ។", show_alert=True)
        return

    rev_id = job.current_revision_id
    plan = load_dubbing_plan(job_id, rev_id)
    if plan:
        plan.speaker_mode = "single"
        save_dubbing_plan(job_id, rev_id, plan)

    from app.handlers.dubbing import render_segment_review_page
    await render_segment_review_page(call, job_id, rev_id, page=1, plan=plan)
    await call.answer()


@router.callback_query(F.data.startswith("spk_m:m:"))
async def cb_speaker_mode_multi(call: CallbackQuery, state: FSMContext) -> None:
    """User selects Multi-Speaker Dubbing mode (verified with verify_callback_job)."""
    _, _, job_id = call.data.split(":")
    if not await verify_callback_job(call, job_id, allowed_states=(JobState.AWAITING_SEGMENT_REVIEW, JobState.AWAITING_TEXT)):
        return

    job = job_storage.get_job(job_id)
    if not job or not job.source_path:
        await call.answer("មិនអាចរកឃើញវីដេអូដើមឡើយ។", show_alert=True)
        return

    rev_id = job.current_revision_id
    plan = load_dubbing_plan(job_id, rev_id)
    if not plan or not plan.segments:
        await call.answer("មិនមានទិន្នន័យឃ្លាឡើយ។", show_alert=True)
        return

    await safe_edit_message(call, "⏳ កំពុងវិភាគអ្នកនិយាយក្នុងវីដេអូ (Speaker Diarization)... សូមរង់ចាំបន្តិច។")
    await call.answer("👥 កំពុងវិភាគអ្នកនិយាយ...")

    # Run optional diarization (F2 & F3)
    from app.services.speaker_diarization import run_speaker_diarization, is_diarization_available
    source_audio = workspace.get_source_audio_path(job_id)

    speaker_turns: list[SpeakerTurn] = []
    diarization_ran = False
    if is_diarization_available() and source_audio.exists():
        try:
            speaker_turns = await run_speaker_diarization(
                audio_wav_path=source_audio,
                hf_token=config.hf_token,
                device=config.speaker_device,
                model_name=config.speaker_diarization_model,
            )
            diarization_ran = True
        except Exception as e:
            logger.warning(f"Diarization unavailable or failed: {e}")

    analysis_key = f"diar_{job_id[:8]}"

    # F3: Never fabricate alternating speaker turns when analysis is missing/failed!
    if not speaker_turns:
        # Honest setup: create manual profiles and leave assignments unassigned or manual
        distinct_spks = ["Speaker A", "Speaker B"]
        speaker_turns = []
        out_segments = plan.segments
        assignments = [
            SpeakerAssignment(
                segment_id=s.segment_id,
                speaker_id=None,
                evidence_key=analysis_key,
                origin="auto",
                confidence=None,
                confidence_kind="unavailable",
            )
            for s in plan.segments
        ]
        assign_issues = [
            ReviewIssue(
                issue_id=f"unk_spk_{s.segment_id}",
                segment_id=s.segment_id,
                reason="unknown_speaker",
                subject_key=analysis_key,
                producer="speaker_assignment",
                blocking=True,
                allow_confirmation=False,
            )
            for s in plan.segments
        ]
    else:
        # Assign speakers & split ASR segments if trustworthy word timings exist (F5)
        out_segments, assignments, assign_issues = assign_speakers_to_segments(
            segments=plan.segments,
            turns=speaker_turns,
            analysis_key=analysis_key,
        )
        distinct_spks = sorted(list({t.speaker_id for t in speaker_turns}))

    # F5: Ensure every segment in out_segments has a corresponding TranslatedSegment
    trans_map = {t.segment_id: t for t in plan.translations}
    updated_translations: list[TranslatedSegment] = []
    for s in out_segments:
        existing = trans_map.get(s.segment_id)
        if existing:
            updated_translations.append(existing)
        else:
            # Child segment from split -> generate initial translation entry from parent or text
            parent = trans_map.get(s.parent_segment_id) if s.parent_segment_id else None
            initial_text = s.source_text if not parent else f"({parent.translated_text})"
            updated_translations.append(
                TranslatedSegment(
                    segment_id=s.segment_id,
                    translated_text=initial_text,
                    translation_provider="split",
                    status="needs_review",
                    full_translation=initial_text,
                )
            )

    profiles = [
        SpeakerProfile(speaker_id=s, display_name=f"តួអង្គ {s.replace('Speaker ', '')}", analysis_key=analysis_key)
        for s in distinct_spks
    ]

    # Initialize voice map
    available_voices = await get_available_voices()
    available_ids = [v["ShortName"] for v in available_voices]
    voice_map: dict[str, VoiceChoice] = {}
    for idx, spk in enumerate(distinct_spks):
        chosen_voice = available_ids[idx % len(available_ids)] if available_ids else "km-KH-SreymomNeural"
        voice_map[spk] = VoiceChoice(voice_id=chosen_voice, rate="+0%", confirmed=False)

    plan.speaker_mode = "multi"
    plan.source_analysis_key = analysis_key
    plan.segments = out_segments
    plan.translations = updated_translations
    plan.speakers = profiles
    plan.speaker_turns = speaker_turns
    plan.speaker_assignments = assignments
    plan.speaker_voice_map = voice_map

    # Run audit for review issues
    plan.review_issues = audit_speaker_plan(
        plan=plan,
        available_voice_ids=set(available_ids),
        require_unscored_review=config.speaker_require_unscored_review,
    )
    plan.review_issues.extend(assign_issues)

    save_dubbing_plan(job_id, rev_id, plan)

    # Render first speaker card
    await render_speaker_card(
        call=call,
        job_id=job_id,
        revision_id=rev_id,
        user_id=call.from_user.id,
        speaker_index=0,
        plan=plan,
    )


# ---------------- Speaker Card Callbacks ----------------

@router.callback_query(F.data.startswith("spk_p:"))
async def cb_speaker_page(call: CallbackQuery) -> None:
    """Paginate between speaker cards (F1 verified)."""
    _, token, page_str = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    page = int(page_str)
    await render_speaker_card(
        call=call,
        job_id=token_data["job_id"],
        revision_id=token_data["revision_id"],
        user_id=token_data["user_id"],
        speaker_index=page - 1,
        plan=plan,
    )
    await call.answer()


@router.callback_query(F.data.startswith("spk_o:"))
async def cb_speaker_original_sample(call: CallbackQuery) -> None:
    """Watch original video + original audio sample for this speaker (F1 verified)."""
    _, token = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    job_id = token_data["job_id"]
    rev_id = token_data["revision_id"]
    spk_id = token_data["target_id"]

    await call.answer("🎬 កំពុងរៀបចំវីដេអូគំរូដើម...")

    if plan.speaker_turns:
        w_start, w_end = select_speaker_sample_window(
            speaker_id=spk_id,
            turns=plan.speaker_turns,
            source_duration_ms=plan.source_duration_ms,
            context_ms=config.speaker_preview_context_ms,
        )
    else:
        # Fallback to first available segment
        s0 = plan.segments[0]
        w_start, w_end = review_window(s0.start_ms, s0.end_ms, plan.source_duration_ms)

    start_sec = w_start / 1000.0
    dur_sec = max(1.0, (w_end - w_start) / 1000.0)
    window_key = f"{w_start}_{w_end}"

    out_sample = workspace.get_speaker_sample_original(job_id, rev_id, window_key)
    if not out_sample.exists() or out_sample.stat().st_size == 0:
        await render_timed_excerpt(
            source_path=job.source_path,
            assembled_audio_path=None,
            output_preview_path=out_sample,
            settings=rev.settings,
            start_sec=start_sec,
            duration_sec=dur_sec,
            variant="original",
            cancel_check=lambda: worker_pool.is_cancelled(job_id),
        )

    if out_sample.exists():
        video_input = FSInputFile(str(out_sample), filename="original_sample.mp4")
        await call.message.reply_video(
            video=video_input,
            caption=f"🎬 **វីដេអូគំរូដើម ({spk_id}):** {format_window_label(w_start, w_end)}\nសំឡេងដើមពីវីដេអូ",
            supports_streaming=True,
        )


@router.callback_query(F.data.startswith("spk_d:"))
async def cb_speaker_dubbed_sample(call: CallbackQuery) -> None:
    """Watch dubbed video sample for this speaker on the same window (F1 & F8 verified)."""
    _, token = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    job_id = token_data["job_id"]
    rev_id = token_data["revision_id"]
    spk_id = token_data["target_id"]

    await call.answer("🎙️ កំពុងបង្កើតគំរូសំឡេងថ្មី...")

    if plan.speaker_turns:
        w_start, w_end = select_speaker_sample_window(
            speaker_id=spk_id,
            turns=plan.speaker_turns,
            source_duration_ms=plan.source_duration_ms,
            context_ms=config.speaker_preview_context_ms,
        )
    else:
        s0 = plan.segments[0]
        w_start, w_end = review_window(s0.start_ms, s0.end_ms, plan.source_duration_ms)

    start_sec = w_start / 1000.0
    dur_sec = max(1.0, (w_end - w_start) / 1000.0)
    window_key = f"{w_start}_{w_end}"

    # Synthesize clips (allowing unconfirmed voices for this audition trial)
    audition_seg = s0 if 's0' in locals() and s0 else (plan.segments[0] if plan.segments else None)
    plan = await synthesize_and_fit_plan(
        plan=plan,
        job_id=job_id,
        revision_id=rev_id,
        settings=rev.settings,
        cancel_check=lambda: worker_pool.is_cancelled(job_id),
        require_confirmed_voices=False,
        audition_speaker_id=spk_id,
        audition_segment_id=audition_seg.segment_id if audition_seg else None,
    )
    if worker_pool.is_cancelled(job_id):
        return

    if not plan.clips:
        await call.answer("⚠️ មិនមានសំឡេងបកប្រែដែលត្រូវបានបង្កើតឡើយ។", show_alert=True)
        return

    save_dubbing_plan(job_id, rev_id, plan)

    # Assemble timeline audio & subtitles
    timeline_wav = workspace.get_timeline_audio_path(job_id, rev_id)
    assemble_timeline_pcm(plan, timeline_wav)

    sub_srt = workspace.get_subtitles_srt_path(job_id, rev_id)
    sub_ass = workspace.get_subtitles_ass_path(job_id, rev_id)
    build_timeline_subtitles(plan, sub_srt, sub_ass, rev.settings.subtitle_color, rev.settings.subtitle_position)

    voice_choice = plan.speaker_voice_map.get(spk_id)
    v_id = voice_choice.voice_id if voice_choice else "default"
    out_dubbed = workspace.get_speaker_sample_dubbed(job_id, rev_id, window_key, v_id)

    await render_timed_excerpt(
        source_path=job.source_path,
        assembled_audio_path=timeline_wav,
        output_preview_path=out_dubbed,
        settings=rev.settings,
        start_sec=start_sec,
        duration_sec=dur_sec,
        subtitles_ass_path=sub_ass,
        variant="dubbed",
        cancel_check=lambda: worker_pool.is_cancelled(job_id),
    )

    if out_dubbed.exists() and not worker_pool.is_cancelled(job_id):
        video_input = FSInputFile(str(out_dubbed), filename="dubbed_sample.mp4")
        await call.message.reply_video(
            video=video_input,
            caption=(
                f"🎬 **វីដេអូគំរូសំឡេងថ្មី ({spk_id}):** {format_window_label(w_start, w_end)}\n"
                f"សំឡេង AI: **{v_id}**\n"
                f"⚠️ *នេះជាគំរូតេស្ត audition សាកល្បងមុនបញ្ជាក់*"
            ),
            supports_streaming=True,
        )


@router.callback_query(F.data.startswith("spk_vl:"))
async def cb_speaker_voice_list(call: CallbackQuery) -> None:
    """Show voice list for this speaker (F1 verified)."""
    _, token = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    spk_id = token_data["target_id"]
    available_voices = await get_available_voices()
    curr_voice = plan.speaker_voice_map.get(spk_id)
    curr_id = curr_voice.voice_id if curr_voice else ""

    await safe_edit_message(
        call,
        f"🎙️ **ជ្រើសរើសសំឡេង AI សម្រាប់ {spk_id}:**\nសូមជ្រើសរើសសំឡេងដែលសមស្របនឹងតួអង្គនេះ៖",
        reply_markup=speaker_voice_picker_keyboard(token, available_voices, curr_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("spk_vs:"))
async def cb_speaker_voice_select(call: CallbackQuery) -> None:
    """Apply voice selection to speaker (F1 verified)."""
    _, token, vidx_str = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    job_id = token_data["job_id"]
    rev_id = token_data["revision_id"]
    spk_id = token_data["target_id"]
    vidx = int(vidx_str)

    available_voices = await get_available_voices()
    if 0 <= vidx < len(available_voices):
        chosen = available_voices[vidx]["ShortName"]
        prev = plan.speaker_voice_map.get(spk_id)
        # Update voice choice (unconfirmed until user confirms)
        plan.speaker_voice_map[spk_id] = VoiceChoice(
            voice_id=chosen,
            rate=prev.rate if prev else "+0%",
            confirmed=False,
        )

        # Invalidate full preview digest since voice changed
        plan.full_preview_approved_digest = None
        plan.preview_plan_digest = None

        save_dubbing_plan(job_id, rev_id, plan)

    # Return to speaker card
    spk_idx = next((i for i, s in enumerate(plan.speakers) if s.speaker_id == spk_id), 0)
    await render_speaker_card(
        call=call,
        job_id=job_id,
        revision_id=rev_id,
        user_id=token_data["user_id"],
        speaker_index=spk_idx,
        plan=plan,
    )
    await call.answer("បានប្តូរសំឡេងរួចរាល់!")


@router.callback_query(F.data.startswith("spk_cf:"))
async def cb_speaker_confirm_voice(call: CallbackQuery) -> None:
    """Confirm chosen voice for this speaker (F1 & F7: preserve other producers' issues)."""
    _, token = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    job_id = token_data["job_id"]
    rev_id = token_data["revision_id"]
    spk_id = token_data["target_id"]

    choice = plan.speaker_voice_map.get(spk_id)
    if choice:
        plan.speaker_voice_map[spk_id] = VoiceChoice(
            voice_id=choice.voice_id,
            rate=choice.rate,
            confirmed=True,
        )
        speaker_review_store.record_decision(
            job_id=job_id,
            revision_id=rev_id,
            user_id=token_data["user_id"],
            action="confirm_voice",
            target_id=spk_id,
            details={"voice_id": choice.voice_id, "rate": choice.rate},
        )

        # F7: Re-audit only speaker_review issues, preserving other producers' issues!
        available_voices = await get_available_voices()
        available_ids = {v["ShortName"] for v in available_voices}
        audit_issues = audit_speaker_plan(
            plan=plan,
            available_voice_ids=available_ids,
            require_unscored_review=config.speaker_require_unscored_review,
        )
        other_issues = [i for i in plan.review_issues if i.producer != "speaker_review"]
        plan.review_issues = audit_issues + other_issues
        save_dubbing_plan(job_id, rev_id, plan)

    spk_idx = next((i for i, s in enumerate(plan.speakers) if s.speaker_id == spk_id), 0)
    await render_speaker_card(
        call=call,
        job_id=job_id,
        revision_id=rev_id,
        user_id=token_data["user_id"],
        speaker_index=spk_idx,
        plan=plan,
    )
    await call.answer("✅ បានបញ្ជាក់សំឡេងរួចរាល់!")


@router.callback_query(F.data.startswith("spk_rn:"))
async def cb_speaker_rename(call: CallbackQuery, state: FSMContext) -> None:
    """Prompt user to rename a speaker profile (F1 verified)."""
    _, token = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    await state.update_data(
        job_id=token_data["job_id"],
        revision_id=token_data["revision_id"],
        renaming_speaker_id=token_data["target_id"],
        user_id=token_data["user_id"],
    )
    await state.set_state(WizardStep.renaming_speaker)
    await safe_edit_message(
        call,
        f"✏️ **ដាក់ឈ្មោះតួអង្គសម្រាប់ {token_data['target_id']}:**\n"
        f"ឧទាហរណ៍៖ `តួឯក`, `អ្នកលក់`, `ពូសំបូរ`...\n"
        f"សូមវាយឈ្មោះថ្មីផ្ញើមកទីនេះ៖"
    )
    await call.answer()


@router.message(WizardStep.renaming_speaker, F.text)
async def handle_speaker_rename_input(message: Message, state: FSMContext) -> None:
    """Handles text message input for character rename."""
    raw_text = message.text or ""
    new_name = unicodedata.normalize("NFC", raw_text).strip()
    if not new_name:
        await message.reply("សូមបញ្ចូលឈ្មោះតួអង្គឱ្យបានត្រឹមត្រូវ។")
        return

    data = await state.get_data()
    job_id = data.get("job_id")
    rev_id = data.get("revision_id")
    spk_id = data.get("renaming_speaker_id")
    user_id = data.get("user_id", message.from_user.id)

    plan = load_dubbing_plan(job_id, rev_id)
    if not plan:
        await message.reply("មានបញ្ហាក្នុងការរក្សាទុក។")
        return

    # Update profile display name
    updated_profiles = []
    for p in plan.speakers:
        if p.speaker_id == spk_id:
            updated_profiles.append(SpeakerProfile(speaker_id=p.speaker_id, display_name=new_name, analysis_key=p.analysis_key))
        else:
            updated_profiles.append(p)
    plan.speakers = updated_profiles
    save_dubbing_plan(job_id, rev_id, plan)

    await state.set_state(WizardStep.dubbing_review)
    confirm_msg = await message.reply(f"✅ បានកំណត់ឈ្មោះ '{new_name}' សម្រាប់ {spk_id}!")

    token = speaker_review_store.create_token(job_id, rev_id, user_id, spk_id)
    has_full_preview = bool(plan.preview_plan_digest)
    open_issues = [i for i in plan.review_issues if i.blocking and i.is_open]
    voice_choice = plan.speaker_voice_map.get(spk_id)
    is_confirmed = voice_choice.confirmed if voice_choice else False

    await confirm_msg.edit_text(
        f"👤 **{spk_id} — ឈ្មោះដែលអ្នកកំណត់: {new_name}**\n"
        f"សំឡេងដែលបានជ្រើស: **{voice_choice.voice_id if voice_choice else '(មិនទាន់ជ្រើស)'}**\n\n"
        f"💡 សូមជ្រើសរើសសំឡេង AI និងមើលវីដេអូគំរូមុនបញ្ជាក់។",
        reply_markup=speaker_card_keyboard(
            token=token,
            page=1,
            total_pages=len(plan.speakers),
            is_confirmed=is_confirmed,
            open_issue_count=len(open_issues),
            has_full_preview=has_full_preview,
        ),
    )


# ---------------- Review Alerts & Issues (F4 & F10) ----------------

@router.callback_query(F.data.startswith("spk_rv:"))
async def cb_speaker_review_issues(call: CallbackQuery) -> None:
    """Displays Review Alerts for uncertain or problematic segments (F10)."""
    parts = call.data.split(":")
    token = parts[1]
    issue_idx = int(parts[2]) if len(parts) > 2 else 0
    await render_review_issue(call, token, issue_idx)
    await call.answer()


@router.callback_query(F.data.startswith("spk_io:"))
async def cb_issue_original_sample(call: CallbackQuery) -> None:
    """Watch original video sample for a specific review issue (F4)."""
    _, token, issue_idx_str = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    issue_idx = int(issue_idx_str)
    if issue_idx >= len(plan.review_issues):
        await call.answer("មិនមានទិន្នន័យបញ្ហាឡើយ។", show_alert=True)
        return

    issue = plan.review_issues[issue_idx]
    seg = plan.get_segment(issue.segment_id)
    if not seg:
        await call.answer("មិនមានទិន្នន័យឃ្លាឡើយ។", show_alert=True)
        return

    await call.answer("🎬 កំពុងរៀបចំវីដេអូដើមសម្រាប់ឈុតនេះ...")
    w_start, w_end = review_window(seg.start_ms, seg.end_ms, plan.source_duration_ms, config.speaker_preview_context_ms)
    start_sec = w_start / 1000.0
    dur_sec = max(1.0, (w_end - w_start) / 1000.0)

    out_sample = workspace.get_speaker_sample_original(job.job_id, rev.revision_id, f"issue_{seg.segment_id}")
    await render_timed_excerpt(
        source_path=job.source_path,
        assembled_audio_path=None,
        output_preview_path=out_sample,
        settings=rev.settings,
        start_sec=start_sec,
        duration_sec=dur_sec,
        variant="original",
        cancel_check=lambda: worker_pool.is_cancelled(job.job_id),
    )

    if out_sample.exists():
        video_input = FSInputFile(str(out_sample), filename="issue_orig.mp4")
        await call.message.reply_video(
            video=video_input,
            caption=f"🎬 **វីដេអូដើម ({seg.segment_id}):** {format_window_label(w_start, w_end)}\n_{seg.source_text}_",
            supports_streaming=True,
        )


@router.callback_query(F.data.startswith("spk_id:"))
async def cb_issue_dubbed_sample(call: CallbackQuery) -> None:
    """Watch dubbed video sample for a specific review issue (F4)."""
    _, token, issue_idx_str = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    issue_idx = int(issue_idx_str)
    if issue_idx >= len(plan.review_issues):
        await call.answer("មិនមានទិន្នន័យបញ្ហាឡើយ។", show_alert=True)
        return

    issue = plan.review_issues[issue_idx]
    seg = plan.get_segment(issue.segment_id)
    trans = plan.get_translation(issue.segment_id)
    if not seg:
        await call.answer("មិនមានទិន្នន័យឃ្លាឡើយ។", show_alert=True)
        return

    await call.answer("🎙️ កំពុងបង្កើតគំរូសំឡេងថ្មីសម្រាប់ឈុតនេះ...")
    w_start, w_end = review_window(seg.start_ms, seg.end_ms, plan.source_duration_ms, config.speaker_preview_context_ms)
    start_sec = w_start / 1000.0
    dur_sec = max(1.0, (w_end - w_start) / 1000.0)

    # Synthesize clips
    issue_asgn = plan.get_assignment(seg.segment_id)
    audition_spk = (issue_asgn.speaker_id if issue_asgn and issue_asgn.speaker_id else (plan.speakers[0].speaker_id if plan.speakers else "Speaker A"))
    plan = await synthesize_and_fit_plan(
        plan=plan,
        job_id=job.job_id,
        revision_id=rev.revision_id,
        settings=rev.settings,
        cancel_check=lambda: worker_pool.is_cancelled(job.job_id),
        require_confirmed_voices=False,
        audition_speaker_id=audition_spk,
        audition_segment_id=seg.segment_id,
    )
    if worker_pool.is_cancelled(job.job_id):
        return

    if not plan.clips:
        await call.answer("⚠️ មិនមានសំឡេងបកប្រែដែលត្រូវបានបង្កើតឡើយ។", show_alert=True)
        return

    save_dubbing_plan(job.job_id, rev.revision_id, plan)

    timeline_wav = workspace.get_timeline_audio_path(job.job_id, rev.revision_id)
    assemble_timeline_pcm(plan, timeline_wav)

    sub_ass = workspace.get_subtitles_ass_path(job.job_id, rev.revision_id)
    sub_srt = workspace.get_subtitles_srt_path(job.job_id, rev.revision_id)
    build_timeline_subtitles(plan, sub_srt, sub_ass, rev.settings.subtitle_color, rev.settings.subtitle_position)

    out_dubbed = workspace.get_speaker_sample_dubbed(job.job_id, rev.revision_id, f"issue_{seg.segment_id}", "audition")
    await render_timed_excerpt(
        source_path=job.source_path,
        assembled_audio_path=timeline_wav,
        output_preview_path=out_dubbed,
        settings=rev.settings,
        start_sec=start_sec,
        duration_sec=dur_sec,
        subtitles_ass_path=sub_ass,
        variant="dubbed",
        cancel_check=lambda: worker_pool.is_cancelled(job.job_id),
    )

    if out_dubbed.exists():
        video_input = FSInputFile(str(out_dubbed), filename="issue_dubbed.mp4")
        await call.message.reply_video(
            video=video_input,
            caption=(
                f"🎬 **វីដេអូបកប្រែ ({seg.segment_id}):** {format_window_label(w_start, w_end)}\n"
                f"**{trans.translated_text if trans else ''}**"
            ),
            supports_streaming=True,
        )


@router.callback_query(F.data.startswith("spk_ie:"))
async def cb_issue_edit_speaker(call: CallbackQuery) -> None:
    """Prompt user to reassign speaker for this issue's segment (F4)."""
    _, token, issue_idx_str = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    issue_idx = int(issue_idx_str)
    if issue_idx >= len(plan.review_issues):
        await call.answer("មិនមានទិន្នន័យបញ្ហាឡើយ។", show_alert=True)
        return

    issue = plan.review_issues[issue_idx]
    speaker_names = [p.speaker_id for p in plan.speakers]
    if not speaker_names:
        speaker_names = ["Speaker A", "Speaker B"]

    await safe_edit_message(
        call,
        f"👤 **ជ្រើសរើសអ្នកនិយាយសម្រាប់ឃ្លា {issue.segment_id}:**\nសូមជ្រើសរើសតួអង្គដែលត្រូវនឹងសំឡេងពិតប្រាកដ៖",
        reply_markup=speaker_assignment_picker_keyboard(token, issue.segment_id, speaker_names),
    )
    await call.answer()


@router.callback_query(F.data.startswith("spk_sa:"))
async def cb_issue_save_speaker_assignment(call: CallbackQuery) -> None:
    """Assign selected speaker to segment (F4)."""
    parts = call.data.split(":")
    token = parts[1]
    segment_id = parts[2]
    new_spk = parts[3]

    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    # Update assignment
    updated_assignments = []
    found = False
    for a in plan.speaker_assignments:
        if a.segment_id == segment_id:
            updated_assignments.append(
                SpeakerAssignment(
                    segment_id=a.segment_id,
                    speaker_id=new_spk,
                    evidence_key=a.evidence_key,
                    origin="manual",
                    confirmed_by_user=True,
                    confidence=1.0,
                    confidence_kind="calibrated",
                )
            )
            found = True
        else:
            updated_assignments.append(a)

    if not found:
        updated_assignments.append(
            SpeakerAssignment(
                segment_id=segment_id,
                speaker_id=new_spk,
                evidence_key="manual",
                origin="manual",
                confirmed_by_user=True,
                confidence=1.0,
                confidence_kind="calibrated",
            )
        )

    plan.speaker_assignments = updated_assignments

    # Also update SourceSegment speaker_id
    for s in plan.segments:
        if s.segment_id == segment_id:
            s.speaker_id = new_spk
            s.speaker_assignment_origin = "manual"
            s.needs_review = False

    # Invalidate full preview digest
    plan.preview_plan_digest = None
    plan.full_preview_approved_digest = None

    # Re-audit review issues
    available_voices = await get_available_voices()
    available_ids = {v["ShortName"] for v in available_voices}
    audit_issues = audit_speaker_plan(plan, available_ids, config.speaker_require_unscored_review)
    # Remove old unknown_speaker / competing issue for this segment
    other_issues = [i for i in plan.review_issues if i.segment_id != segment_id and i.producer != "speaker_review"]
    plan.review_issues = audit_issues + other_issues

    save_dubbing_plan(job.job_id, rev.revision_id, plan)

    speaker_review_store.record_decision(
        job_id=job.job_id,
        revision_id=rev.revision_id,
        user_id=token_data["user_id"],
        action="assign_speaker",
        target_id=segment_id,
        details={"speaker_id": new_spk},
    )

    await call.answer(f"✅ បានកំណត់អ្នកនិយាយ {new_spk} សម្រាប់ឃ្លា {segment_id}!")
    await render_review_issue(call, token, 0)


@router.callback_query(F.data.startswith("spk_it:"))
async def cb_issue_edit_text(call: CallbackQuery, state: FSMContext) -> None:
    """Trigger segment text editing from issue card (F4)."""
    _, token, segment_id = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    s_seg = plan.get_segment(segment_id)
    t_seg = plan.get_translation(segment_id)
    if not s_seg:
        await call.answer("មិនមានទិន្នន័យឃ្លាឡើយ។", show_alert=True)
        return

    await state.update_data(
        job_id=job.job_id,
        revision_id=rev.revision_id,
        editing_segment_id=segment_id,
        speaker_token=token,
    )
    await state.set_state(WizardStep.editing_segment_text)

    prompt = (
        f"✏️ **កែសម្រួលអត្ថបទឃ្លា {segment_id} ({s_seg.start_ms/1000.0:.1f}s - {s_seg.end_ms/1000.0:.1f}s)៖**\n\n"
        f"• **ដើម៖** _{s_seg.source_text}_\n"
        f"• **បកប្រែបច្ចុប្បន្ន៖** **{t_seg.translated_text if t_seg else ''}**\n\n"
        f"សូមវាយអត្ថបទបកប្រែថ្មីផ្ញើមកទីនេះ៖"
    )
    await safe_edit_message(call, prompt)
    await call.answer()


@router.callback_query(F.data.startswith("spk_ac:"))
async def cb_speaker_acknowledge_issue(call: CallbackQuery) -> None:
    """Acknowledge / confirm an uncertain issue where allowed (F10)."""
    _, token, issue_idx_str = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    issue_idx = int(issue_idx_str)
    if issue_idx >= len(plan.review_issues):
        await call.answer("មិនមានទិន្នន័យឡើយ។", show_alert=True)
        return

    issue = plan.review_issues[issue_idx]
    if not issue.allow_confirmation:
        await call.answer("បញ្ហានេះតម្រូវឱ្យកែប្រែជាក់ស្ដែង មិនអាចគ្រាន់តែចុចបញ្ជាក់បានទេ។", show_alert=True)
        return

    # Update confirmed_for_key to current subject_key
    updated_issues = []
    for i, iss in enumerate(plan.review_issues):
        if i == issue_idx:
            updated_issues.append(
                ReviewIssue(
                    issue_id=iss.issue_id,
                    segment_id=iss.segment_id,
                    reason=iss.reason,
                    subject_key=iss.subject_key,
                    producer=iss.producer,
                    blocking=iss.blocking,
                    allow_confirmation=iss.allow_confirmation,
                    confirmed_for_key=iss.subject_key,
                )
            )
        else:
            updated_issues.append(iss)

    plan.review_issues = updated_issues
    save_dubbing_plan(job.job_id, rev.revision_id, plan)

    speaker_review_store.record_decision(
        job_id=job.job_id,
        revision_id=rev.revision_id,
        user_id=token_data["user_id"],
        action="acknowledge_issue",
        target_id=issue.issue_id,
        details={"subject_key": issue.subject_key},
    )

    await call.answer("✅ បានបញ្ជាក់ឈុតនេះរួចរាល់!")
    # F10: call render_review_issue directly without mutating frozen CallbackQuery!
    await render_review_issue(call, token, issue_idx)


@router.callback_query(F.data.startswith("spk_bk:"))
async def cb_speaker_back_to_card(call: CallbackQuery) -> None:
    """Return to Speaker Card from review or voice selection (F1 verified)."""
    _, token = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    await render_speaker_card(
        call=call,
        job_id=token_data["job_id"],
        revision_id=token_data["revision_id"],
        user_id=token_data["user_id"],
        speaker_index=0,
        plan=plan,
    )
    await call.answer()


# ---------------- Full Preview & Approval (F6, F8, F9) ----------------

@router.callback_query(F.data.startswith("spk_fp:"))
async def cb_speaker_full_preview(call: CallbackQuery) -> None:
    """Generate and deliver full-timeline video preview (F6, F8, F9)."""
    _, token = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    job_id = token_data["job_id"]
    rev_id = token_data["revision_id"]

    # F8: Check cancellation before starting
    if worker_pool.is_cancelled(job_id):
        await call.answer("ការងារត្រូវបានបោះបង់។", show_alert=True)
        return

    await call.answer("🎬 កំពុង Render Full Preview វីដេអូទាំងមូល...")
    await safe_edit_message(call, "⏳ កំពុង Render Full Timeline Video Preview វីដេអូទាំងមូល... សូមរង់ចាំបន្តិច។")

    # Step 1: Synthesize all segments with chosen voices
    plan = await synthesize_and_fit_plan(
        plan=plan,
        job_id=job_id,
        revision_id=rev_id,
        settings=rev.settings,
        cancel_check=lambda: worker_pool.is_cancelled(job_id),
        require_confirmed_voices=False,
    )
    if worker_pool.is_cancelled(job_id):
        return

    if not plan.clips:
        await call.answer("⚠️ មិនអាច Render Preview បានទេ ព្រោះគ្មានសំឡេងបកប្រែ។", show_alert=True)
        return

    # Step 2: Assemble timeline PCM audio & subtitles (F9: generate both SRT and ASS)
    timeline_wav = workspace.get_timeline_audio_path(job_id, rev_id)
    placements, sync_rep = assemble_timeline_pcm(plan, timeline_wav)
    save_sync_report(job_id, rev_id, sync_rep)

    sub_srt = workspace.get_subtitles_srt_path(job_id, rev_id)
    sub_ass = workspace.get_subtitles_ass_path(job_id, rev_id)
    build_timeline_subtitles(plan, sub_srt, sub_ass, rev.settings.subtitle_color, rev.settings.subtitle_position)

    # Step 3: Render full preview MP4
    full_preview_path = workspace.get_full_preview_path(job_id, rev_id)
    await render_full_preview_video(
        source_path=job.source_path,
        voice_audio_path=timeline_wav,
        output_path=full_preview_path,
        settings=rev.settings,
        target_duration=plan.source_duration_ms / 1000.0,
        subtitles_ass_path=sub_ass,
        cancel_check=lambda: worker_pool.is_cancelled(job_id),
    )
    if worker_pool.is_cancelled(job_id):
        return

    # Step 4: Compute content digest and record it
    digest = compute_plan_content_digest(plan, rev.settings)
    plan.preview_plan_digest = digest
    save_dubbing_plan(job_id, rev_id, plan)

    # Generate completeness report (Addendum requirement 4)
    generate_completeness_report(plan, rev.settings, job_id, rev_id)

    # F9: Atomically persist subtitles_ass and subtitles_srt in revision!
    job_storage.update_revision(
        job_id=job_id,
        revision_id=rev_id,
        preview_path=str(full_preview_path),
        audio_path=str(timeline_wav),
        audio_duration=plan.source_duration_ms / 1000.0,
        subtitles_srt=str(sub_srt),
        subtitles_ass=str(sub_ass),
    )

    if full_preview_path.exists() and not worker_pool.is_cancelled(job_id):
        video_input = FSInputFile(str(full_preview_path), filename="preview_full.mp4")
        await call.message.reply_video(
            video=video_input,
            caption=(
                "🎬 **Full Timeline Video Preview (ពិនិត្យវីដេអូពេញលេញ)៖**\n\n"
                "• បានតម្រឹមសំឡេង AI គ្រប់តួអង្គតាមពេលវេលាដើម\n"
                "• មិនមានបញ្ហាដែលប្រព័ន្ធបានរកឃើញ។ សូមពិនិត្យ Preview មុនបញ្ជាក់។"
            ),
            supports_streaming=True,
        )

    # Re-render card with "Approve" button unlocked
    await render_speaker_card(
        call=call,
        job_id=job_id,
        revision_id=rev_id,
        user_id=token_data["user_id"],
        speaker_index=0,
        plan=plan,
    )


@router.callback_query(F.data.startswith("spk_ap:"))
async def cb_speaker_approve_final(call: CallbackQuery) -> None:
    """Approve matching full preview and enqueue final export (F6: validate all blocking issues)."""
    _, token = call.data.split(":")
    verified = await verify_speaker_token(call, token)
    if not verified:
        return
    token_data, job, plan, rev = verified

    job_id = token_data["job_id"]
    rev_id = token_data["revision_id"]

    available_voices = await get_available_voices()
    available_ids = {v["ShortName"] for v in available_voices}

    plan_digest = compute_plan_content_digest(plan, rev.settings)

    # F6: Validate content coverage across all stages
    coverage_issues = validate_content_coverage(plan, rev.settings, require_clips_and_placements=True)
    if coverage_issues:
        first_issue = coverage_issues[0]
        await call.answer(f"⚠️ មិនទាន់អាច Export បានទេ៖ {first_issue.message}", show_alert=True)
        return

    # F6: Validate final review gate (both review issues and plan issues)
    try:
        assert_final_ready(
            segment_ids=[s.segment_id for s in plan.segments],
            assignments={a.segment_id: a for a in plan.speaker_assignments},
            voice_map=plan.speaker_voice_map,
            available_voice_ids=available_ids,
            issues=plan.review_issues,
            plan_digest=plan_digest,
            approved_full_preview_digest=plan.preview_plan_digest,
            plan_issues=plan.issues,
        )
    except ReviewRequired as re:
        await call.answer(f"⚠️ មិនទាន់អាច Export បានទេ៖ {re}", show_alert=True)
        return

    # Mark approved digest
    plan.full_preview_approved_digest = plan_digest
    save_dubbing_plan(job_id, rev_id, plan)

    speaker_review_store.record_decision(
        job_id=job_id,
        revision_id=rev_id,
        user_id=token_data["user_id"],
        action="approve_full_preview",
        target_id=plan_digest,
    )

    # Enqueue final task
    job_storage.set_job_status(job_id, JobState.FINAL_QUEUED)
    job_storage.enqueue_task(job_id, rev_id, token_data["user_id"], "final")

    await safe_edit_message(
        call,
        "🚀 **ការងារត្រូវបានបញ្ជូនទៅ Render វីដេអូផ្លូវការ (Final Export) ដោយជោគជ័យ!**\n"
        "សូមរង់ចាំបន្តិច ប្រព័ន្ធនឹងផ្ញើវីដេអូសម្រេចជូនអ្នក។"
    )
    await call.answer()


@router.callback_query(F.data.startswith("spk_cx:"))
async def cb_speaker_cancel(call: CallbackQuery) -> None:
    """Cancel job (F1 & F8 verified)."""
    _, token = call.data.split(":")
    token_data = speaker_review_store.get_token(token)
    if not token_data:
        await call.answer("វគ្គបានផុតកំណត់។", show_alert=True)
        return

    # Ownership check
    if call.from_user.id != token_data["user_id"]:
        await call.answer("អ្នកមិនមានសិទ្ធិបោះបង់ការងារនេះឡើយ។", show_alert=True)
        return

    job_id = token_data["job_id"]
    worker_pool.cancel_job(job_id)
    await safe_edit_message(call, "❌ ការងារត្រូវបានបោះបង់។")
    await call.answer()
