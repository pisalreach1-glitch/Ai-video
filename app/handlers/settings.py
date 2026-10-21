"""Settings and preferences customization handlers."""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from app.domain.models import VoiceSettings
from app.storage.jobs import job_storage
from app.storage.preferences import preferences_storage
from app.services.voices import get_or_create_voice_sample
from app.handlers.common import safe_edit_message, safe_edit_reply_markup, verify_callback_job
from app.ui import texts_km as texts
from app.ui import options as opt
from app.ui.keyboards import (
    settings_menu_keyboard,
    voice_picker_keyboard,
    speed_picker_keyboard,
    subtitle_picker_keyboard,
    audio_picker_keyboard,
    format_picker_keyboard,
)

router = Router(name="settings")

def _render_settings_summary(rev) -> str:
    s = rev.settings
    voice_name = "ស្រី (Sreymom)" if "Sreymom" in s.voice else "ប្រុស (Piseth)"
    speed_name = opt.SPEEDS.get(s.speed, {}).get("label", s.speed)
    sub_status = "បើក" if s.subtitles_enabled else "បិទ"
    sub_col = "ស" if s.subtitle_color == "white" else "លឿង"
    sub_pos = "ក្រោម" if s.subtitle_position == "bottom" else "កណ្តាល"
    aud_mode = "ជំនួសដោយ AI" if s.source_audio_mode == "mute" else "រក្សាតិចៗ (15%)"
    fmt_mode = "Pad" if s.framing_mode == "fit" else "Crop"

    return texts.SETTINGS_SUMMARY.format(
        voice_label=voice_name,
        speed_label=speed_name,
        sub_status=sub_status,
        sub_color=sub_col,
        sub_pos=sub_pos,
        audio_mode_label=aud_mode,
        aspect_ratio=s.aspect_ratio,
        framing_mode=fmt_mode,
    )

@router.callback_query(F.data == "cfg_customize")
@router.callback_query(F.data.startswith("cfg_customize:"))
async def cb_settings_customize(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    job_id = data.get("job_id")
    rev_id = data.get("revision_id")

    if not job_id:
        parts = call.data.split(":")
        if len(parts) >= 3:
            job_id = parts[1]
            rev_id = int(parts[2])

    if not job_id or not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, rev_id) if rev_id else job_storage.get_latest_revision(job_id)
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    text = _render_settings_summary(rev)
    await safe_edit_message(call, text, reply_markup=settings_menu_keyboard(job_id, rev.revision_id))
    await call.answer()

# Voice Picker
@router.callback_query(F.data.startswith("set_voice:"))
async def cb_set_voice(call: CallbackQuery) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    await safe_edit_message(
        call,
        texts.SETTINGS_VOICE_PROMPT,
        reply_markup=voice_picker_keyboard(job_id, rev.revision_id, rev.settings.voice),
    )
    await call.answer()

@router.callback_query(F.data.startswith("v_pick:"))
async def cb_v_pick(call: CallbackQuery, state: FSMContext) -> None:
    _, short_voice, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    voice = opt.VOICE_SHORT_TO_NAME.get(short_voice, short_voice)
    # Create new revision on change
    new_settings = VoiceSettings.from_dict(rev.settings.to_dict())
    new_settings.voice = voice
    new_rev = job_storage.create_revision(job_id, rev.narration_text, new_settings)
    await state.update_data(revision_id=new_rev.revision_id)

    await safe_edit_reply_markup(
        call,
        reply_markup=voice_picker_keyboard(job_id, new_rev.revision_id, voice),
    )
    await call.answer("បានជ្រើសរើសសំឡេងរួចរាល់")

@router.callback_query(F.data.startswith("v_sample:"))
async def cb_v_sample(call: CallbackQuery, bot: Bot) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    await call.answer("⏳ កំពុងបង្កើតសំឡេងសាកល្បង...")
    sample_path = await get_or_create_voice_sample(rev.settings.voice)
    voice_file = FSInputFile(str(sample_path), filename=f"sample_{rev.settings.voice}.mp3")
    await bot.send_audio(
        chat_id=call.message.chat.id,
        audio=voice_file,
        caption=f"🔊 គំរូសំឡេង៖ {rev.settings.voice}",
    )

