"""Aiogram 3 handlers for Voice Conversion (Speech-to-Speech) flow."""
import hashlib
import logging
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from app.features.voice_conversion.states import VoiceConversionSteps
from app.features.voice_conversion.storage import voice_conversion_storage
from app.features.voice_conversion.media import validate_audio_file, normalize_to_pcm_wav
from app.features.voice_conversion.keyboards import (
    vc_review_inputs_keyboard,
    vc_preview_keyboard,
    vc_cancel_only_keyboard,
)
from app.features.talking_photo.storage import talking_photo_storage
from app.storage.jobs import job_storage
from app.domain.features import JobFeature

logger = logging.getLogger(__name__)
router = Router(name="voice_conversion")

# -------------------------------------------------------------
# 1. Start Voice Conversion Route from Talking Photo
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("tp_src_vc:") | F.data.startswith("tp_src_cln:"))
async def cb_choose_voice_conversion(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]

    await state.update_data(job_id=job_id, audio_source="converted_voice")
    await state.set_state(VoiceConversionSteps.waiting_target_reference)

    prompt = (
        "🎙️ **ជំហានទី ១៖ សូមផ្ញើសំឡេងគំរូដែលចង់ឲ្យវីដេអូមានសំឡេងដូច (Target Voice)៖**\n\n"
        "• ចុច icon មេក្រូហ្វូន 🎙️ ដើម្បីថត Voice ខ្លី (៥ ទៅ ៣០ វិនាទី) ឬផ្ញើឯកសារសំឡេង\n"
        "• AI នឹងស្រង់យកលក្ខណៈសំឡេង (Timbre & Tone) របស់សំឡេងគំរូនេះ។"
    )
    await callback.message.edit_text(prompt, reply_markup=vc_cancel_only_keyboard(job_id))
    await callback.answer()

