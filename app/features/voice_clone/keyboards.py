"""Keyboard builders for Voice Cloning and audio source selection."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def tp_audio_source_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Choose between user's own recorded voice and local voice cloning."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎤 ប្រើសំឡេងថតផ្ទាល់ (Recorded Voice)", callback_data=f"tp_src_rec:{job_id}")],
        [InlineKeyboardButton(text="🗣️ បម្លែងសំឡេង Voice (Voice Conversion)", callback_data=f"tp_src_vc:{job_id}")],
        [InlineKeyboardButton(text="🔄 ប្តូររូបថតផ្សេង", callback_data=f"tp_change_photo:{job_id}:1")],
        [InlineKeyboardButton(text="⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="nav_main")],
    ])

def vc_reference_prompt_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎤 ប្រើសំឡេងថតផ្ទាល់ជំនួសវិញ", callback_data=f"tp_src_rec:{job_id}")],
        [InlineKeyboardButton(text="🔄 ប្តូររូបថត", callback_data=f"tp_change_photo:{job_id}:1")],
        [InlineKeyboardButton(text="⬅️ ត្រឡប់", callback_data="nav_main")],
    ])

def vc_transcript_prompt_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎙️ ផ្ញើសំឡេងគំរូឡើងវិញ", callback_data=f"vc_re_ref:{job_id}")],
        [InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}")],
    ])

def vc_text_prompt_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ កែប្រែ Transcript សំឡេងគំរូ", callback_data=f"vc_ed_ref:{job_id}")],
        [InlineKeyboardButton(text="🎙️ ផ្ញើសំឡេងគំរូឡើងវិញ", callback_data=f"vc_re_ref:{job_id}")],
        [InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}")],
    ])

def vc_review_keyboard(job_id: str, artifact_id: str) -> InlineKeyboardMarkup:
    # All callback_data strings strictly <= 64 bytes
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ អនុម័តសំឡេង (បន្តទៅវីដេអូ)", callback_data=f"vc_appr:{job_id}:{artifact_id}")],
        [
            InlineKeyboardButton(text="✏️ កែអត្ថបទ", callback_data=f"vc_ed:{job_id}:{artifact_id}"),
            InlineKeyboardButton(text="🔄 បង្កើតម្ដងទៀត", callback_data=f"vc_rt:{job_id}:{artifact_id}"),
        ],
        [
            InlineKeyboardButton(text="🎙️ ប្តូរសំឡេងគំរូ", callback_data=f"vc_re_ref:{job_id}"),
            InlineKeyboardButton(text="🎤 ប្តូរទៅសំឡេងថត", callback_data=f"tp_src_rec:{job_id}"),
        ],
        [InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}")],
    ])
