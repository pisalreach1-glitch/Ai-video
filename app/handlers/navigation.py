"""Navigation, Back, and Resume handlers."""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from app.domain.states import WizardStep, JobState
from app.domain.features import JobFeature
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
    active_job_picker_keyboard,
)
from app.features.talking_photo.states import TalkingPhotoSteps
from app.features.talking_photo.storage import talking_photo_storage
from app.features.talking_photo.keyboards import (
    tp_photo_prompt_keyboard,
    tp_voice_prompt_keyboard,
    tp_input_review_keyboard,
    tp_preview_keyboard,
)

router = Router(name="navigation")

async def _resume_single_job(call: CallbackQuery, state: FSMContext, job) -> None:
    job_id = job.job_id
    feature = getattr(job, "feature", JobFeature.VIDEO_VOICEOVER.value)

    if feature == JobFeature.TALKING_PHOTO.value:
        tp_rev = talking_photo_storage.get_latest_revision(job_id)
        rev_id = tp_rev.revision_id if tp_rev else 1
        await state.update_data(job_id=job_id, revision_id=rev_id, feature=feature)

        status = job.status
        if status == JobState.AWAITING_SOURCE:
            await state.set_state(TalkingPhotoSteps.waiting_photo)
            await safe_edit_message(call, texts.TP_PHOTO_PROMPT, reply_markup=tp_photo_prompt_keyboard(), prefer_new_for_media=True)
        elif status == JobState.AWAITING_TEXT or (tp_rev and not tp_rev.original_voice_path):
            await state.set_state(TalkingPhotoSteps.waiting_voice)
            await safe_edit_message(call, texts.TP_VOICE_PROMPT, reply_markup=tp_voice_prompt_keyboard(job_id), prefer_new_for_media=True)
        elif status == JobState.AWAITING_APPROVAL:
            await state.set_state(TalkingPhotoSteps.reviewing_video)
            await safe_edit_message(call, texts.PREVIEW_REVIEW_PROMPT, reply_markup=tp_preview_keyboard(job_id, rev_id), prefer_new_for_media=True)
        elif status in (JobState.RENDERING, JobState.PREVIEW_RENDERING, JobState.FINAL_QUEUED, JobState.PREVIEW_QUEUED):
            await state.set_state(TalkingPhotoSteps.rendering)
            await safe_edit_message(call, texts.JOB_RENDERING, reply_markup=job_in_progress_keyboard(job_id), prefer_new_for_media=True)
        else:
            await state.set_state(TalkingPhotoSteps.reviewing_inputs)
            review_text = texts.TP_REVIEW_PROMPT.format(
                width=512,
                height=512,
                duration=0.0,
                face_size=256,
            )
            await safe_edit_message(call, review_text, reply_markup=tp_input_review_keyboard(job_id, rev_id), prefer_new_for_media=True)
        return

    # Video voiceover resume branch
    rev = job_storage.get_latest_revision(job_id)
    rev_id = rev.revision_id if rev else 1
    await state.update_data(job_id=job_id, revision_id=rev_id, feature=feature)

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

@router.callback_query(F.data == "nav_resume")
async def cb_resume_job(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    active_jobs = job_storage.get_user_active_jobs(user_id, chat_id)
    if not active_jobs:
        await safe_edit_message(
            call,
            "⚠️ មិនមានការងារដែលត្រូវបន្តឡើយ។",
            reply_markup=main_menu_keyboard(has_active_job=False),
            prefer_new_for_media=True,
        )
        return

    if len(active_jobs) > 1:
        # Show job picker as required by contract
        await safe_edit_message(
            call,
            "📋 **លោកអ្នកមានការងារមិនទាន់បញ្ចប់ចំនួនច្រើន៖**\nសូមជ្រើសរើសការងារដែលចង់បន្តដំណើរការ៖",
            reply_markup=active_job_picker_keyboard(active_jobs),
            prefer_new_for_media=True,
        )
        return

    await _resume_single_job(call, state, active_jobs[0])

@router.callback_query(F.data.startswith("resume_job:"))
async def cb_resume_selected_job(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    _, job_id = call.data.split(":")
    job = job_storage.get_job(job_id)
    if not job:
        await safe_edit_message(
            call,
            "⚠️ រកមិនឃើញការងារនេះទេ។",
            reply_markup=main_menu_keyboard(has_active_job=False),
            prefer_new_for_media=True,
        )
        return
    await _resume_single_job(call, state, job)

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
