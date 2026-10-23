"""Inline keyboard builders for Talking Photo feature."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.features.talking_photo.domain import TalkingPhotoSettings

def tp_photo_prompt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="nav_main")],
    ])

def tp_voice_prompt_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 ប្តូររូបថតផ្សេង", callback_data=f"tp_change_photo:{job_id}:1")],
        [InlineKeyboardButton(text="⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="nav_main")],
    ])

def tp_input_review_keyboard(job_id: str, rev_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ចាប់ផ្តើមបង្កើតវីដេអូ", callback_data=f"tp_confirm:{job_id}:{rev_id}")],
        [
            InlineKeyboardButton(text="🔄 ប្តូររូបថត", callback_data=f"tp_change_photo:{job_id}:{rev_id}"),
            InlineKeyboardButton(text="🎤 ថតសំឡេងឡើងវិញ", callback_data=f"tp_change_voice:{job_id}:{rev_id}"),
        ],
        [InlineKeyboardButton(text="⚙️ ការកំណត់ចលនា", callback_data=f"tp_settings:{job_id}:{rev_id}")],
        [InlineKeyboardButton(text="⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="nav_main")],
    ])

def tp_settings_keyboard(job_id: str, rev_id: int, settings: TalkingPhotoSettings) -> InlineKeyboardMarkup:
    size_label = f"📐 ទំហំ៖ {settings.face_size}p"
    still_label = f"🎭 ចលនាក្បាល៖ {'តិច (Still)' if settings.still_mode else 'ធម្មជាតិ'}"
    pose_label = f"🕺 ស្ទីល៖ បែបទី {settings.pose_style + 1}"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=size_label, callback_data=f"tp_set_sz:{job_id}:{rev_id}")],
        [InlineKeyboardButton(text=still_label, callback_data=f"tp_set_st:{job_id}:{rev_id}")],
        [InlineKeyboardButton(text=pose_label, callback_data=f"tp_set_ps:{job_id}:{rev_id}")],
        [InlineKeyboardButton(text="✅ រួចរាល់ (ត្រឡប់)", callback_data=f"tp_set_done:{job_id}:{rev_id}")],
    ])

def tp_preview_keyboard(job_id: str, rev_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ អនុម័ត និងទាញយកវីដេអូពេញ", callback_data=f"tp_approve:{job_id}:{rev_id}")],
        [InlineKeyboardButton(text="🔄 បង្កើតឡើងវិញ (Retry)", callback_data=f"tp_retry:{job_id}:{rev_id}")],
        [
            InlineKeyboardButton(text="🖼️ ប្តូររូបថត", callback_data=f"tp_change_photo:{job_id}:{rev_id}"),
            InlineKeyboardButton(text="🎤 ថតសំឡេងថ្មី", callback_data=f"tp_change_voice:{job_id}:{rev_id}"),
        ],
        [InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}")],
    ])

def tp_completed_keyboard(job_id: str, rev_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 ទាញយកវីដេអូ", callback_data=f"job_dl_video:{job_id}:{rev_id}")],
        [InlineKeyboardButton(text="🖼️ បង្កើត Talking Photo ថ្មី", callback_data="nav_talking_photo")],
        [InlineKeyboardButton(text="🏠 ម៉ឺនុយដើម", callback_data="nav_main")],
    ])