# -------------------------------------------------------------
# 2. Collect Target Reference Voice
# -------------------------------------------------------------
@router.message(VoiceConversionSteps.waiting_target_reference, F.voice | F.audio | F.document)
async def handle_target_reference_upload(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    job_id = data.get("job_id")
    if not job_id:
        await message.answer("❌ មិនអាចរកឃើញការងារនេះទេ។ សូមចុច /start ដើម្បីចាប់ផ្តើមឡើងវិញ។")
        return

    progress_msg = await message.answer("📥 កំពុងទាញយក និងត្រួតពិនិត្យសំឡេងគំរូ (Target Voice)...")
    dest_dir = Path("runtime") / "jobs" / job_id / "conversion" / "inputs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    raw_dest = dest_dir / "raw_target_reference.ogg"

    try:
        file_obj = message.voice or message.audio or message.document
        if not file_obj:
            await progress_msg.edit_text("❌ សូមផ្ញើឯកសារសំឡេង ឬ Voice។")
            return
        await message.bot.download(file_obj.file_id, destination=raw_dest)

        dur, sr, ch = await validate_audio_file(raw_dest, min_duration=3.0, max_duration=60.0)
        norm_dest = dest_dir / "target_reference.wav"
        norm_path, sha256 = await normalize_to_pcm_wav(raw_dest, norm_dest, target_sr=24000)

        await state.update_data(
            target_reference_path=str(norm_path),
            target_reference_duration=dur,
            target_reference_sha256=sha256,
        )
        await state.set_state(VoiceConversionSteps.waiting_full_source)

        await progress_msg.edit_text(
            f"✅ **ទទួលបានសំឡេងគំរូជោគជ័យ!** ({dur:.1f} វិនាទី)\n\n"
            f"🎤 **ជំហានទី ២៖ សូមផ្ញើ Voice និយាយពេញដែលចង់ឲ្យរូបនិយាយតាម (Full Source Speech)៖**\n\n"
            f"• ចុច icon មេក្រូហ្វូន 🎙️ ក្នុង Telegram នេះដើម្បីថតផ្ទាល់ ឬផ្ញើឯកសារសំឡេង (.mp3, .wav, .m4a)\n"
            f"• គាំទ្រសំឡេងពេញលេញរហូតដល់ ១២០ វិនាទីឡើងទៅ (រក្សាពាក្យ ឃ្លា និងចង្វាក់និយាយទាំងស្រុង)។",
            reply_markup=vc_cancel_only_keyboard(job_id),
        )
    except ValueError as ve:
        await progress_msg.edit_text(f"❌ {ve}\n\nសូមផ្ញើសំឡេងគំរូឡើងវិញ។", reply_markup=vc_cancel_only_keyboard(job_id))
    except Exception as e:
        logger.exception(f"Target reference upload error: {e}")
        await progress_msg.edit_text(f"❌ ជួបបញ្ហាបច្ចេកទេស៖ {e}", reply_markup=vc_cancel_only_keyboard(job_id))

# -------------------------------------------------------------
# 3. Collect Full Source Voice and Show Review Card
# -------------------------------------------------------------
@router.message(VoiceConversionSteps.waiting_full_source, F.voice | F.audio | F.document)
async def handle_full_source_upload(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    job_id = data.get("job_id")
    ref_dur = data.get("target_reference_duration", 0.0)
    if not job_id:
        await message.answer("❌ មិនអាចរកឃើញការងារនេះទេ។ សូមចុច /start ដើម្បីចាប់ផ្តើមឡើងវិញ។")
        return

    progress_msg = await message.answer("📥 កំពុងទាញយក និងត្រួតពិនិត្យសំឡេងនិយាយពេញ (Full Source)...")
    dest_dir = Path("runtime") / "jobs" / job_id / "conversion" / "inputs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    raw_dest = dest_dir / "raw_full_source.ogg"

    try:
        file_obj = message.voice or message.audio or message.document
        if not file_obj:
            await progress_msg.edit_text("❌ សូមផ្ញើឯកសារសំឡេង ឬ Voice។")
            return
        await message.bot.download(file_obj.file_id, destination=raw_dest)

        dur, sr, ch = await validate_audio_file(raw_dest, min_duration=3.0, max_duration=300.0)
        norm_dest = dest_dir / "full_source.wav"
        norm_path, sha256 = await normalize_to_pcm_wav(raw_dest, norm_dest, target_sr=24000)

        await state.update_data(
            full_source_path=str(norm_path),
            full_source_duration=dur,
            full_source_sha256=sha256,
        )
        await state.set_state(VoiceConversionSteps.reviewing_inputs)

        card = (
            "📋 **ព័ត៌មានត្រួតពិនិត្យមុនពេលដំណើរការ (Review Conversion Inputs)៖**\n\n"
            "🖼️ **រូបថត**៖ បានទទួលជោគជ័យ\n"
            f"🎙️ **សំឡេងគំរូ (Target Voice)**៖ {ref_dur:.1f} វិនាទី (ប្រើជាសំនៀង)\n"
            f"🎤 **សំឡេងនិយាយពេញ (Full Speech)**៖ {dur:.1f} វិនាទី (ប្រើជាពាក្យ និងចង្វាក់និយាយ)\n\n"
            "⚡ ប្រព័ន្ធនឹងបម្លែងសំឡេងនិយាយពេញ ឱ្យទៅជាសំនៀងរបស់សំឡេងគំរូ ដោយមិនបាត់បង់ពាក្យ ឬចង្វាក់និយាយឡើយ!"
        )
        await progress_msg.edit_text(card, reply_markup=vc_review_inputs_keyboard(job_id))
    except ValueError as ve:
        await progress_msg.edit_text(f"❌ {ve}\n\nសូមផ្ញើសំឡេងនិយាយពេញឡើងវិញ។", reply_markup=vc_cancel_only_keyboard(job_id))
    except Exception as e:
        logger.exception(f"Full source upload error: {e}")
        await progress_msg.edit_text(f"❌ ជួបបញ្ហាបច្ចេកទេស៖ {e}", reply_markup=vc_cancel_only_keyboard(job_id))

# -------------------------------------------------------------
# 4. Start Conversion
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("vc_start:"))
async def cb_start_conversion(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]
    data = await state.get_data()

    ref_path = data.get("target_reference_path")
    ref_sha = data.get("target_reference_sha256", "")
    ref_dur = data.get("target_reference_duration", 0.0)
    src_path = data.get("full_source_path")
    src_sha = data.get("full_source_sha256", "")
    src_dur = data.get("full_source_duration", 0.0)

    if not ref_path or not src_path:
        await callback.answer("❌ បាត់បង់ទិន្នន័យសំឡេង។ សូមផ្ញើសំឡេងឡើងវិញ។", show_alert=True)
        return

    req_digest = hashlib.sha256(f"{ref_sha}:{src_sha}:seed_vc".encode("utf-8")).hexdigest()

    conv = voice_conversion_storage.create_conversion(
        job_id=job_id,
        owner_user_id=callback.from_user.id,
        target_reference_path=ref_path,
        target_reference_sha256=ref_sha,
        target_reference_duration=ref_dur,
        full_source_path=src_path,
        full_source_sha256=src_sha,
        full_source_duration=src_dur,
        request_digest=req_digest,
        backend_id="seed_vc",
    )

    enqueued = job_storage.enqueue_task(
        job_id=job_id,
        revision_id=1,
        user_id=callback.from_user.id,
        task_type="voice_conversion",
        feature=JobFeature.TALKING_PHOTO.value,
        input_digest=req_digest,
    )

    if not enqueued:
        await callback.answer("⚠️ Queue ពេញ។ សូមសាកល្បងម្ដងទៀត។", show_alert=True)
        return

    await state.set_state(VoiceConversionSteps.converting)
    await callback.message.edit_text(
        "⏳ **ការងារត្រូវបានបញ្ចូលទៅក្នុងជួរ (Queue)!**\n\n"
        "AI កំពុងបម្លែងសំឡេងនិយាយពេញរបស់អ្នក ឱ្យទៅជាសំនៀងសំឡេងគំរូ ព្រមទាំងរៀបចំ Video Preview... សូមរង់ចាំបន្តិច។",
    )
    await callback.answer()

# -------------------------------------------------------------
# 5. Play Full Converted Audio
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("vc_play:"))
async def cb_play_converted_audio(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]
    conv_id = parts[2] if len(parts) > 2 else None

    conv = voice_conversion_storage.get_conversion(conv_id) if conv_id else voice_conversion_storage.get_latest_conversion_for_job(job_id)
    if not conv or not conv.converted_wav_path or not Path(conv.converted_wav_path).exists():
        await callback.answer("❌ មិនអាចរកឃើញឯកសារសំឡេងដែលបានបម្លែងទេ។", show_alert=True)
        return

    await callback.answer("🔊 កំពុងផ្ញើសំឡេងបម្លែងពេញលេញ...")
    await callback.message.answer_audio(
        audio=FSInputFile(conv.converted_wav_path),
        caption=f"🎵 **សំឡេងដែលបានបម្លែងរួចរាល់ពេញលេញ** ({conv.converted_duration:.1f} វិនាទី)",
    )

