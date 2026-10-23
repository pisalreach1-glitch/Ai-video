"""Aiogram 3 handlers for Voice Cloning flow."""
import hashlib
import logging
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app.features.voice_clone.states import VoiceCloneSteps
from app.features.voice_clone.storage import voice_clone_storage
from app.features.voice_clone.validation import validate_reference_audio, normalize_reference_audio
from app.features.voice_clone.keyboards import (
    tp_audio_source_keyboard,
    vc_reference_prompt_keyboard,
    vc_transcript_prompt_keyboard,
    vc_text_prompt_keyboard,
    vc_review_keyboard,
)
from app.features.voice_clone.backends import get_voice_clone_backend
from app.features.talking_photo.states import TalkingPhotoSteps
from app.features.talking_photo.storage import talking_photo_storage
from app.storage.jobs import job_storage
from app.domain.features import JobFeature

logger = logging.getLogger(__name__)
router = Router(name="voice_clone")

# -------------------------------------------------------------
# 1. Audio Source Selection (Recorded vs Cloned)
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("tp_src_rec:"))
async def cb_choose_recorded_voice(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]

    await state.update_data(job_id=job_id, audio_source="recorded_voice")
    await state.set_state(TalkingPhotoSteps.waiting_voice)

    prompt = (
        "🎤 **សូមផ្ញើសំឡេង Voice របស់អ្នក (Recorded Voice)៖**\n\n"
        "• ចុច icon មេក្រូហ្វូន 🎙️ ក្នុង Telegram នេះដើម្បីថតផ្ទាល់ ឬផ្ញើឯកសារសំឡេង (.mp3, .wav, .m4a)\n"
        "• ប្រព័ន្ធគាំទ្រសំឡេងពេញលេញចាប់ពី ១០ វិនាទី រហូតដល់ ១២០ វិនាទីឡើងទៅ\n"
        "• សំឡេងនេះនឹងត្រូវប្រើប្រាស់ទាំងស្រុងក្នុងការកម្រើកមាត់ និងកាយវិការរូបថត។"
    )
    await callback.message.edit_text(prompt, reply_markup=vc_reference_prompt_keyboard(job_id))
    await callback.answer()

@router.callback_query(F.data.startswith("tp_src_cln:"))
async def cb_choose_clone_voice(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]

    # Verify backend configuration
    backend = get_voice_clone_backend()
    caps = await backend.capabilities()
    if not caps.supports_khmer:
        msg = (
            "⚠️ **មុខងារ Clone សំឡេងខ្លួនឯង (Local Voice Clone) មិនទាន់ដំណើរការទេ៖**\n\n"
            "ម៉ាស៊ីនកុំព្យូទ័រនេះមិនទាន់មានដំឡើង Engine សំឡេង Clone ភាសាខ្មែរនៅឡើយទេ "
            "(No verified local Khmer voice-cloning engine configured in `.env`)។\n\n"
            "💡 **ដំណោះស្រាយ៖** សូមជ្រើសរើស «🎤 ប្រើសំឡេងថតផ្ទាល់» (Recorded Voice) "
            "ដើម្បីបង្កើត Talking Photo ជាមួយនឹងសំឡេងផ្ទាល់របស់អ្នកបានភ្លាមៗ!"
        )
        await callback.message.edit_text(
            msg,
            reply_markup=vc_reference_prompt_keyboard(job_id),
        )
        await callback.answer()
        return

    await state.update_data(job_id=job_id, audio_source="cloned_voice")
    await state.set_state(VoiceCloneSteps.waiting_reference)

    prompt = (
        "🎙️ **ជំហានទី ១៖ ផ្ញើសំឡេងគំរូរបស់អ្នក (Reference Voice)៖**\n\n"
        "• សូមថតសំឡេង Voice ខ្លីមួយ (ប្រវែង ៥ ទៅ ៣០ វិនាទី) ឱ្យច្បាស់ និងគ្មានសំឡេងរំខាន\n"
        "• AI នឹងចម្លងរលកសំឡេង និងទឹកដមរបស់អ្នក ដើម្បីអានអត្ថបទថ្មីដែលអ្នកចង់បាន។"
    )
    await callback.message.edit_text(prompt, reply_markup=vc_reference_prompt_keyboard(job_id))
    await callback.answer()