# Speed Picker
@router.callback_query(F.data.startswith("set_speed:"))
async def cb_set_speed(call: CallbackQuery) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    await safe_edit_message(
        call,
        texts.SETTINGS_SPEED_PROMPT,
        reply_markup=speed_picker_keyboard(job_id, rev.revision_id, rev.settings.speed),
    )
    await call.answer()

@router.callback_query(F.data.startswith("sp_pick:"))
async def cb_sp_pick(call: CallbackQuery, state: FSMContext) -> None:
    _, speed, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    # Create new revision on change
    new_settings = VoiceSettings.from_dict(rev.settings.to_dict())
    new_settings.speed = speed
    new_rev = job_storage.create_revision(job_id, rev.narration_text, new_settings)
    await state.update_data(revision_id=new_rev.revision_id)

    await safe_edit_reply_markup(
        call,
        reply_markup=speed_picker_keyboard(job_id, new_rev.revision_id, speed),
    )
    await call.answer("បានកំណត់ល្បឿនរួចរាល់")

# Subtitle Picker
@router.callback_query(F.data.startswith("set_sub:"))
async def cb_set_sub(call: CallbackQuery) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    await safe_edit_message(
        call,
        texts.SETTINGS_SUBTITLE_PROMPT,
        reply_markup=subtitle_picker_keyboard(
            job_id, rev.revision_id,
            rev.settings.subtitles_enabled,
            rev.settings.subtitle_color,
            rev.settings.subtitle_position,
        ),
    )
    await call.answer()

@router.callback_query(F.data.startswith("sub_tog:"))
async def cb_sub_tog(call: CallbackQuery, state: FSMContext) -> None:
    _, flag, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    new_settings = VoiceSettings.from_dict(rev.settings.to_dict())
    new_settings.subtitles_enabled = (flag == "1")
    new_rev = job_storage.create_revision(job_id, rev.narration_text, new_settings)
    await state.update_data(revision_id=new_rev.revision_id)

    await safe_edit_reply_markup(
        call,
        reply_markup=subtitle_picker_keyboard(
            job_id, new_rev.revision_id,
            new_settings.subtitles_enabled,
            new_settings.subtitle_color,
            new_settings.subtitle_position,
        ),
    )
    await call.answer()

@router.callback_query(F.data.startswith("sub_col:"))
async def cb_sub_col(call: CallbackQuery, state: FSMContext) -> None:
    _, col, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    new_settings = VoiceSettings.from_dict(rev.settings.to_dict())
    new_settings.subtitle_color = col
    new_rev = job_storage.create_revision(job_id, rev.narration_text, new_settings)
    await state.update_data(revision_id=new_rev.revision_id)

    await safe_edit_reply_markup(
        call,
        reply_markup=subtitle_picker_keyboard(
            job_id, new_rev.revision_id,
            new_settings.subtitles_enabled,
            new_settings.subtitle_color,
            new_settings.subtitle_position,
        ),
    )
    await call.answer()

@router.callback_query(F.data.startswith("sub_pos:"))
async def cb_sub_pos(call: CallbackQuery, state: FSMContext) -> None:
    _, pos, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    new_settings = VoiceSettings.from_dict(rev.settings.to_dict())
    new_settings.subtitle_position = pos
    new_rev = job_storage.create_revision(job_id, rev.narration_text, new_settings)
    await state.update_data(revision_id=new_rev.revision_id)

    await safe_edit_reply_markup(
        call,
        reply_markup=subtitle_picker_keyboard(
            job_id, new_rev.revision_id,
            new_settings.subtitles_enabled,
            new_settings.subtitle_color,
            new_settings.subtitle_position,
        ),
    )
    await call.answer()

