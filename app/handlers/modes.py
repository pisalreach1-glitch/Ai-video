"""Handlers for selecting between Free Narration and Source-Timed Khmer Dubbing."""
import logging
from pathlib import Path
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from app.config import config
from app.domain.states import WizardStep, JobState
from app.domain.dubbing import DubbingPlan
from app.storage.jobs import job_storage
from app.storage.preferences import preferences_storage
from app.storage.dubbing import save_dubbing_plan, save_source_segments
from app.handlers.common import safe_edit_message, verify_callback_job, answer_callback_safely
from app.services.progress import live_progress, progress_text, stage_label
from app.ui import texts_km as texts
from app.ui.keyboards import (
    mode_choice_keyboard,
    dubbing_review_keyboard,
    job_in_progress_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name="modes")

@router.callback_query(F.data.startswith("mode_free:"))
async def cb_choose_free_narration(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id = call.data.split(":")
    if not await verify_callback_job(call, job_id, allowed_states=(JobState.AWAITING_TEXT, JobState.AWAITING_SETTINGS)):
        return

    job_storage.set_job_mode(job_id, "free_narration")
    await state.update_data(job_id=job_id, mode="free_narration")
    await state.set_state(WizardStep.awaiting_narration_text)

    await safe_edit_message(
        call,
        texts.NARRATION_PROMPT.format(max_chars=config.max_narration_chars),
    )
    await call.answer()

@router.callback_query(F.data.startswith("mode_dub:"))
async def cb_choose_source_timed_dubbing(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id = call.data.split(":")
    if not await verify_callback_job(call, job_id, allowed_states=(JobState.AWAITING_TEXT, JobState.AWAITING_SETTINGS, JobState.AWAITING_SEGMENT_REVIEW)):
        return

    job = job_storage.get_job(job_id)
    if not job or not job.source_path:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    job_storage.set_job_mode(job_id, "source_timed")
    job_storage.set_job_status(job_id, JobState.ANALYZING_SOURCE, stage="analyzing_source")
    await state.update_data(job_id=job_id, mode="source_timed")

    video_duration = job.source_media_info.duration if job.source_media_info else 0.0

    from app.services.source_asr import transcribe_source
    from app.services.segment_translation import translate_segments, TranslationCancelledError
    from app.storage.dubbing import load_source_segments

    def cancelled():
        current = job_storage.get_job(job_id)
        return not current or current.status == JobState.CANCELLED

    async def translation_progress(elapsed):
        await safe_edit_message(
            call, texts.DUBBING_TRANSLATING + f"\n⏱ រង់ចាំ {elapsed} វិនាទី។ អាចចុចបោះបង់បាន។",
            reply_markup=job_in_progress_keyboard(job_id),
        )

    async def analysis_progress(elapsed):
        await safe_edit_message(
            call, progress_text(stage_label("analyzing_source"), elapsed),
            reply_markup=job_in_progress_keyboard(job_id),
        )

    try:
        await answer_callback_safely(call, "⏳ កំពុងវិភាគសំឡេង...")
        source_segments = load_source_segments(job_id)
        if not source_segments:
            await safe_edit_message(call, texts.DUBBING_ANALYZING, reply_markup=job_in_progress_keyboard(job_id))
            async with live_progress(analysis_progress, cancelled=cancelled):
                source_segments = await transcribe_source(
                    video_path=Path(job.source_path),
                    video_duration=video_duration,
                    job_id=job_id,
                    cancel_check=cancelled,
                )
            if source_segments:
                save_source_segments(job_id, source_segments)

        # Step 2: Translate segments
        if cancelled():
            return
        job_storage.set_job_status(job_id, JobState.TRANSLATING_SEGMENTS, stage="translating_segments")
        await safe_edit_message(call, texts.DUBBING_TRANSLATING, reply_markup=job_in_progress_keyboard(job_id))

        translated_segments = await translate_segments(
            segments=source_segments,
            provider=config.translation_provider,
            video_path=Path(job.source_path),
            cancel_check=cancelled,
            on_progress=translation_progress,
        )

        if cancelled():
            return
        if any(t.status == "needs_review" for t in translated_segments):
            await call.message.answer("⚠️ ការបកប្រែ AI មិនទាន់បានបញ្ចប់គ្រប់ឃ្លាទេ។ អ្នកអាចសាកល្បងបកប្រែម្ដងទៀត ឬកែឃ្លាដោយដៃនៅផ្ទាំងពិនិត្យ។")

        # Step 3: Build DubbingPlan & Initial Revision
        plan = DubbingPlan(
            mode="source_timed",
            source_duration_ms=int(round(video_duration * 1000)),
            sample_rate=config.dub_sample_rate,
            segments=source_segments,
            translations=translated_segments,
        )

        user_id = call.from_user.id
        prefs = preferences_storage.get_preferences(user_id)

        # Full combined text for reference
        combined_text = " ".join(t.translated_text for t in translated_segments if t.translated_text)
        rev = job_storage.create_revision(
            job_id=job_id,
            narration_text=combined_text,
            settings=prefs,
            mode="source_timed",
        )

        save_dubbing_plan(job_id, rev.revision_id, plan)
        job_storage.set_job_dubbing_revision(job_id, rev.revision_id)
        job_storage.set_job_status(job_id, JobState.AWAITING_SEGMENT_REVIEW, stage="awaiting_segment_review")

        await state.update_data(
            job_id=job_id,
            revision_id=rev.revision_id,
            dubbing_page=1,
        )
        await state.set_state(WizardStep.dubbing_review)

        from app.handlers.dubbing import render_segment_review_page, execute_dubbing_proceed
        translations = {t.segment_id: t for t in translated_segments}
        complete = bool(source_segments) and all(
            (t := translations.get(segment.segment_id)) is not None
            and t.status == "ready" and t.translated_text.strip()
            and any("\u1780" <= char <= "\u17ff" for char in t.translated_text)
            for segment in source_segments
        )
        if complete:
            # Continue on the same immutable callback; it was acknowledged before ASR.
            await execute_dubbing_proceed(call, job_id, rev.revision_id, state=state, acknowledge=False)
        else:
            await render_segment_review_page(call, job_id, rev.revision_id, page=1, plan=plan)

    except TranslationCancelledError:
        return
    except Exception as e:
        if cancelled():
            return
        logger.exception(f"Source-timed dubbing setup failed for job {job_id}: {e}")
        job_storage.set_job_status(job_id, JobState.AWAITING_TEXT)
        clean_err = str(e).replace("_", " ").replace("*", " ").replace("`", "'")[:200]
        await safe_edit_message(
            call,
            f"❌ ការវិភាគសំឡេងវីដេអូបរាជ័យ៖ {clean_err}\n\nសូមជ្រើសរើសរបៀប Narration ថ្មីវិញ៖",
            reply_markup=mode_choice_keyboard(job_id, has_caption=False),
        )

@router.callback_query(F.data.startswith("mode_more:"))
async def cb_mode_more(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id = call.data.split(":")
    if not await verify_callback_job(call, job_id, allowed_states=(JobState.AWAITING_TEXT, JobState.AWAITING_SETTINGS)):
        return
    data = await state.get_data()
    await call.answer()
    await safe_edit_message(call, "⚙️ កែបន្ថែម\n\nអ្នកអាចសរសេរអត្ថបទផ្ទាល់ខ្លួន ឬជ្រើសការបកប្រែធម្មតា។", reply_markup=mode_choice_keyboard(job_id, has_caption=bool(data.get("caption_text")), advanced=True))