# -------------------------------------------------------------
# 2. Collect Reference Voice
# -------------------------------------------------------------
@router.message(VoiceCloneSteps.waiting_reference, F.voice | F.audio | F.document)
async def handle_voice_reference_upload(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    job_id = data.get("job_id")
    if not job_id:
        await message.answer("❌ មិនអាចរកឃើញការងារនេះទេ។ សូមចុច /start ដើម្បីចាប់ផ្តើមឡើងវិញ។")
        return

    progress_msg = await message.answer("📥 កំពុងទាញយក និងត្រួតពិនិត្យសំឡេងគំរូ...")
    ref_dir = Path("runtime") / "jobs" / job_id / "voice_clone" / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)
    raw_dest = ref_dir / "raw_reference.ogg"

    try:
        file_obj = message.voice or message.audio or message.document
        if not file_obj:
            await progress_msg.edit_text("❌ សូមផ្ញើឯកសារសំឡេង ឬ Voice។")
            return
        await message.bot.download(file_obj.file_id, destination=raw_dest)

        dur, sr, ch = await validate_reference_audio(raw_dest, min_duration=3.0, max_duration=120.0)
        norm_dest = ref_dir / "reference.wav"
        norm_path, sha256 = await normalize_reference_audio(raw_dest, norm_dest, target_sr=24000)

        # Save reference record
        ref = voice_clone_storage.save_reference(
            owner_user_id=message.from_user.id,
            job_id=job_id,
            wav_path=str(norm_path),
            sha256=sha256,
            duration_seconds=dur,
            sample_rate=24000,
            channels=1,
        )

        await state.update_data(reference_id=ref.reference_id, reference_sha256=sha256)
        await state.set_state(VoiceCloneSteps.waiting_reference_transcript)

        await progress_msg.edit_text(
            f"✅ **ទទួលបានសំឡេងគំរូជោគជ័យ!** ({dur:.1f} វិនាទី)\n\n"
            f"📝 **ជំហានទី ២៖ សូមវាយបញ្ចូលអត្ថបទដែលបាននិយាយក្នុងសំឡេងគំរូ (Reference Transcript)៖**\n\n"
            f"• វាយអត្ថបទខ្លីដែលអ្នកបាននិយាយក្នុងសំឡេងគំរូខាងលើ\n"
            f"• ម៉ូឌែល OmniVoice ត្រូវការអត្ថបទគំរូនេះ ដើម្បីផ្ទៀងផ្ទាត់ និងចម្លងទឹកដមរបស់អ្នកបានត្រឹមត្រូវ។",
            reply_markup=vc_transcript_prompt_keyboard(job_id),
        )

    except ValueError as ve:
        await progress_msg.edit_text(f"❌ {ve}\n\nសូមផ្ញើសំឡេងគំរូឡើងវិញ។", reply_markup=vc_reference_prompt_keyboard(job_id))
    except Exception as e:
        logger.exception(f"Reference upload error: {e}")
        await progress_msg.edit_text(f"❌ ជួបបញ្ហាបច្ចេកទេស៖ {e}", reply_markup=vc_reference_prompt_keyboard(job_id))

# -------------------------------------------------------------
# 2.1. Collect Reference Transcript
# -------------------------------------------------------------
@router.message(VoiceCloneSteps.waiting_reference_transcript, F.text)
async def handle_reference_transcript_input(message: Message, state: FSMContext) -> None:
    ref_text = message.text.strip()
    if not ref_text:
        await message.answer("⚠️ សូមវាយបញ្ចូលអត្ថបទដែលមិនទទេ (Transcript cannot be empty)។")
        return

    data = await state.get_data()
    job_id = data.get("job_id")
    ref_id = data.get("reference_id")

    if not job_id or not ref_id:
        await message.answer("❌ បាត់បង់ទិន្នន័យសំឡេងគំរូ។ សូមចុច /start ដើម្បីចាប់ផ្តើមឡើងវិញ។")
        return

    voice_clone_storage.update_reference_text(ref_id, ref_text)
    await state.update_data(reference_text=ref_text)
    await state.set_state(VoiceCloneSteps.waiting_text)

    await message.answer(
        f"✅ **បានរក្សាទុក Transcript សំឡេងគំរូ៖** «{ref_text}»\n\n"
        f"✍️ **ជំហានទី ៣៖ សូមផ្ញើអត្ថបទថ្មីដែលអ្នកចង់ឱ្យសំឡេង Clone នេះនិយាយ (Target Text)៖**\n\n"
        f"• វាយអក្សរ ឬ Copy អត្ថបទថ្មីផ្ញើមកទីនេះ (គាំទ្រទាំងភាសាខ្មែរ និងអង់គ្លេស)\n"
        f"• ប្រព័ន្ធនឹងរក្សាសញ្ញាខណ្ឌ (។) និងសង្វាក់ឃ្លាឱ្យត្រឹមត្រូវ។",
        reply_markup=vc_text_prompt_keyboard(job_id),
    )

