"""Navigation, Back, and Resume handlers."""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from app.domain.states import WizardStep, JobState
from app.storage.jobs import job_storage
from app.handlers.common import safe_edit_message
from app.ui import texts_km as texts
from app.ui.keyboards import (
    source_choice_keyboard,
    narration_confirm_keyboard,
    settings_menu_keyboard,
    audio_review_keyboard,
    video_preview_review_keyboard,
    job_in_progress_keyboard,
    duration_choice_keyboard,
    main_menu_keyboard,
    interrupted_job_keyboard,
)

router = Router(name="navigation")

@router.callback_query(F.data == "nav_resume")
async def cb_resume_job(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    job = job_storage.get_user_active_job(user_id, chat_id)
    if not job:
        await safe_edit_message(
            call,
            "⚠️ មិនមានការងារដែលត្រូវបន្តឡើយ។",
            reply_markup=main_menu_keyboard(has_active_job=False),
            prefer_new_for_media=True,
        )
        return

    job_id = job.job_id
    rev = job_storage.get_latest_revision(job_id)
    rev_id = rev.revision_id if rev else 1
    await state.update_data(job_id=job_id, revision_id=rev_id)

    status = job.status
    if status == JobState.AWAITING_SOURCE:
        await state.set_state(WizardStep.awaiting_video_source)
        await safe_edit_message(call, texts.SOURCE_PROMPT, reply_markup=source_choice_keyboard(), prefer_new_for_media=True)

    elif status == JobState.AWAITING_TEXT:
        await state.set_state(WizardStep.awaiting_narration_text)
        await safe_edit_message(
            call,
            texts.NARRATION_PROMPT.format(max_chars=2000),
            reply_markup=source_choice_keyboard(),
            prefer_new_for_media=True,
        )

    elif status in (JobState.AWAITING_SETTINGS, JobState.GENERATING_AUDIO):
        await state.set_state(WizardStep.customizing_settings)
        await safe_edit_message(
            call,
            texts.AFTER_NARRATION_PROMPT,
            reply_markup=settings_menu_keyboard(job_id, rev_id),
            prefer_new_for_media=True,
        )

    elif status == JobState.AWAITING_AUDIO_REVIEW:
        await state.set_state(WizardStep.audio_review)
        v_dur = job.source_media_info.duration if job.source_media_info else 0.0
        a_dur = rev.audio_duration if rev else 0.0
        await safe_edit_message(
            call,
            texts.AUDIO_REVIEW_PROMPT.format(audio_dur=a_dur, video_dur=v_dur),
            reply_markup=audio_review_keyboard(job_id, rev_id),
            prefer_new_for_media=True,
        )

    elif status == JobState.AWAITING_DURATION_CHOICE:
        await state.set_state(WizardStep.duration_choice)
        v_dur = job.source_media_info.duration if job.source_media_info else 0.0
        a_dur = rev.audio_duration if rev else 0.0
        await safe_edit_message(
            call,
            texts.DURATION_CHOICE_PROMPT.format(audio_dur=a_dur, video_dur=v_dur),
            reply_markup=duration_choice_keyboard(job_id, rev_id),
            prefer_new_for_media=True,
        )

    elif status == JobState.AWAITING_APPROVAL:
        await state.set_state(WizardStep.preview_review)
        await safe_edit_message(
            call,
            texts.PREVIEW_REVIEW_PROMPT,
            reply_markup=video_preview_review_keyboard(job_id, rev_id),
            prefer_new_for_media=True,
        )

    elif status in (JobState.RENDERING, JobState.PREVIEW_RENDERING, JobState.FINAL_QUEUED, JobState.PREVIEW_QUEUED):
        await state.set_state(WizardStep.rendering_in_progress)
        await safe_edit_message(
            call,
            texts.JOB_RENDERING,
            reply_markup=job_in_progress_keyboard(job_id),
            prefer_new_for_media=True,
        )

    elif status == JobState.INTERRUPTED:
        await safe_edit_message(
            call,
            "⚠️ ការងាររបស់អ្នកត្រូវបានផ្អាកដោយសារ bot បាន restart។\n"
            "តើអ្នកចង់សាកល្បងដំណើរការឡើងវិញ ឬចាប់ផ្ដើមការងារថ្មី?",
            reply_markup=interrupted_job_keyboard(job_id, rev_id),
            prefer_new_for_media=True,
        )

    else:
        await safe_edit_message(
            call,
            texts.START_WELCOME,
            reply_markup=main_menu_keyboard(has_active_job=False),
            prefer_new_for_media=True,
        )

@router.callback_query(F.data == "nav_source")
async def cb_nav_source(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    await state.set_state(WizardStep.awaiting_video_source)
    await safe_edit_message(call, texts.SOURCE_PROMPT, reply_markup=source_choice_keyboard(), prefer_new_for_media=True)

@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery) -> None:
    await call.answer()