# -------------------------------------------------------------
# 6. Approve Preview & Render Full Talking Photo Video
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("vc_appr:"))
async def cb_approve_and_render_full(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]
    conv_id = parts[2] if len(parts) > 2 else None

    conv = voice_conversion_storage.get_conversion(conv_id) if conv_id else voice_conversion_storage.get_latest_conversion_for_job(job_id)
    rev = talking_photo_storage.get_latest_revision(job_id)

    if not conv or not rev:
        await callback.answer("❌ រកមិនឃើញទិន្នន័យការងារឡើយ។", show_alert=True)
        return

    # Enqueue final full talking photo render using converted master audio
    enqueued = job_storage.enqueue_task(
        job_id=job_id,
        revision_id=rev.revision_id,
        user_id=callback.from_user.id,
        task_type="final",
        feature=JobFeature.TALKING_PHOTO.value,
        input_digest=conv.request_digest,
    )

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "🚀 **ការអនុម័តជោគជ័យ!**\n\n"
        "AI កំពុងចាប់ផ្តើម Render វីដេអូរូបថតនិយាយពេញលេញ (Full Talking Photo Render) "
        "ជាមួយសំឡេងដែលបានបម្លែង... នៅពេលរួចរាល់ Bot នឹងផ្ញើវីដេអូ MP4 ជូនអ្នកភ្លាម!"
    )
    await callback.answer()

