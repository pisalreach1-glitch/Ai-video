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
from app.handlers.common import safe_edit_message, verify_callback_job
from app.ui import texts_km as texts
from app.ui.keyboards import (
    mode_choice_keyboard,
    dubbing_review_keyboard,
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
    if not await verify_callback_job(call, job_id, allowed_states=(JobState.AWAITING_TEXT, JobState.AWAITING_SETTINGS, JobState.ANALYZING_SOURCE, JobState.AWAITING_SEGMENT_REVIEW)):
        return

    job = job_storage.get_job(job_id)
    if not job or not job.source_path:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    job_storage.set_job_mode(job_id, "source_timed")
    job_storage.set_job_status(job_id, JobState.ANALYZING_SOURCE, stage="analyzing_source")
    await state.update_data(job_id=job_id, mode="source_timed")

    video_duration = job.source_media_info.duration if job.source_media_info else 0.0

    await safe_edit_message(call, texts.DUBBING_ANALYZING)
    await call.answer("⏳ កំពុងវិភាគសំឡេង...")

    from app.services.source_asr import transcribe_source
    from app.services.segment_translation import translate_segments
    from app.storage.dubbing import load_source_segments

    try:
        source_segments = load_source_segments(job_id)
        if not source_segments:
            source_segments = await transcribe_source(
                video_path=Path(job.source_path),
                video_duration=video_duration,
                job_id=job_id,
            )
            if source_segments:
                save_source_segments(job_id, source_segments)

        # Step 2: Translate segments
        job_storage.set_job_status(job_id, JobState.TRANSLATING_SEGMENTS, stage="translating_segments")
        await safe_edit_message(call, texts.DUBBING_TRANSLATING)

        translated_segments = await translate_segments(
            segments=source_segments,
            provider=config.translation_provider,
        )

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

        if config.enable_multi_speaker_dubbing:
            from app.ui.speaker_keyboards import speaker_mode_choice_keyboard
            await safe_edit_message(
                call,
                "👥 **ជ្រើសរើសរបៀបសំឡេងសម្រាប់វីដេអូនេះ៖**\n\n"
                "• 🎙 **សំឡេងមួយ** — ប្រើសំឡេង AI តែមួយសម្រាប់វីដេអូទាំងមូល\n"
                "• 👥 **សំឡេងតាមអ្នកនិយាយ** — បែងចែកអ្នកនិយាយ (Speaker A/B) និងជ្រើសសំឡេង AI ដាច់ដោយឡែកសម្រាប់តួអង្គម្នាក់ៗ",
                reply_markup=speaker_mode_choice_keyboard(job_id),
            )
        else:
            # Present paginated segment review (3 segments per page)
            from app.handlers.dubbing import render_segment_review_page
            await render_segment_review_page(call, job_id, rev.revision_id, page=1, plan=plan)

    except Exception as e:
        logger.exception(f"Source-timed dubbing setup failed for job {job_id}: {e}")
        job_storage.set_job_status(job_id, JobState.AWAITING_TEXT)
        clean_err = str(e).replace("_", " ").replace("*", " ").replace("`", "'")[:200]
        await safe_edit_message(
            call,
            f"❌ ការវិភាគសំឡេងវីដេអូបរាជ័យ៖ {clean_err}\n\nសូមជ្រើសរើសរបៀប Narration ថ្មីវិញ៖",
            reply_markup=mode_choice_keyboard(job_id, has_caption=False),
        )
