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
from app.ui.keyboards import main_menu_keyboard, settings_menu_keyboard

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

    await call.message.edit_text(
        texts.JOB_CANCELLED,
        reply_markup=main_menu_keyboard(has_active_job=False),
    )
    await call.answer()

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
    rev = job_storage.get_latest_revision(job_id)
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    # Create new revision based on latest
    new_rev = job_storage.create_revision(
        job_id=job_id,
        narration_text=rev.narration_text,
        settings=rev.settings,
    )
    await state.update_data(job_id=job_id, revision_id=new_rev.revision_id)
    await state.set_state(WizardStep.customizing_settings)

    from app.handlers.settings import _render_settings_summary
    text = _render_settings_summary(new_rev)
    await call.message.edit_text(text, reply_markup=settings_menu_keyboard(job_id, new_rev.revision_id))
    await call.answer()
