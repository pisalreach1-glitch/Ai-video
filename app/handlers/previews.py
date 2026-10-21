"""Audio preview, video preview, duration policy, and approval handlers."""
import logging
from pathlib import Path
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from app.config import config
from app.domain.states import WizardStep, JobState
from app.storage.jobs import job_storage
from app.storage.workspaces import workspace
from app.services.tts import generate_narration, TTSTimingError
from app.services.subtitles import generate_srt, generate_ass
from app.ui import texts_km as texts
from app.ui import options as opt
from app.ui.keyboards import (
    audio_review_keyboard,
    duration_choice_keyboard,
    job_in_progress_keyboard,
    video_preview_review_keyboard,
    settings_menu_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name="previews")

async def _generate_audio_and_subtitles(job_id: str, rev_id: int) -> tuple[Path, float, Path, Path]:
    job = job_storage.get_job(job_id)
    rev = job_storage.get_revision(job_id, rev_id)
    if not job or not rev:
        raise ValueError("Job or revision missing.")

    audio_dest = workspace.get_voice_audio_path(job_id, rev_id)
    srt_dest = workspace.get_subtitles_srt_path(job_id, rev_id)
    ass_dest = workspace.get_subtitles_ass_path(job_id, rev_id)

    # Generate TTS audio and timing events
    _, duration, timing_events = await generate_narration(
        text=rev.narration_text,
        voice=rev.settings.voice,
        rate=rev.settings.speed,
        output_audio_path=audio_dest,
    )

    # Generate SRT
    generate_srt(timing_events, srt_dest)

    # Generate styled ASS
    res_x = 1080
    res_y = 1920 if rev.settings.aspect_ratio == "9:16" else (1080 if rev.settings.aspect_ratio == "1:1" else (job.source_media_info.height if job.source_media_info else 1920))
    generate_ass(
        events=timing_events,
        output_path=ass_dest,
        font_name="Khmer OS Battambang",
        color=rev.settings.subtitle_color,
        position=rev.settings.subtitle_position,
        res_x=res_x,
        res_y=res_y,
    )

    # Update revision
    job_storage.update_revision(
        job_id,
        rev_id,
        audio_path=str(audio_dest),
        audio_duration=duration,
        subtitles_srt=str(srt_dest),
        subtitles_ass=str(ass_dest),
    )
    return audio_dest, duration, srt_dest, ass_dest

@router.callback_query(F.data == "cfg_use_defaults")
@router.callback_query(F.data.startswith("set_proceed:"))
async def cb_proceed_to_audio(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    job_id = data.get("job_id")
    rev_id = data.get("revision_id")

    if not job_id and ":" in call.data:
        _, job_id, rev_id_str = call.data.split(":")
        rev_id = int(rev_id_str)

    if not job_id or not rev_id:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    job = job_storage.get_job(job_id)
    rev = job_storage.get_revision(job_id, rev_id)
    if not job or not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    await call.message.edit_text(texts.AUDIO_GENERATING)

    try:
        job_storage.set_job_status(job_id, JobState.GENERATING_AUDIO)
        audio_path, a_dur, _, _ = await _generate_audio_and_subtitles(job_id, rev_id)
        job_storage.set_job_status(job_id, JobState.AWAITING_AUDIO_REVIEW)

        v_dur = job.source_media_info.duration if job.source_media_info else 0.0

        # Send generated audio to user
        audio_file = FSInputFile(str(audio_path), filename=f"narration_{job_id[:6]}.mp3")
        await bot.send_audio(
            chat_id=call.message.chat.id,
            audio=audio_file,
            caption=f"🎙️ សំឡេងអាន AI ({a_dur:.1f}s)",
        )

        # Check if source video is shorter than audio
        if v_dur > 0 and v_dur < a_dur:
            await state.set_state(WizardStep.duration_choice)
            job_storage.set_job_status(job_id, JobState.AWAITING_DURATION_CHOICE)
            await bot.send_message(
                chat_id=call.message.chat.id,
                text=texts.DURATION_CHOICE_PROMPT.format(video_dur=v_dur, audio_dur=a_dur),
                reply_markup=duration_choice_keyboard(job_id, rev_id),
            )
        else:
            await state.set_state(WizardStep.audio_review)
            await bot.send_message(
                chat_id=call.message.chat.id,
                text=texts.AUDIO_REVIEW_PROMPT.format(audio_dur=a_dur, video_dur=v_dur),
                reply_markup=audio_review_keyboard(job_id, rev_id),
            )

    except TTSTimingError as e:
        logger.warning(f"TTS timing error for job {job_id}: {e}")
        job_storage.set_job_status(job_id, JobState.FAILED, error_message=str(e))
        await call.message.edit_text(
            f"❌ មិនអាចទទួលទិន្នន័យពេលវេលាពី Edge-TTS បានទេ៖ {e}\nសូមព្យាយាមម្ដងទៀត។",
            reply_markup=settings_menu_keyboard(job_id, rev_id),
        )
    except Exception as e:
        logger.exception(f"Error generating audio for job {job_id}: {e}")
        job_storage.set_job_status(job_id, JobState.FAILED, error_message=str(e))
        await call.message.edit_text(
            f"❌ ការបង្កើតសំឡេងបានបរាជ័យ៖ {e}",
            reply_markup=settings_menu_keyboard(job_id, rev_id),
        )

@router.callback_query(F.data.startswith("dur_pick:"))
async def cb_duration_policy_picked(call: CallbackQuery, state: FSMContext) -> None:
    _, policy, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)
    rev = job_storage.get_revision(job_id, rev_id)
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    rev.settings.duration_policy = policy
    job_storage.update_revision(job_id, rev_id, settings=rev.settings)
    job_storage.set_duration_policy(job_id, policy)

    # Proceed directly to video preview render
    await _start_video_preview(call, job_id, rev_id, state)

