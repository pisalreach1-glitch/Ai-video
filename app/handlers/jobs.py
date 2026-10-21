"""Job actions: cancellation, delivery retries, and media downloads."""
import logging
from pathlib import Path
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from app.domain.states import JobState, WizardStep
from app.storage.jobs import job_storage
from app.jobs.worker import worker_pool
from app.services.delivery import deliver_final_video, send_srt_file
from app.ui import texts_km as texts
from app.ui.keyboards import main_menu_keyboard, settings_menu_keyboard, job_in_progress_keyboard, audio_review_keyboard
from app.handlers.common import safe_edit_message, safe_edit_reply_markup

logger = logging.getLogger(__name__)
router = Router(name="jobs")

@router.callback_query(F.data.startswith("job_cancel:"))
async def cb_cancel_job(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id = call.data.split(":")
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if not job_storage.verify_ownership(job_id, user_id, chat_id):
        await call.answer("Unauthorized.", show_alert=True)
        return

    worker_pool.cancel_job(job_id)
    await state.clear()

    await safe_edit_message(
        call,
        texts.JOB_CANCELLED,
        reply_markup=main_menu_keyboard(has_active_job=False),
    )
    await call.answer()

@router.callback_query(F.data.startswith("retry_job:"))
async def cb_retry_interrupted_job(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if not job_storage.verify_ownership(job_id, user_id, chat_id):
        await call.answer("Unauthorized.", show_alert=True)
        return

    job = job_storage.get_job(job_id)
    rev = job_storage.get_revision(job_id, rev_id)
    if not job or not rev:
        await call.answer("Job or revision not found.", show_alert=True)
        return

    stage = job.stage or ""

    # Case 1: Interrupted during uploading (final video already rendered, just deliver)
    if stage == "interrupted:uploading" or (rev.final_path and Path(rev.final_path).exists()):
        await call.answer("⏳ កំពុងផ្ញើវីដេអូចុងក្រោយឡើងវិញ...")
        job_storage.set_job_status(job_id, JobState.UPLOADING)
        from app.services.delivery import deliver_final_video
        await deliver_final_video(bot, chat_id, job_id, rev)
        return

    # Case 2: Interrupted during final rendering / queue
    if stage in ("interrupted:rendering", "interrupted:final_queued", "interrupted:final_render") or (rev.audio_path and rev.preview_path):
        task_type = "final"
        next_status = JobState.FINAL_QUEUED
        job_storage.enqueue_task(job_id, rev_id, user_id, task_type)
        job_storage.set_job_status(job_id, next_status, stage="final_queue")
        await state.set_state(WizardStep.rendering_in_progress)
        await safe_edit_message(
            call,
            "⏳ ការងារ Render ចុងក្រោយត្រូវបានបញ្ចូលក្នុងជួរម្តងទៀត!\nសូមរង់ចាំបន្តិច...",
            reply_markup=job_in_progress_keyboard(job_id),
        )
        await call.answer("✅ បានដាក់ក្នុងជួរ Render ឡើងវិញ!")
        return

    # Case 3: Interrupted during preview rendering / queue
    if stage in ("interrupted:preview_rendering", "interrupted:preview_queued", "interrupted:preview_render") or (rev.audio_path and Path(rev.audio_path).exists()):
        task_type = "preview"
        next_status = JobState.PREVIEW_QUEUED
        job_storage.enqueue_task(job_id, rev_id, user_id, task_type)
        job_storage.set_job_status(job_id, next_status, stage="preview_queue")
        await state.set_state(WizardStep.rendering_in_progress)
        await safe_edit_message(
            call,
            "⏳ ការងារ Video Preview ត្រូវបានបញ្ចូលក្នុងជួរម្តងទៀត!\nសូមរង់ចាំបន្តិច...",
            reply_markup=job_in_progress_keyboard(job_id),
        )
        await call.answer("✅ បានដាក់ក្នុងជួរ Preview ឡើងវិញ!")
        return

    # Case 4: Interrupted during TTS generation (no audio generated yet)
    if stage == "interrupted:generating_audio" or not rev.audio_path or not Path(rev.audio_path).exists():
        await safe_edit_message(call, texts.AUDIO_GENERATING)
        cancel_check = lambda: worker_pool.is_cancelled(job_id)
        from app.handlers.previews import _generate_audio_and_subtitles
        try:
            job_storage.set_job_status(job_id, JobState.GENERATING_AUDIO)
            audio_path, a_dur, _, _ = await _generate_audio_and_subtitles(
                job_id, rev_id, cancel_check=cancel_check
            )
            if cancel_check():
                await safe_edit_message(call, texts.JOB_CANCELLED)
                return

            job_storage.set_job_status(job_id, JobState.AWAITING_AUDIO_REVIEW)
            audio_file = FSInputFile(str(audio_path), filename=f"narration_{job_id[:6]}.mp3")
            await bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                caption=f"🎙️ សំឡេងអាន AI ({a_dur:.1f}s)",
            )
            await bot.send_message(
                chat_id=chat_id,
                text=texts.AUDIO_REVIEW_PROMPT.format(
                    audio_dur=a_dur,
                    video_dur=job.source_media_info.duration if job.source_media_info else 0.0
                ),
                reply_markup=audio_review_keyboard(job_id, rev_id),
            )
            await call.answer("✅ បានបង្កើតសំឡេងឡើងវិញ!")
            return
        except Exception as e:
            logger.exception(f"Error retrying TTS for job {job_id}: {e}")
            job_storage.set_job_status(job_id, JobState.FAILED, error_message=str(e))
            await safe_edit_message(call, f"❌ ការបង្កើតសំឡេងបានបរាជ័យ៖ {e}")
            return

    # Case 5: Interrupted during downloading
    await state.set_state(WizardStep.awaiting_url_input)
    await safe_edit_message(call, texts.LINK_PROMPT)
    await call.answer("សូមផ្ញើ Link ឬ Upload វីដេអូឡើងវិញ។")

@router.callback_query(F.data.startswith("retry_dlv:"))
async def cb_retry_delivery(call: CallbackQuery, bot: Bot) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if not job_storage.verify_ownership(job_id, user_id, chat_id):
        await call.answer("Unauthorized.", show_alert=True)
        return

    rev = job_storage.get_revision(job_id, rev_id)
    if not rev or not rev.final_path:
        await call.answer("Final video not found.", show_alert=True)
        return

    await call.answer("⏳ កំពុងព្យាយាមផ្ញើម្តងទៀត...")
    await deliver_final_video(bot, chat_id, job_id, rev)

@router.callback_query(F.data.startswith("dl_video:"))
async def cb_download_video(call: CallbackQuery, bot: Bot) -> None:
    _, job_id = call.data.split(":")
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if not job_storage.verify_ownership(job_id, user_id, chat_id):
        await call.answer("Unauthorized.", show_alert=True)
        return

    rev = job_storage.get_latest_revision(job_id)
    if not rev or not rev.final_path or not Path(rev.final_path).exists():
        await call.answer(texts.HISTORY_EXPIRED.format(retention=24), show_alert=True)
        return

    await call.answer("⏳ កំពុងទាញយកវីដេអូ...")
    video_doc = FSInputFile(rev.final_path, filename=f"voiceover_{job_id[:8]}.mp4")
    await bot.send_document(
        chat_id=chat_id,
        document=video_doc,
        caption="🎬 វីដេអូពេញលេញ (Full HD MP4)",
    )

@router.callback_query(F.data.startswith("dl_srt:"))
async def cb_download_srt(call: CallbackQuery, bot: Bot) -> None:
    _, job_id = call.data.split(":")
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if not job_storage.verify_ownership(job_id, user_id, chat_id):
        await call.answer("Unauthorized.", show_alert=True)
        return

    rev = job_storage.get_latest_revision(job_id)
    if not rev or not rev.subtitles_srt or not Path(rev.subtitles_srt).exists():
        await call.answer("ឯកសារ Subtitle មិនត្រូវបានរកឃើញ ឬផុតកំណត់។", show_alert=True)
        return

    await call.answer("⏳ កំពុងផ្ញើឯកសារ SRT...")
    await send_srt_file(bot, chat_id, rev.subtitles_srt)

@router.callback_query(F.data.startswith("job_edit:"))
async def cb_edit_completed_job(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id = call.data.split(":")
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if not job_storage.verify_ownership(job_id, user_id, chat_id):
        await call.answer("Unauthorized.", show_alert=True)
        return

    rev = job_storage.get_latest_revision(job_id)
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    # Create new revision based on latest, carrying over audio so subtitles/ratio edits don't re-run TTS
    new_rev = job_storage.create_revision(
        job_id=job_id,
        narration_text=rev.narration_text,
        settings=rev.settings,
        audio_path=rev.audio_path,
        audio_duration=rev.audio_duration,
        subtitles_srt=rev.subtitles_srt,
    )
    job_storage.set_job_status(job_id, JobState.AWAITING_SETTINGS)
    await state.update_data(job_id=job_id, revision_id=new_rev.revision_id)
    await state.set_state(WizardStep.customizing_settings)

    from app.handlers.settings import _render_settings_summary
    text = _render_settings_summary(new_rev)
    # Remove reply markup from video safely
    await safe_edit_reply_markup(call, reply_markup=None)
    # Send settings menu as new text message
    await call.message.answer(text, reply_markup=settings_menu_keyboard(job_id, new_rev.revision_id))
    await call.answer("🔁 ចាប់ផ្ដើមកែសម្រួល")