# -------------------------------------------------------------
# 3. Collect Clone Text and Enqueue Synthesis
# -------------------------------------------------------------
@router.message(VoiceCloneSteps.waiting_text, F.text)
async def handle_clone_text_input(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text:
        await message.answer("⚠️ សូមផ្ញើអត្ថបទដែលមិនទទេ (Text cannot be empty)។")
        return

    data = await state.get_data()
    job_id = data.get("job_id")
    ref_id = data.get("reference_id")
    ref_sha = data.get("reference_sha256", "")
    ref_text = data.get("reference_text", "")

    if not job_id or not ref_id:
        await message.answer("❌ បាត់បង់ទិន្នន័យសំឡេងគំរូ។ សូមចុច /start ដើម្បីចាប់ផ្តើមឡើងវិញ។")
        return

    text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    req_digest = hashlib.sha256(f"{ref_sha}:{text_sha}:{ref_text}:1.0.0".encode("utf-8")).hexdigest()

    # Create artifact
    art = voice_clone_storage.create_artifact(
        job_id=job_id,
        owner_user_id=message.from_user.id,
        reference_id=ref_id,
        reference_sha256=ref_sha,
        text=text,
        text_sha256=text_sha,
        request_digest=req_digest,
        language="km",
        backend_id="local",
        model_version="1.0.0",
        reference_text=ref_text,
    )

    # Invalidate any old audio approvals for this job
    voice_clone_storage.invalidate_approvals(job_id)

    # Enqueue task
    enqueued = job_storage.enqueue_task(
        job_id=job_id,
        revision_id=1,
        user_id=message.from_user.id,
        task_type="clone_synthesis",
        feature=JobFeature.TALKING_PHOTO.value,
        input_digest=req_digest,
    )

    if not enqueued:
        await message.answer("⚠️ បរាជ័យក្នុងការបញ្ចូលទៅក្នុងជួរការងារ (Queue is full)។ សូមសាកល្បងម្ដងទៀត។")
        return

    await state.update_data(artifact_id=art.artifact_id, request_digest=req_digest)
    await state.set_state(VoiceCloneSteps.synthesizing)

    await message.answer(
        "⏳ **ការងារត្រូវបានបញ្ចូលទៅក្នុង Queue!**\n\n"
        "AI កំពុងរៀបចំ និងបង្កើតសំឡេង Clone របស់អ្នក... សូមរង់ចាំបន្តិច។",
    )

# -------------------------------------------------------------
# 4. Audio Review & Approval
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("vc_appr:"))
async def cb_approve_clone_audio(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]
    artifact_id = parts[2]

    artifact = voice_clone_storage.get_artifact(artifact_id)
    if not artifact or artifact.state != "ready" or not artifact.wav_path:
        await callback.answer("❌ សំឡេងនេះមិនទាន់រួចរាល់ ឬមានបញ្ហា។", show_alert=True)
        return

    # Transactional approval
    approval = voice_clone_storage.approve_audio(
        job_id=job_id,
        artifact_id=artifact_id,
        request_digest=artifact.request_digest,
        wav_sha256=artifact.wav_sha256 or "",
        owner_user_id=callback.from_user.id,
    )

    # Update or create TalkingPhotoRevision with approved audio
    rev = talking_photo_storage.get_latest_revision(job_id)
    if not rev:
        await callback.answer("❌ រកមិនឃើញ revision របស់រូបថតឡើយ។", show_alert=True)
        return

    talking_photo_storage.update_revision_paths(
        job_id=job_id,
        revision_id=rev.revision_id,
        inference_wav_path=artifact.wav_path,
        master_audio_path=artifact.wav_path,
        audio_source="cloned_voice",
        approved_audio_artifact_id=artifact_id,
        audio_approval_id=approval.approval_id,
    )

    # Enqueue preview video render for talking photo
    enqueued = job_storage.enqueue_task(
        job_id=job_id,
        revision_id=rev.revision_id,
        user_id=callback.from_user.id,
        task_type="preview",
        feature=JobFeature.TALKING_PHOTO.value,
        input_digest=artifact.request_digest,
    )

    await state.set_state(TalkingPhotoSteps.rendering)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "✅ **សំឡេង Clone ត្រូវបានអនុម័តជោគជ័យ!**\n\n"
        "⏳ AI កំពុងចាប់ផ្តើម Render វីដេអូគំរូ (Talking Photo Preview 5s) ជាមួយនឹងសំឡេងដែលបានអនុម័តនេះ... សូមរង់ចាំបន្តិច។"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("vc_ed:"))
async def cb_edit_clone_text(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]

    voice_clone_storage.invalidate_approvals(job_id)
    await state.set_state(VoiceCloneSteps.waiting_text)
    await callback.message.answer(
        "📝 **សូមផ្ញើអត្ថបទថ្មីដែលអ្នកចង់កែសម្រួល៖**",
        reply_markup=vc_text_prompt_keyboard(job_id),
    )
    await callback.answer()

@router.callback_query(F.data.startswith("vc_ed_ref:"))
async def cb_edit_reference_transcript(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]

    voice_clone_storage.invalidate_approvals(job_id)
    await state.set_state(VoiceCloneSteps.waiting_reference_transcript)
    await callback.message.answer(
        "📝 **សូមវាយបញ្ចូល Transcript ថ្មីសម្រាប់សំឡេងគំរូរបស់អ្នក៖**",
        reply_markup=vc_transcript_prompt_keyboard(job_id),
    )
    await callback.answer()

@router.callback_query(F.data.startswith("vc_re_ref:"))
async def cb_change_reference_voice(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    job_id = parts[1]

    voice_clone_storage.invalidate_approvals(job_id)
    await state.set_state(VoiceCloneSteps.waiting_reference)
    await callback.message.answer(
        "🎙️ **សូមផ្ញើសំឡេងគំរូថ្មី (Reference Voice ៥ ទៅ ៣០ វិនាទី)៖**",
        reply_markup=vc_reference_prompt_keyboard(job_id),
    )
    await callback.answer()
