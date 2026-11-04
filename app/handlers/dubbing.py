import asyncio
import math
import logging
import unicodedata
from pathlib import Path
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from app.config import config
from app.domain.states import WizardStep, JobState
from app.domain.dubbing import DubbingPlan
from app.storage.jobs import job_storage
from app.storage.dubbing import (
    save_dubbing_plan,
    load_dubbing_plan,
    save_sync_report,
    load_sync_report,
)
from app.storage.workspaces import workspace
from app.handlers.common import safe_edit_message, verify_callback_job, answer_callback_safely
from app.services.progress import live_progress, progress_text, stage_label
from app.ui import texts_km as texts
from app.ui.keyboards import (
    dubbing_review_keyboard,
    dubbing_fit_resolution_keyboard,
    video_preview_review_keyboard,
    job_in_progress_keyboard,
)
from app.services.segment_translation import (
    shorten_single_segment_khmer,
    shorten_overlong_segments,
)

logger = logging.getLogger(__name__)
router = Router(name="dubbing")

SEGMENTS_PER_PAGE = 3

def invalidate_segment_tts(job_id: str, revision_id: int, segment_id: str) -> None:
    workspace.get_segment_voice_mp3(job_id, revision_id, segment_id).unlink(missing_ok=True)
    workspace.get_segment_voice_wav(job_id, revision_id, segment_id).unlink(missing_ok=True)
    workspace.get_segment_fitted_wav(job_id, revision_id, segment_id).unlink(missing_ok=True)
    workspace.get_segment_tts_events_path(job_id, revision_id, segment_id).unlink(missing_ok=True)

async def render_segment_review_page(
    call: CallbackQuery,
    job_id: str,
    revision_id: int,
    page: int,
    plan: DubbingPlan | None = None,
    advanced: bool = False,
) -> None:
    """Helper to display paginated segment review with edit buttons."""
    if not plan:
        plan = load_dubbing_plan(job_id, revision_id)
    if not plan or not plan.segments:
        await call.answer("មិនមានទិន្នន័យឃ្លាឡើយ។", show_alert=True)
        return

    total_segments = len(plan.segments)
    total_pages = max(1, math.ceil(total_segments / SEGMENTS_PER_PAGE))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * SEGMENTS_PER_PAGE
    end_idx = min(start_idx + SEGMENTS_PER_PAGE, total_segments)
    page_segments = plan.segments[start_idx:end_idx]

    lines = []
    visible_btns = []
    for s in page_segments:
        t = plan.get_translation(s.segment_id)
        trans_text = t.translated_text if t and t.translated_text else "*(មិនទាន់បានបកប្រែ)*"
        dur_s = s.duration_ms / 1000.0
        start_s = s.start_ms / 1000.0
        end_s = s.end_ms / 1000.0

        number = start_idx + len(lines) + 1
        if advanced:
            lines.append(
                f"🔹 **ឃ្លា {number}** ({start_s:.1f}s - {end_s:.1f}s):\n"
                f"ដើម៖ {s.source_text}\nខ្មែរ៖ {trans_text}"
            )
        else:
            lines.append(f"**{number}.** {trans_text}")
        visible_btns.append((s.segment_id, str(number)))

    segments_text = "\n\n".join(lines)
    video_dur = plan.source_duration_ms / 1000.0

    msg_text = texts.DUBBING_REVIEW_TITLE.format(
        page=page,
        total_pages=total_pages,
        video_dur=video_dur,
        total_segments=total_segments,
        segments_text=segments_text,
    )

    if not advanced:
        msg_text = f"📝 **ពិនិត្យអត្ថបទខ្មែរ ({page}/{total_pages})**\n\n{segments_text}\n\nបើត្រឹមត្រូវ សូមចុចបន្តទៅវីដេអូគំរូ។"

    await safe_edit_message(
        call,
        msg_text,
        reply_markup=dubbing_review_keyboard(
            job_id=job_id,
            revision_id=revision_id,
            page=page,
            total_pages=total_pages,
            segments_on_page=visible_btns,
            advanced=advanced,
        ),
    )

