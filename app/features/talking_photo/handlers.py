"""Aiogram router and handlers for Talking Photo feature."""
import logging
from pathlib import Path
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from app.config import config
from app.domain.features import JobFeature
from app.domain.states import JobState
from app.storage.jobs import job_storage
from app.storage.sessions import session_storage
from app.storage.workspaces import workspace
from app.handlers.common import safe_edit_message, verify_callback_job
from app.ui import texts_km as texts
from app.ui.keyboards import main_menu_keyboard, job_in_progress_keyboard
from app.features.talking_photo.domain import TalkingPhotoSettings
from app.features.talking_photo.states import TalkingPhotoSteps
from app.features.talking_photo.storage import talking_photo_storage
from app.features.talking_photo.media import (
    validate_portrait_image,
    normalize_voice_recording,
    measure_audio_duration,
)
from app.features.talking_photo.keyboards import (
    tp_photo_prompt_keyboard,
    tp_voice_prompt_keyboard,
    tp_input_review_keyboard,
    tp_settings_keyboard,
    tp_preview_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name="talking_photo")

@router.callback_query(F.data == "nav_talking_photo")
async def cb_start_talking_photo(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass

    user_id = call.from_user.id
    chat_id = call.message.chat.id

    # Create new talking_photo job
    job = job_storage.create_job(
        user_id=user_id,
        chat_id=chat_id,
        source_type="upload",
        feature=JobFeature.TALKING_PHOTO.value,
    )

    session_storage.set_session(
        user_id=user_id,
        chat_id=chat_id,
        active_job_id=job.job_id,
        wizard_state="waiting_photo",
        state_data={"job_id": job.job_id, "feature": JobFeature.TALKING_PHOTO.value},
    )

    await state.set_state(TalkingPhotoSteps.waiting_photo)
    await state.update_data(job_id=job.job_id, feature=JobFeature.TALKING_PHOTO.value)

    await safe_edit_message(
        call,
        texts.TP_PHOTO_PROMPT,
        reply_markup=tp_photo_prompt_keyboard(),
        prefer_new_for_media=True,
    )

@router.message(TalkingPhotoSteps.waiting_photo, F.photo | F.document)
async def handle_photo_upload(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    job_id = data.get("job_id")
    if not job_id:
        user_id = message.from_user.id
        chat_id = message.chat.id
        job = job_storage.create_job(user_id=user_id, chat_id=chat_id, feature=JobFeature.TALKING_PHOTO.value)
        job_id = job.job_id
        await state.update_data(job_id=job_id)

    # Determine file_id and extension
    file_id = None
    ext = "png"
    if message.photo:
        # Highest resolution photo
        photo = message.photo[-1]
        file_id = photo.file_id
        ext = "jpg"
    elif message.document:
        mime = (message.document.mime_type or "").lower()
        fname = (message.document.file_name or "").lower()
        if not (mime.startswith("image/") or fname.endswith((".jpg", ".jpeg", ".png", ".webp"))):
            await message.reply("⚠️ សូមផ្ញើឯកសារជារូបថត (JPG, PNG, WEBP)។")
            return
        file_id = message.document.file_id
        ext = fname.split(".")[-1] if "." in fname else "png"

    dest_path = workspace.get_tp_photo_path(job_id, ext=ext)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    status_msg = await message.reply("⏳ កំពុងទទួល និងពិនិត្យរូបថត...")
    try:
        await bot.download(file_id, destination=dest_path)
        is_valid, err_msg, w, h = await validate_portrait_image(dest_path)
        if not is_valid:
            await status_msg.edit_text(f"❌ {err_msg}", reply_markup=tp_photo_prompt_keyboard())
            return

        await state.update_data(photo_path=str(dest_path), photo_width=w, photo_height=h)
        await state.set_state(TalkingPhotoSteps.waiting_voice)

        await status_msg.edit_text(
            texts.TP_VOICE_PROMPT,
            reply_markup=tp_voice_prompt_keyboard(job_id),
        )
    except Exception as e:
        logger.exception(f"Error handling photo upload: {e}")
        await status_msg.edit_text(f"❌ បរាជ័យក្នុងការទាញយករូបថត៖ {e}")

@router.message(TalkingPhotoSteps.waiting_voice, F.voice | F.audio | F.document)
async def handle_voice_upload(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    job_id = data.get("job_id")
    photo_path_str = data.get("photo_path")

    if not job_id or not photo_path_str:
        await message.reply("⚠️ សូមចាប់ផ្ដើមដោយផ្ញើរូបថតជាមុនសិន។", reply_markup=main_menu_keyboard(False))
        await state.set_state(TalkingPhotoSteps.waiting_photo)
        return

    file_id = None
    ext = "ogg"
    if message.voice:
        file_id = message.voice.file_id
        ext = "ogg"
    elif message.audio:
        file_id = message.audio.file_id
        ext = "mp3"
    elif message.document:
        mime = (message.document.mime_type or "").lower()
        fname = (message.document.file_name or "").lower()
        if not (mime.startswith("audio/") or fname.endswith((".mp3", ".wav", ".m4a", ".ogg", ".aac"))):
            await message.reply("⚠️ សូមផ្ញើសារសំឡេង (Voice) ឬឯកសារសំឡេង (MP3, WAV, OGG)។")
            return
        file_id = message.document.file_id
        ext = fname.split(".")[-1] if "." in fname else "mp3"

    voice_raw_path = workspace.get_tp_voice_path(job_id, ext=ext)
    status_msg = await message.reply("⏳ កំពុងទទួល និងកែសម្រួលកម្រិតសំឡេង (Master Audio)...")

    try:
        await bot.download(file_id, destination=voice_raw_path)

        # Paths for normalized master audio and inference wav
        master_audio = workspace.get_tp_master_audio_path(job_id, 1)
        inference_wav = workspace.get_tp_inference_wav_path(job_id, 1)

        duration = await normalize_voice_recording(
            source_voice_path=voice_raw_path,
            master_audio_wav=master_audio,
            inference_wav=inference_wav,
        )

        if duration < 0.5:
            await status_msg.edit_text("⚠️ សំឡេងខ្លីពេក (តិចជាង 0.5 វិនាទី)។ សូមថតសារសំឡេងម្ដងទៀត។")
            return

        # Create or update revision in talking_photo_storage
        st = TalkingPhotoSettings(
            face_size=int(data.get("face_size", 256)),
            still_mode=bool(data.get("still_mode", False)),
            pose_style=int(data.get("pose_style", 0)),
        )

        rev = talking_photo_storage.create_revision(
            job_id=job_id,
            image_path=photo_path_str,
            original_voice_path=str(voice_raw_path),
            settings=st,
        )

        talking_photo_storage.update_revision_paths(
            job_id=job_id,
            revision_id=rev.revision_id,
            inference_wav_path=str(inference_wav),
            master_audio_path=str(master_audio),
        )

        await state.update_data(
            revision_id=rev.revision_id,
            voice_duration=duration,
            master_audio=str(master_audio),
            inference_wav=str(inference_wav),
        )
        await state.set_state(TalkingPhotoSteps.reviewing_inputs)

        w = data.get("photo_width", 512)
        h = data.get("photo_height", 512)
        review_text = texts.TP_REVIEW_PROMPT.format(
            width=w,
            height=h,
            duration=duration,
            face_size=st.face_size,
        )

        await status_msg.edit_text(
            review_text,
            reply_markup=tp_input_review_keyboard(job_id, rev.revision_id),
        )

    except Exception as e:
        logger.exception(f"Error handling voice upload: {e}")
        await status_msg.edit_text(f"❌ បរាជ័យក្នុងការរៀបចំសំឡេង៖ {e}")

@router.callback_query(F.data.startswith("tp_confirm:"))
async def cb_confirm_inputs(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass

    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)

    # Enqueue preview render
    user_id = call.from_user.id
    enqueued = job_storage.enqueue_task(
        job_id=job_id,
        revision_id=rev_id,
        user_id=user_id,
        task_type="preview",
        feature=JobFeature.TALKING_PHOTO.value,
    )

    if not enqueued:
        await call.answer("⚠️ មិនអាចបញ្ចូលទៅក្នុងជួររង់ចាំបានទេ។ សូមព្យាយាមម្ដងទៀត។", show_alert=True)
        return

    job_storage.set_job_status(job_id, JobState.PREVIEW_QUEUED, stage="preview_queued")
    await state.set_state(TalkingPhotoSteps.rendering)

    await safe_edit_message(
        call,
        "⏳ **ការងារត្រូវបានបញ្ចូលទៅក្នុង Queue!**\n\nAI កំពុងរៀបចំបង្កើតវីដេអូគំរូ (Preview 5s)... សូមរង់ចាំបន្តិច។",
        reply_markup=job_in_progress_keyboard(job_id),
    )

@router.callback_query(F.data.startswith("tp_change_photo:"))
async def cb_change_photo(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    await state.set_state(TalkingPhotoSteps.waiting_photo)
    await safe_edit_message(call, texts.TP_PHOTO_PROMPT, reply_markup=tp_photo_prompt_keyboard())

@router.callback_query(F.data.startswith("tp_change_voice:"))
async def cb_change_voice(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    data = await state.get_data()
    job_id = data.get("job_id", "")
    await state.set_state(TalkingPhotoSteps.waiting_voice)
    await safe_edit_message(call, texts.TP_VOICE_PROMPT, reply_markup=tp_voice_prompt_keyboard(job_id))

@router.callback_query(F.data.startswith("tp_settings:"))
async def cb_tp_settings(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)
    rev = talking_photo_storage.get_revision(job_id, rev_id)
    st = rev.settings if rev else TalkingPhotoSettings()

    await safe_edit_message(
        call,
        "⚙️ **កំណត់ប៉ារ៉ាម៉ែត្រចលនាផ្ទៃមុខ (Talking Photo Settings)៖**\n\n"
        f"• ទំហំផ្ទៃមុខ៖ {st.face_size}p\n"
        f"• ចលនាក្បាល៖ {'តិច (Still)' if st.still_mode else 'ធម្មជាតិ'}\n"
        f"• ស្ទីលក្បាល៖ បែបទី {st.pose_style + 1}",
        reply_markup=tp_settings_keyboard(job_id, rev_id, st),
    )

@router.callback_query(F.data.startswith("tp_set_sz:"))
async def cb_toggle_size(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)
    rev = talking_photo_storage.get_revision(job_id, rev_id)
    if rev:
        rev.settings.face_size = 512 if rev.settings.face_size == 256 else 256
        talking_photo_storage.create_revision(
            job_id=job_id,
            image_path=rev.image_path,
            original_voice_path=rev.original_voice_path,
            settings=rev.settings,
        )
        new_rev = talking_photo_storage.get_latest_revision(job_id)
        if new_rev:
            rev_id = new_rev.revision_id
            st = new_rev.settings
            await safe_edit_message(
                call,
                f"⚙️ **បានប្តូរទំហំទៅ {st.face_size}p!**",
                reply_markup=tp_settings_keyboard(job_id, rev_id, st),
            )

@router.callback_query(F.data.startswith("tp_set_st:"))
async def cb_toggle_still(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)
    rev = talking_photo_storage.get_revision(job_id, rev_id)
    if rev:
        rev.settings.still_mode = not rev.settings.still_mode
        new_rev = talking_photo_storage.create_revision(
            job_id=job_id,
            image_path=rev.image_path,
            original_voice_path=rev.original_voice_path,
            settings=rev.settings,
        )
        st = new_rev.settings
        await safe_edit_message(
            call,
            f"🎭 **បានប្តូរចលនាក្បាល៖ {'តិច (Still)' if st.still_mode else 'ធម្មជាតិ'}**",
            reply_markup=tp_settings_keyboard(job_id, new_rev.revision_id, st),
        )

@router.callback_query(F.data.startswith("tp_set_ps:"))
async def cb_toggle_pose(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)
    rev = talking_photo_storage.get_revision(job_id, rev_id)
    if rev:
        rev.settings.pose_style = (rev.settings.pose_style + 1) % 3
        new_rev = talking_photo_storage.create_revision(
            job_id=job_id,
            image_path=rev.image_path,
            original_voice_path=rev.original_voice_path,
            settings=rev.settings,
        )
        st = new_rev.settings
        await safe_edit_message(
            call,
            f"🕺 **បានប្តូរស្ទីល៖ បែបទី {st.pose_style + 1}**",
            reply_markup=tp_settings_keyboard(job_id, new_rev.revision_id, st),
        )

@router.callback_query(F.data.startswith("tp_set_done:"))
async def cb_settings_done(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)
    data = await state.get_data()
    rev = talking_photo_storage.get_revision(job_id, rev_id)
    st = rev.settings if rev else TalkingPhotoSettings()
    dur = float(data.get("voice_duration", 0.0))

    review_text = texts.TP_REVIEW_PROMPT.format(
        width=data.get("photo_width", 512),
        height=data.get("photo_height", 512),
        duration=dur,
        face_size=st.face_size,
    )
    await safe_edit_message(call, review_text, reply_markup=tp_input_review_keyboard(job_id, rev_id))

@router.callback_query(F.data.startswith("tp_approve:"))
async def cb_approve_talking_photo(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass

    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)

    # Atomic queue claim for final render
    user_id = call.from_user.id
    enqueued = job_storage.enqueue_task(
        job_id=job_id,
        revision_id=rev_id,
        user_id=user_id,
        task_type="final",
        feature=JobFeature.TALKING_PHOTO.value,
    )

    if not enqueued:
        await call.answer("⚠️ មិនអាចបញ្ចូលទៅក្នុងជួររង់ចាំបានទេ។ សូមព្យាយាមម្ដងទៀត។", show_alert=True)
        return

    job_storage.set_job_status(job_id, JobState.FINAL_QUEUED, stage="final_queued")
    await state.set_state(TalkingPhotoSteps.rendering)

    await safe_edit_message(
        call,
        "⏳ **ការងារត្រូវបានអនុម័ត!**\n\nAI កំពុងដំណើរការបង្កើតវីដេអូពេញ... វីដេអូនឹងត្រូវផ្ញើជូនលោកអ្នកនៅទីនេះដោយស្វ័យប្រវត្តិនាពេលបន្តិចទៀត។",
        reply_markup=job_in_progress_keyboard(job_id),
    )

@router.callback_query(F.data.startswith("tp_retry:"))
async def cb_retry_talking_photo(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    _, job_id, rev_id_str = call.data.split(":")
    rev_id = int(rev_id_str)
    user_id = call.from_user.id

    job_storage.enqueue_task(
        job_id=job_id,
        revision_id=rev_id,
        user_id=user_id,
        task_type="preview",
        feature=JobFeature.TALKING_PHOTO.value,
    )
    job_storage.set_job_status(job_id, JobState.PREVIEW_QUEUED, stage="preview_queued")
    await state.set_state(TalkingPhotoSteps.rendering)
    await safe_edit_message(call, "⏳ កំពុងបង្កើតវីដេអូឡើងវិញ...", reply_markup=job_in_progress_keyboard(job_id))
