"""Narration text entry, auto-translation, and confirmation handlers."""
import logging
import unicodedata
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from app.config import config
from app.domain.states import WizardStep, JobState
from app.storage.jobs import job_storage
from app.storage.preferences import preferences_storage
from app.handlers.common import safe_edit_message, verify_callback_job
from app.ui import texts_km as texts
from app.ui.keyboards import (
    narration_confirm_keyboard,
    after_narration_keyboard,
    settings_menu_keyboard,
    narration_method_keyboard,
    translation_review_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name="narration")

@router.callback_query(F.data.startswith("act_text:"))
async def cb_choose_manual_text(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id = call.data.split(":")
    if not await verify_callback_job(call, job_id, allowed_states=(JobState.AWAITING_TEXT,)):
        return

    await state.update_data(job_id=job_id)
    await state.set_state(WizardStep.awaiting_narration_text)
    await safe_edit_message(
        call,
        texts.NARRATION_PROMPT.format(max_chars=config.max_narration_chars),
    )
    await call.answer()

@router.callback_query(F.data.startswith("act_trans:"))
async def cb_start_auto_translation(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id = call.data.split(":")
    if not await verify_callback_job(call, job_id, allowed_states=(JobState.AWAITING_TEXT, JobState.AWAITING_SETTINGS)):
        return

    job = job_storage.get_job(job_id)
    if not job or not job.source_path:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    duration = job.source_media_info.duration if job.source_media_info else 0.0

    # Show progress message
    await safe_edit_message(
        call,
        texts.TRANSLATING_PROGRESS.format(duration=duration),
    )
    await call.answer("⏳ កំពុងដំណើរការបកប្រែ...")

    from app.services.translator import translate_video_to_khmer
    try:
        translated_text = await translate_video_to_khmer(
            video_path=Path(job.source_path),
            video_duration=duration,
            job_id=job_id,
        )

        if not translated_text or translated_text == "NO_SPEECH_DETECTED":
            await safe_edit_message(
                call,
                texts.NO_SPEECH_FOUND,
                reply_markup=narration_method_keyboard(job_id, has_caption=False),
            )
            return

        # Success: store into state and create revision with user's saved preferences
        user_id = call.from_user.id
        prefs = preferences_storage.get_preferences(user_id)
        rev = job_storage.create_revision(
            job_id=job_id,
            narration_text=translated_text,
            settings=prefs,
        )
        await state.update_data(job_id=job_id, revision_id=rev.revision_id, narration_text=translated_text)
        job_storage.set_job_status(job_id, JobState.AWAITING_SETTINGS)

        preview_text = translated_text[:1000] + ("..." if len(translated_text) > 1000 else "")
        await safe_edit_message(
            call,
            texts.TRANSLATION_SUCCESS.format(
                duration=duration,
                text=preview_text,
            ),
            reply_markup=translation_review_keyboard(job_id, rev.revision_id),
        )

    except Exception as e:
        logger.exception(f"Translation failed for job {job_id}: {e}")
        await safe_edit_message(
            call,
            f"❌ ការបកប្រែវីដេអូបរាជ័យ៖ {e}\n\nសូមព្យាយាមម្ដងទៀត ឬវាយអត្ថបទអានដោយខ្លួនឯង។",
            reply_markup=narration_method_keyboard(job_id, has_caption=False),
        )

@router.message(WizardStep.awaiting_narration_text, F.text)
@router.message(WizardStep.editing_narration_text, F.text)
async def handle_narration_text(message: Message, state: FSMContext) -> None:
    # Preserve Khmer character clusters by normalizing to Unicode NFC
    raw_text = message.text or ""
    normalized_text = unicodedata.normalize("NFC", raw_text).strip()

    if not normalized_text:
        await message.reply(texts.NARRATION_EMPTY)
        return

    char_count = len(normalized_text)
    if char_count > config.max_narration_chars:
        await message.reply(
            texts.NARRATION_TOO_LONG.format(
                len=char_count,
                max_chars=config.max_narration_chars,
            )
        )
        return

    await state.update_data(narration_text=normalized_text)
    await state.set_state(WizardStep.editing_narration_text)

    await message.reply(
        texts.NARRATION_CONFIRM.format(
            text=normalized_text,
            chars=char_count,
            max_chars=config.max_narration_chars,
        ),
        reply_markup=narration_confirm_keyboard(),
    )

@router.callback_query(F.data == "narration_replace")
async def cb_narration_replace(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    await state.set_state(WizardStep.awaiting_narration_text)
    await safe_edit_message(
        call,
        texts.NARRATION_PROMPT.format(max_chars=config.max_narration_chars),
    )

@router.callback_query(F.data == "narration_confirm")
async def cb_narration_confirm(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    data = await state.get_data()
    job_id = data.get("job_id")
    narration_text = data.get("narration_text", "")

    user_id = call.from_user.id
    prefs = preferences_storage.get_preferences(user_id)

    # Create initial revision with user's saved preferences
    rev = job_storage.create_revision(
        job_id=job_id,
        narration_text=narration_text,
        settings=prefs,
    )
    await state.update_data(revision_id=rev.revision_id)
    job_storage.set_job_status(job_id, JobState.AWAITING_SETTINGS)

    await state.set_state(WizardStep.customizing_settings)
    await safe_edit_message(
        call,
        texts.AFTER_NARRATION_PROMPT,
        reply_markup=after_narration_keyboard(),
    )

@router.callback_query(F.data == "nav_narration")
async def cb_nav_narration(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    await state.set_state(WizardStep.awaiting_narration_text)
    await safe_edit_message(
        call,
        texts.NARRATION_PROMPT.format(max_chars=config.max_narration_chars),
    )
