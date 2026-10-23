"""Inline keyboards for Voice Conversion flow."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def vc_review_inputs_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Card showing Start, Replace inputs, and Cancel buttons (all <= 64 bytes)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 ចាប់ផ្តើមបម្លែង (Start Conversion)", callback_data=f"vc_start:{job_id}")],
        [
            InlineKeyboardButton(text="🎙️ ប្តូរសំឡេងគំរូ", callback_data=f"vc_ch_ref:{job_id}"),
            InlineKeyboardButton(text="🎤 ប្តូរសំឡេងនិយាយពេញ", callback_data=f"vc_ch_src:{job_id}"),
        ],
        [
            InlineKeyboardButton(text="🔄 ប្តូររូបថត", callback_data=f"tp_change_photo:{job_id}:1"),
            InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}"),
        ],
    ])

def vc_preview_keyboard(job_id: str, conversion_id: str = "") -> InlineKeyboardMarkup:
    """Actions after video preview is rendered with converted audio. Strictly <= 64 bytes."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ អនុម័ត និង Render វីដេអូពេញ", callback_data=f"vc_appr:{job_id}")],
        [InlineKeyboardButton(text="🔊 ស្តាប់សំឡេងបម្លែងពេញ (Audio)", callback_data=f"vc_play:{job_id}")],
        [
            InlineKeyboardButton(text="🔄 បម្លែងឡើងវិញ", callback_data=f"vc_retry:{job_id}"),
            InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}"),
        ],
    ])

def vc_cancel_only_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}")],
    ])