@router.callback_query(F.data.startswith("aud_next:"))
async def cb_audio_next_to_preview(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)
    await _start_video_preview(call, job_id, rev_id, state)

async def _start_video_preview(call: CallbackQuery, job_id: str, rev_id: int, state: FSMContext) -> None:
    job = job_storage.get_job(job_id)
    if not job:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    # Check queue
    job_storage.set_job_status(job_id, JobState.PREVIEW_QUEUED)
    enqueued = job_storage.enqueue_task(job_id, rev_id, call.from_user.id, "preview")
    if not enqueued:
        await call.answer(texts.SYSTEM_BUSY, show_alert=True)
        return

    await state.set_state(WizardStep.preview_review)
    await call.message.edit_text(
        texts.PREVIEW_GENERATING,
        reply_markup=job_in_progress_keyboard(job_id),
    )
    await call.answer()

@router.callback_query(F.data.startswith("apprv_final:"))
async def cb_approve_final(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)

    job = job_storage.get_job(job_id)
    if not job:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    # Prevent approval of outdated revision
    if job.current_revision_id != rev_id:
        await call.answer(texts.APPROVAL_OUTDATED, show_alert=True)
        return

    # Prevent duplicate clicks
    if job.status in (JobState.FINAL_QUEUED, JobState.RENDERING, JobState.UPLOADING):
        await call.answer(texts.ALREADY_PROCESSING, show_alert=True)
        return

    job_storage.set_job_status(job_id, JobState.FINAL_QUEUED)
    enqueued = job_storage.enqueue_task(job_id, rev_id, call.from_user.id, "final")
    if not enqueued:
        await call.answer(texts.SYSTEM_BUSY, show_alert=True)
        return

    await state.set_state(WizardStep.rendering_in_progress)
    await call.message.edit_text(
        texts.JOB_RENDERING,
        reply_markup=job_in_progress_keyboard(job_id),
    )
    await call.answer()

# Edit triggers from review screens
@router.callback_query(F.data.startswith("edit_text:"))
async def cb_edit_text(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    await state.update_data(job_id=job_id, revision_id=int(rev_id_str))
    await state.set_state(WizardStep.awaiting_narration_text)
    await call.message.edit_text(
        f"✏️ **កែសម្រួលអត្ថបទអាន៖**\n\n{texts.NARRATION_PROMPT.format(max_chars=config.max_narration_chars)}"
    )
    await call.answer()

@router.callback_query(F.data.startswith("edit_voice:"))
@router.callback_query(F.data.startswith("edit_speed:"))
@router.callback_query(F.data.startswith("edit_sub:"))
@router.callback_query(F.data.startswith("edit_fmt:"))
async def cb_edit_settings_forward(call: CallbackQuery, state: FSMContext) -> None:
    action, job_id, rev_id_str = call.data.split(":")
    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    from app.handlers.settings import _render_settings_summary
    text = _render_settings_summary(rev)
    await call.message.edit_text(text, reply_markup=settings_menu_keyboard(job_id, rev.revision_id))
    await call.answer()