# -------------------------------------------------------------
# 7. Change Inputs Handlers
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("vc_ch_ref:"))
async def cb_change_reference(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]
    await state.set_state(VoiceConversionSteps.waiting_target_reference)
    await callback.message.answer(
        "🎙️ **សូមផ្ញើសំឡេងគំរូថ្មី (Target Voice ៥ ទៅ ៣០ វិនាទី)៖**",
        reply_markup=vc_cancel_only_keyboard(job_id),
    )
    await callback.answer()

@router.callback_query(F.data.startswith("vc_ch_src:"))
async def cb_change_full_source(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]
    await state.set_state(VoiceConversionSteps.waiting_full_source)
    await callback.message.answer(
        "🎤 **សូមផ្ញើសំឡេងនិយាយពេញថ្មី (Full Source Speech)៖**",
        reply_markup=vc_cancel_only_keyboard(job_id),
    )
    await callback.answer()

@router.callback_query(F.data.startswith("vc_retry:"))
async def cb_retry_conversion(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]
    data = await state.get_data()
    ref_dur = data.get("target_reference_duration", 0.0)
    src_dur = data.get("full_source_duration", 0.0)
    await state.set_state(VoiceConversionSteps.reviewing_inputs)
    card = (
        "📋 **ព័ត៌មានត្រួតពិនិត្យមុនពេលដំណើរការ (Review Conversion Inputs)៖**\n\n"
        "🖼️ **រូបថត**៖ បានទទួលជោគជ័យ\n"
        f"🎙️ **សំឡេងគំរូ (Target Voice)**៖ {ref_dur:.1f} វិនាទី (ប្រើជាសំនៀង)\n"
        f"🎤 **សំឡេងនិយាយពេញ (Full Speech)**៖ {src_dur:.1f} វិនាទី (ប្រើជាពាក្យ និងចង្វាក់និយាយ)\n\n"
        "⚡ អ្នកអាចប្តូរសំឡេង ឬចុចចាប់ផ្តើមបម្លែងឡើងវិញបានភ្លាមៗ។"
    )
    await callback.message.answer(card, reply_markup=vc_review_inputs_keyboard(job_id))
    await callback.answer()

# -------------------------------------------------------------
# 8. Guidance for Incorrect Input Types (Text / Other)
# -------------------------------------------------------------
@router.message(VoiceConversionSteps.waiting_target_reference, ~F.voice & ~F.audio & ~F.document)
async def handle_target_reference_wrong_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    job_id = data.get("job_id", "")
    await message.answer(
        "⚠️ មុខងារនេះជាការបម្លែងសំឡេង (Speech-to-Speech) មិនតម្រូវឱ្យវាយអក្សរឡើយ។\n\n"
        "🎙️ សូមចុច icon មេក្រូហ្វូនដើម្បីផ្ញើសំឡេងគំរូ (Target Voice ៥ ទៅ ៣០ វិនាទី) ឬផ្ញើឯកសារសំឡេង (.mp3, .wav, .ogg)។",
        reply_markup=vc_cancel_only_keyboard(job_id) if job_id else None,
    )

@router.message(VoiceConversionSteps.waiting_full_source, ~F.voice & ~F.audio & ~F.document)
async def handle_full_source_wrong_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    job_id = data.get("job_id", "")
    await message.answer(
        "⚠️ មុខងារនេះជាការបម្លែងសំឡេង (Speech-to-Speech) មិនតម្រូវឱ្យវាយអក្សរឡើយ។\n\n"
        "🎤 សូមចុច icon មេក្រូហ្វូនដើម្បីផ្ញើសំឡេងនិយាយពេញដែលចង់ឱ្យរូបនិយាយតាម (Full Source Speech)។",
        reply_markup=vc_cancel_only_keyboard(job_id) if job_id else None,
    )