# Audio Mix Picker
@router.callback_query(F.data.startswith("set_audio:"))
async def cb_set_audio(call: CallbackQuery) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    await safe_edit_message(
        call,
        texts.SETTINGS_AUDIO_PROMPT,
        reply_markup=audio_picker_keyboard(job_id, rev.revision_id, rev.settings.source_audio_mode),
    )
    await call.answer()

@router.callback_query(F.data.startswith("aud_pick:"))
async def cb_aud_pick(call: CallbackQuery, state: FSMContext) -> None:
    _, mode, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    new_settings = VoiceSettings.from_dict(rev.settings.to_dict())
    new_settings.source_audio_mode = mode
    new_rev = job_storage.create_revision(job_id, rev.narration_text, new_settings)
    await state.update_data(revision_id=new_rev.revision_id)

    await safe_edit_reply_markup(
        call,
        reply_markup=audio_picker_keyboard(job_id, new_rev.revision_id, mode),
    )
    await call.answer("បានកំណត់សំឡេងដើមរួចរាល់")

# Format Picker (Fixed colon parsing bug!)
@router.callback_query(F.data.startswith("set_format:"))
async def cb_set_format(call: CallbackQuery) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    await safe_edit_message(
        call,
        texts.SETTINGS_FORMAT_PROMPT,
        reply_markup=format_picker_keyboard(
            job_id, rev.revision_id,
            rev.settings.aspect_ratio,
            rev.settings.framing_mode,
        ),
    )
    await call.answer()

@router.callback_query(F.data.startswith("fmt_rat:"))
async def cb_fmt_rat(call: CallbackQuery, state: FSMContext) -> None:
    _, short_ratio, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    ratio = opt.RATIO_SHORT_TO_VAL.get(short_ratio, short_ratio)
    new_settings = VoiceSettings.from_dict(rev.settings.to_dict())
    new_settings.aspect_ratio = ratio
    new_rev = job_storage.create_revision(job_id, rev.narration_text, new_settings)
    await state.update_data(revision_id=new_rev.revision_id)

    await safe_edit_reply_markup(
        call,
        reply_markup=format_picker_keyboard(
            job_id, new_rev.revision_id,
            ratio,
            new_settings.framing_mode,
        ),
    )
    await call.answer()

@router.callback_query(F.data.startswith("fmt_frm:"))
async def cb_fmt_frm(call: CallbackQuery, state: FSMContext) -> None:
    _, framing, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    new_settings = VoiceSettings.from_dict(rev.settings.to_dict())
    new_settings.framing_mode = framing
    new_rev = job_storage.create_revision(job_id, rev.narration_text, new_settings)
    await state.update_data(revision_id=new_rev.revision_id)

    await safe_edit_reply_markup(
        call,
        reply_markup=format_picker_keyboard(
            job_id, new_rev.revision_id,
            new_settings.aspect_ratio,
            framing,
        ),
    )
    await call.answer()

# Save / Restore Defaults
@router.callback_query(F.data.startswith("set_save_def:"))
async def cb_set_save_def(call: CallbackQuery) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    preferences_storage.save_preferences(call.from_user.id, rev.settings)
    await call.answer(texts.PREFERENCES_SAVED, show_alert=True)

@router.callback_query(F.data.startswith("set_rest_def:"))
async def cb_set_rest_def(call: CallbackQuery, state: FSMContext) -> None:
    _, job_id, rev_id_str = call.data.split(":")
    if not await verify_callback_job(call, job_id):
        return

    rev = job_storage.get_revision(job_id, int(rev_id_str))
    if not rev:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    default_settings = preferences_storage.restore_preferences(call.from_user.id)
    new_rev = job_storage.create_revision(job_id, rev.narration_text, default_settings)
    await state.update_data(revision_id=new_rev.revision_id)

    text = _render_settings_summary(new_rev)
    await safe_edit_message(call, text, reply_markup=settings_menu_keyboard(job_id, new_rev.revision_id))
    await call.answer(texts.PREFERENCES_RESTORED, show_alert=True)
