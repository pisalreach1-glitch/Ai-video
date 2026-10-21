"""Start and main menu handlers."""
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from app.domain.states import WizardStep, JobState
from app.storage.jobs import job_storage
from app.storage.sessions import session_storage
from app.storage.preferences import preferences_storage
from app.ui import texts_km as texts
from app.ui.keyboards import (
    main_menu_keyboard,
    source_choice_keyboard,
    settings_menu_keyboard,
)

router = Router(name="start")

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    chat_id = message.chat.id

    active_job = job_storage.get_user_active_job(user_id, chat_id)
    has_active = active_job is not None

    text = texts.START_WELCOME
    if has_active:
        text += f"\n\n{texts.RESUME_NOTICE}"

    await message.answer(text, reply_markup=main_menu_keyboard(has_active_job=has_active))

@router.callback_query(F.data == "nav_main")
async def cb_main_menu(call: CallbackQuery, state: FSMContext) -> None:
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    active_job = job_storage.get_user_active_job(user_id, chat_id)
    has_active = active_job is not None

    text = texts.START_WELCOME
    if has_active:
        text += f"\n\n{texts.RESUME_NOTICE}"

    await call.message.edit_text(text, reply_markup=main_menu_keyboard(has_active_job=has_active))
    await call.answer()

@router.message(Command("help"))
@router.callback_query(F.data == "nav_help")
async def cmd_help(event: Message | CallbackQuery) -> None:
    message = event if isinstance(event, Message) else event.message
    await message.answer(texts.HELP_TEXT, reply_markup=main_menu_keyboard(has_active_job=False))
    if isinstance(event, CallbackQuery):
        await event.answer()

@router.callback_query(F.data == "nav_new_video")
async def cb_new_video(call: CallbackQuery, state: FSMContext) -> None:
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    # Create new job record
    job = job_storage.create_job(user_id=user_id, chat_id=chat_id, source_type="upload")
    session_storage.set_session(
        user_id=user_id,
        chat_id=chat_id,
        active_job_id=job.job_id,
        wizard_state="awaiting_video_source",
        state_data={"job_id": job.job_id},
    )

    await state.set_state(WizardStep.awaiting_video_source)
    await state.update_data(job_id=job.job_id)

    await call.message.edit_text(texts.SOURCE_PROMPT, reply_markup=source_choice_keyboard())
    await call.answer()

@router.callback_query(F.data == "nav_my_settings")
async def cb_my_settings(call: CallbackQuery) -> None:
    user_id = call.from_user.id
    prefs = preferences_storage.get_preferences(user_id)

    summary = (
        "⚙️ **ការកំណត់លំនាំដើមរបស់អ្នក (My Defaults)៖**\n\n"
        f"• 🎙️ សំឡេង៖ {'ស្រី (Sreymom)' if 'Sreymom' in prefs.voice else 'ប្រុស (Piseth)'}\n"
        f"• ⚡ ល្បឿន៖ {prefs.speed}\n"
        f"• 📝 Subtitle៖ {'បើក' if prefs.subtitles_enabled else 'បិទ'} ({prefs.subtitle_color}, {prefs.subtitle_position})\n"
        f"• 🔊 សំឡេងដើម៖ {'រក្សាតិចៗ (15%)' if prefs.source_audio_mode == 'low_mix' else 'ជំនួសដោយ AI'}\n"
        f"• 📐 ទំហំ៖ {prefs.aspect_ratio} ({prefs.framing_mode})\n\n"
        "💡 អ្នកអាចកែប្រែការកំណត់ទាំងនេះនៅពេលបង្កើតវីដេអូនីមួយៗ។"
    )
    await call.message.edit_text(summary, reply_markup=main_menu_keyboard(has_active_job=False))
    await call.answer()