@router.callback_query(F.data.startswith("d_p:"))
async def cb_dubbing_page(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id, rev_str, page_str = call.data.split(":")
    revision_id = int(rev_str)
    page = int(page_str)

    if not await verify_callback_job(call, job_id, expected_rev=revision_id):
        return

    await state.update_data(dubbing_page=page)
    await render_segment_review_page(call, job_id, revision_id, page=page)
    await call.answer()

@router.callback_query(F.data.startswith("d_ai:"))
async def cb_dubbing_auto_translate(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id, rev_str = call.data.split(":")
    revision_id = int(rev_str)

    if not await verify_callback_job(call, job_id, expected_rev=revision_id, allowed_states=(JobState.AWAITING_SEGMENT_REVIEW, JobState.AWAITING_TEXT)):
        return

    from app.storage.dubbing import load_source_segments, load_dubbing_plan, save_dubbing_plan
    from app.services.segment_translation import translate_segments, TranslationCancelledError
    import shutil

    source_segments = load_source_segments(job_id)
    if not source_segments:
        await call.answer("មិនមានទិន្នន័យឃ្លាដើមទេ។ សូមជ្រើសរើសរបៀបបកប្រែឡើងវិញ។", show_alert=True)
        return

    await call.answer("⏳ កំពុងបកប្រែដោយ AI...")
    job_storage.set_job_status(job_id, JobState.TRANSLATING_SEGMENTS, stage="translating_segments")
    await safe_edit_message(call, texts.DUBBING_TRANSLATING, reply_markup=job_in_progress_keyboard(job_id))

    def cancelled():
        current = job_storage.get_job(job_id)
        return not current or current.status == JobState.CANCELLED

    async def translation_progress(elapsed):
        await safe_edit_message(
            call, texts.DUBBING_TRANSLATING + f"\n⏱ រង់ចាំ {elapsed} វិនាទី។ អាចចុចបោះបង់បាន។",
            reply_markup=job_in_progress_keyboard(job_id),
        )

    try:
        source_job = job_storage.get_job(job_id)
        if not source_job or not source_job.source_path:
            raise ValueError("Original video is missing; please upload the video again")
        translated_segments = await translate_segments(
            source_segments, provider="gemini", cancel_check=cancelled,
            video_path=Path(source_job.source_path),
            on_progress=translation_progress,
        )
        if cancelled():
            return
        plan = load_dubbing_plan(job_id, revision_id)
        if plan:
            # A provider outage must not erase translations already reviewed by the user.
            previous = {t.segment_id: t for t in plan.translations}
            plan.translations = [
                previous.get(t.segment_id, t) if t.status == "needs_review" else t
                for t in translated_segments
            ]
            save_dubbing_plan(job_id, revision_id, plan)

        if any(t.status == "needs_review" for t in translated_segments):
            await call.message.answer("⚠️ ការបកប្រែ AI មិនទាន់បានបញ្ចប់គ្រប់ឃ្លាទេ។ អត្ថបទចាស់ត្រូវបានរក្សាទុក។ សូមសាកល្បងម្ដងទៀត ឬកែឃ្លាដោយដៃ។")

        # Invalidate any cached segment audio so new translations will generate fresh speech
        rev_dir = workspace.get_revision_dir(job_id, revision_id)
        seg_base = rev_dir / "segments"
        if seg_base.exists():
            shutil.rmtree(seg_base, ignore_errors=True)

        job_storage.set_job_status(job_id, JobState.AWAITING_SEGMENT_REVIEW, stage="awaiting_segment_review")
        await render_segment_review_page(call, job_id, revision_id, page=1, plan=plan)
    except TranslationCancelledError:
        return
    except Exception as e:
        if cancelled():
            return
        job_storage.set_job_status(job_id, JobState.AWAITING_SEGMENT_REVIEW, stage="awaiting_segment_review")
        logger.exception(f"Failed to auto-translate segments for job {job_id}: {e}")
        await safe_edit_message(
            call,
            f"❌ បរាជ័យក្នុងការបកប្រែដោយ AI៖ {e}",
            reply_markup=dubbing_review_keyboard(job_id, revision_id, page=1, total_pages=1, segments_on_page=[]),
        )

@router.callback_query(F.data.startswith("d_ed:"))
async def cb_dubbing_edit_segment(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id, rev_str, segment_id = call.data.split(":")
    revision_id = int(rev_str)

    if not await verify_callback_job(call, job_id, expected_rev=revision_id):
        return

    plan = load_dubbing_plan(job_id, revision_id)
    if not plan:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    s_seg = plan.get_segment(segment_id)
    t_seg = plan.get_translation(segment_id)
    if not s_seg:
        await call.answer("មិនអាចរកឃើញឃ្លានេះឡើយ។", show_alert=True)
        return

    await state.update_data(
        job_id=job_id,
        revision_id=revision_id,
        editing_segment_id=segment_id,
    )
    await state.set_state(WizardStep.editing_segment_text)

    prompt = texts.DUBBING_EDIT_PROMPT.format(
        segment_id=segment_id,
        start_s=s_seg.start_ms / 1000.0,
        end_s=s_seg.end_ms / 1000.0,
        duration_s=s_seg.duration_ms / 1000.0,
        source_text=s_seg.source_text,
        current_text=t_seg.translated_text if t_seg else "",
    )
    await safe_edit_message(call, prompt)
    await call.answer()

@router.message(WizardStep.editing_segment_text, F.text)
async def handle_segment_edit_text(message: Message, state: FSMContext) -> None:
    raw_text = message.text or ""
    new_text = unicodedata.normalize("NFC", raw_text).strip()

    if not new_text:
        await message.reply(texts.NARRATION_EMPTY)
        return

    data = await state.get_data()
    job_id = data.get("job_id")
    revision_id = data.get("revision_id")
    segment_id = data.get("editing_segment_id")

    plan = load_dubbing_plan(job_id, revision_id)
    if not plan:
        await message.reply("មានបញ្ហាក្នុងការរក្សាទុក សូមចាប់ផ្ដើមឡើងវិញ។")
        return

    # Update translation for this segment
    t_seg = plan.get_translation(segment_id)
    if t_seg:
        t_seg.translated_text = new_text
        t_seg.status = "ready"
    else:
        from app.domain.dubbing import TranslatedSegment
        plan.translations.append(TranslatedSegment(
            segment_id=segment_id,
            translated_text=new_text,
            translation_provider="manual",
            status="ready",
        ))

    # Invalidate cached TTS audio for this segment
    invalidate_segment_tts(job_id, revision_id, segment_id)

    save_dubbing_plan(job_id, revision_id, plan)

    # Return to segment review
    page = data.get("dubbing_page", 1)
    await state.set_state(WizardStep.dubbing_review)

    confirm_msg = await message.reply(f"✅ បានកែសម្រួលឃ្លា {segment_id} រួចរាល់!")
    # Show updated review
    total_segments = len(plan.segments)
    total_pages = max(1, math.ceil(total_segments / SEGMENTS_PER_PAGE))
    start_idx = (page - 1) * SEGMENTS_PER_PAGE
    end_idx = min(start_idx + SEGMENTS_PER_PAGE, total_segments)
    visible_btns = [(s.segment_id, s.segment_id) for s in plan.segments[start_idx:end_idx]]

    lines = []
    for s in plan.segments[start_idx:end_idx]:
        t = plan.get_translation(s.segment_id)
        trans = t.translated_text if t else ""
        lines.append(
            f"🔹 **ឃ្លា {s.segment_id}** ({s.start_ms/1000.0:.1f}s - {s.end_ms/1000.0:.1f}s | ⏱️ {s.duration_ms/1000.0:.1f}s):\n"
            f"   • ដើម៖ _{s.source_text}_\n"
            f"   • ខ្មែរ៖ **{trans}**"
        )

    await confirm_msg.edit_text(
        texts.DUBBING_REVIEW_TITLE.format(
            page=page,
            total_pages=total_pages,
            video_dur=plan.source_duration_ms / 1000.0,
            total_segments=total_segments,
            segments_text="\n\n".join(lines),
        ),
        reply_markup=dubbing_review_keyboard(
            job_id=job_id,
            revision_id=revision_id,
            page=page,
            total_pages=total_pages,
            segments_on_page=visible_btns,
        ),
    )

@router.callback_query(F.data.startswith("d_proc:"))
async def cb_dubbing_proceed(call: CallbackQuery, state: FSMContext | None = None) -> None:
    _, job_id, rev_str = call.data.split(":")
    revision_id = int(rev_str)
    await execute_dubbing_proceed(call, job_id, revision_id, state=state)


async def execute_dubbing_proceed(
    call: CallbackQuery,
    job_id: str,
    revision_id: int,
    state: FSMContext | None = None,
    acknowledge: bool = True,
) -> None:
    if not await verify_callback_job(call, job_id, expected_rev=revision_id):
        return

    plan = load_dubbing_plan(job_id, revision_id)
    revision = job_storage.get_revision(job_id, revision_id)
    if not plan or not revision:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    job_storage.set_job_status(job_id, JobState.GENERATING_SEGMENTS, stage="generating_segments")
    await safe_edit_message(call, texts.DUBBING_SYNTHESIZING, reply_markup=job_in_progress_keyboard(job_id))
    if acknowledge:
        await answer_callback_safely(call, "🎙️ កំពុងបង្កើតសំឡេង AI...")

    from app.services.dubbing import synthesize_and_fit_plan
    from app.services.timeline import assemble_timeline_pcm
    from app.services.subtitles import build_timeline_subtitles

    def cancelled():
        job = job_storage.get_job(job_id)
        return not job or job.status == JobState.CANCELLED

    async def update_progress(elapsed):
        await safe_edit_message(
            call, progress_text(stage_label("generating_segments"), elapsed),
            reply_markup=job_in_progress_keyboard(job_id),
        )

    try:
        # Step 1: Synthesize and fit clips
        async with live_progress(update_progress, cancelled=cancelled):
            plan = await synthesize_and_fit_plan(
                plan=plan,
                job_id=job_id,
                revision_id=revision_id,
                settings=revision.settings,
                cancel_check=cancelled,
            )
        if cancelled():
            return
        save_dubbing_plan(job_id, revision_id, plan)

        if not plan.clips:
            await call.answer("⚠️ មិនមានឃ្លាណាមួយត្រូវបានបង្កើតសំឡេងឡើយ។", show_alert=True)
            return

        # Resolve ordinary timing problems without asking the user to operate AI tools.
        from app.services.auto_fit import auto_fit_overlong, use_adjacent_pause

        async def resynthesize(updated):
            return await synthesize_and_fit_plan(
                plan=updated, job_id=job_id, revision_id=revision_id,
                settings=revision.settings, cancel_check=cancelled,
            )

        async def notify_repair(attempt, count):
            await safe_edit_message(
                call, f"🤖 កំពុងកែឃ្លា {count} ឱ្យសមពេលដោយស្វ័យប្រវត្តិ (សាកល្បង {attempt}/2)…",
                reply_markup=job_in_progress_keyboard(job_id),
            )

        # Prefer preserving the complete Khmer phrase over repeated shortening.
        if use_adjacent_pause(plan):
            await safe_edit_message(call, "🤖 កំពុងតម្រឹមសំឡេងដោយប្រើចន្លោះស្ងាត់ជាប់ឃ្លា…", reply_markup=job_in_progress_keyboard(job_id))
            async with live_progress(update_progress, cancelled=cancelled):
                plan = await resynthesize(plan)

        async with live_progress(update_progress, cancelled=cancelled):
            plan = await auto_fit_overlong(
                plan, shorten_overlong_segments, resynthesize,
                cancelled=cancelled, notify=notify_repair,
            )
        if cancelled():
            return
        save_dubbing_plan(job_id, revision_id, plan)

        # Check for blocking issues (overlong clips)
        too_long_clips = [c for c in plan.clips if c.status == "too_long"]
        if too_long_clips:
            first_overlong = too_long_clips[0]
            s_seg = plan.get_segment(first_overlong.segment_id)
            t_seg = plan.get_translation(first_overlong.segment_id)

            slot_s = (s_seg.duration_ms / 1000.0) if s_seg else 0.0
            actual_s = first_overlong.raw_duration_ms / 1000.0
            lag_s = max(0.0, actual_s - slot_s)

            job_storage.set_job_status(job_id, JobState.AWAITING_FIT_RESOLUTION, stage="awaiting_fit_resolution")
            await safe_edit_message(
                call,
                texts.DUBBING_TOO_LONG_ALERT.format(
                    max_tempo=config.dub_max_tempo,
                    segment_id=first_overlong.segment_id,
                    actual_dur=actual_s,
                    slot_dur=slot_s,
                    end_lag=lag_s,
                    text=t_seg.translated_text if t_seg else "",
                ),
                reply_markup=dubbing_fit_resolution_keyboard(
                    job_id=job_id,
                    revision_id=revision_id,
                    segment_id=first_overlong.segment_id,
                    overlong_count=len(too_long_clips),
                ),
            )
            return

        # Step 2: Assemble timeline audio
        job_storage.set_job_status(job_id, JobState.ASSEMBLING_TIMELINE, stage="assembling_timeline")
        timeline_wav = workspace.get_timeline_audio_path(job_id, revision_id)
        placements, sync_report = await asyncio.to_thread(assemble_timeline_pcm, plan, timeline_wav)
        save_sync_report(job_id, revision_id, sync_report)

        # Step 3: Build timeline subtitles
        sub_srt = workspace.get_subtitles_srt_path(job_id, revision_id)
        sub_ass = workspace.get_subtitles_ass_path(job_id, revision_id)
        await asyncio.to_thread(
            build_timeline_subtitles,
            plan=plan,
            output_srt=sub_srt,
            output_ass=sub_ass,
            color=revision.settings.subtitle_color,
            position=revision.settings.subtitle_position,
        )

        # Step 4: Update revision with assembled media
        timeline_dur = plan.source_duration_ms / 1000.0
        job_storage.update_revision(
            job_id=job_id,
            revision_id=revision_id,
            audio_path=str(timeline_wav),
            audio_duration=timeline_dur,
            subtitles_srt=str(sub_srt),
            subtitles_ass=str(sub_ass),
        )

        # Render and deliver the full video without a five-second approval step.
        from app.handlers.previews import _start_full_video
        await _start_full_video(call, job_id, revision_id, state, acknowledge=False)

    except asyncio.CancelledError:
        if cancelled():
            return
        raise
    except Exception as e:
        if cancelled():
            return
        logger.exception(f"Dubbing orchestration failed for job {job_id}: {e}")
        job_storage.set_job_status(job_id, JobState.FAILED, error_message=str(e))
        await safe_edit_message(call, f"❌ បរាជ័យក្នុងការតម្រឹមសំឡេង៖ {e}")

@router.callback_query(F.data.startswith("d_rep:"))
async def cb_dubbing_report(call: CallbackQuery) -> None:
    _, job_id, rev_str = call.data.split(":")
    revision_id = int(rev_str)

    report = load_sync_report(job_id, revision_id)
    plan = load_dubbing_plan(job_id, revision_id)

    dur = (plan.source_duration_ms / 1000.0) if plan else 0.0
    total_count = len(plan.segments) if plan else 0
    placed_count = len(report.get("placements", [])) if report else 0

    clips = report.get("clips", []) if report else []
    tempos = [c.get("tempo_factor", 1.0) for c in clips if c.get("tempo_factor")]
    avg_tempo = sum(tempos) / len(tempos) if tempos else 1.0

    issues = report.get("issues", []) if report else []
    issues_text = f"មាន {len(issues)} បញ្ហា" if issues else "មិនមានបញ្ហាដែលប្រព័ន្ធបានរកឃើញ។ សូមពិនិត្យ Preview មុនបញ្ជាក់។"

    report_text = texts.DUBBING_ALIGNMENT_REPORT.format(
        duration=dur,
        placed_count=placed_count,
        total_count=total_count,
        avg_tempo=avg_tempo,
        issues_text=issues_text,
    )

    await call.message.reply(report_text)
    await call.answer()


@router.callback_query(F.data.startswith("d_sh:"))
async def cb_dubbing_shorten_single_segment(call: CallbackQuery, state: FSMContext | None = None) -> None:
    parts = call.data.split(":")
    if len(parts) != 4:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return
    job_id, rev_str, segment_id = parts[1], parts[2], parts[3]
    revision_id = int(rev_str)

    if not await verify_callback_job(call, job_id, expected_rev=revision_id):
        return

    await call.answer("⏳ កំពុងសង្ខេបឃ្លាដោយ AI...")
    plan = load_dubbing_plan(job_id, revision_id)
    if not plan:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    s_seg = plan.get_segment(segment_id)
    t_seg = plan.get_translation(segment_id)
    if not s_seg or not t_seg:
        await call.answer("មិនអាចរកឃើញឃ្លានេះឡើយ។", show_alert=True)
        return

    target_s = max(s_seg.duration_ms / 1000.0, 0.001)

    try:
        shortened = await shorten_single_segment_khmer(
            source_text=s_seg.source_text,
            current_khmer=t_seg.translated_text,
            target_duration_s=target_s,
        )
    except Exception as e:
        logger.error(f"Failed to shorten segment {segment_id}: {e}")
        await call.answer(f"បរាជ័យក្នុងការសង្ខេប: {e}", show_alert=True)
        return

    t_seg.full_translation = t_seg.full_translation or t_seg.translated_text
    t_seg.proposed_concise_text = shortened
    t_seg.translated_text = shortened
    t_seg.status = "ready"
    save_dubbing_plan(job_id, revision_id, plan)

    invalidate_segment_tts(job_id, revision_id, segment_id)
    await execute_dubbing_proceed(call, job_id, revision_id, state=state, acknowledge=False)


@router.callback_query(F.data.startswith("d_sha:"))
async def cb_dubbing_shorten_all_overlong_segments(call: CallbackQuery, state: FSMContext | None = None) -> None:
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return
    job_id, rev_str = parts[1], parts[2]
    revision_id = int(rev_str)

    if not await verify_callback_job(call, job_id, expected_rev=revision_id):
        return

    await call.answer("⏳ កំពុងសង្ខេបឃ្លាវែងទាំងអស់ដោយ AI...")
    plan = load_dubbing_plan(job_id, revision_id)
    if not plan:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    too_long_ids = {c.segment_id for c in plan.clips if c.status == "too_long"}
    if not too_long_ids:
        await execute_dubbing_proceed(call, job_id, revision_id, state=state, acknowledge=False)
        return

    items_to_shorten = []
    for i, s_seg in enumerate(plan.segments):
        if s_seg.segment_id in too_long_ids:
            t_seg = plan.get_translation(s_seg.segment_id)
            if not t_seg:
                continue
            # Fitting uses the source speech window, not the following silence.
            avail_s = max(s_seg.duration_ms / 1000.0, 0.001)
            items_to_shorten.append({
                "id": s_seg.segment_id,
                "source_text": s_seg.source_text,
                "current_khmer": t_seg.translated_text,
                "target_seconds": round(avail_s, 2),
            })

    try:
        shortened_map = await shorten_overlong_segments(items_to_shorten)
    except Exception as e:
        logger.error(f"Failed to batch shorten overlong segments: {e}")
        await call.answer(f"បរាជ័យក្នុងការសង្ខេប: {e}", show_alert=True)
        return

    for sid, new_text in shortened_map.items():
        t = plan.get_translation(sid)
        if t and new_text:
            t.full_translation = t.full_translation or t.translated_text
            t.proposed_concise_text = new_text
            t.translated_text = new_text
            t.status = "ready"
            invalidate_segment_tts(job_id, revision_id, sid)

    save_dubbing_plan(job_id, revision_id, plan)
    # Telegram callback objects are frozen; pass explicit IDs to the shared runner.
    await execute_dubbing_proceed(call, job_id, revision_id, state=state, acknowledge=False)

@router.callback_query(F.data.startswith("d_more:"))
async def cb_dubbing_more(call: CallbackQuery) -> None:
    _, job_id, rev, page = call.data.split(":")
    if not await verify_callback_job(call, job_id, expected_rev=int(rev), allowed_states=(JobState.AWAITING_SEGMENT_REVIEW,)):
        return
    await call.answer()
    await render_segment_review_page(call, job_id, int(rev), int(page), advanced=True)

@router.callback_query(F.data.startswith("d_spk:"))
async def cb_dubbing_speaker_options(call: CallbackQuery) -> None:
    _, job_id, rev = call.data.split(":")
    if not await verify_callback_job(call, job_id, expected_rev=int(rev), allowed_states=(JobState.AWAITING_SEGMENT_REVIEW,)):
        return
    if not config.enable_multi_speaker_dubbing:
        await call.answer("មុខងារនេះមិនទាន់បានបើកទេ។", show_alert=True)
        return
    from app.ui.speaker_keyboards import speaker_mode_choice_keyboard
    await call.answer()
    await safe_edit_message(call, "👥 សូមជ្រើសរបៀបសំឡេង។ បើមិនចង់បែងចែកអ្នកនិយាយ សូមជ្រើសសំឡេងមួយ។", reply_markup=speaker_mode_choice_keyboard(job_id))
