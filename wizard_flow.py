"""
Wizard state and navigation manager for Video Bot.
Provides:
- 5-step wizard sequence: mode -> upload -> style -> length -> review
- Non-destructive Back navigation (preserves media/settings)
- Summary and custom prompt input
- Instant transition from Wizard to processing DbJob
"""

import os
import uuid
import logging
from pathlib import Path
from typing import Tuple, Optional, Dict, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database import DatabaseManager, WizardSession, DbJob

logger = logging.getLogger(__name__)

WIZARD_STEPS = ["mode", "upload", "style", "length", "review"]


def build_wizard_view(session: WizardSession) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Constructs the text message and inline keyboard for the current wizard step.
    """
    step = session.current_step or "mode"

    if step == "mode":
        text = (
            "🧙‍♂️ **ការកំណត់វីដេអូ (Video Wizard) — ជំហានទី ១/៥៖ ជ្រើសរើស Mode**\n\n"
            "សូមជ្រើសរើសទម្រង់វីដេអូដែលលោកអ្នកចង់បង្កើត៖\n\n"
            "• **⚡ Auto Mode៖** ប្រព័ន្ធវិភាគ និងកាត់តស្វ័យប្រវត្តិតាម AI\n"
            "• **🔥 Quick Viral Pop៖** Subtitle លោតមួយពាក្យម្ដង + Smart Cuts + SFX + BGM\n"
            "• **📊 Motion Explainer៖** ប្លង់ Split-Screen, Stickers & B-Roll Overlays\n"
            "• **🤖 Custom AI Agent៖** ផ្ដល់ការណែនាំពិសេស ឬរចនាប្លង់ផ្ទាល់ខ្លួន\n\n"
            f"👉 ជម្រើសបច្ចុប្បន្ន៖ **{session.mode.upper()}**"
        )
        kb = [
            [InlineKeyboardButton(f"{'✅ ' if session.mode == 'auto' else ''}⚡ ស្វ័យប្រវត្តិ (Auto Mode)", callback_data="wiz_set:mode:auto")],
            [InlineKeyboardButton(f"{'✅ ' if session.mode == 'quick' else ''}🔥 Quick Viral Pop", callback_data="wiz_set:mode:quick")],
            [InlineKeyboardButton(f"{'✅ ' if session.mode == 'story' else ''}📊 Motion Explainer & Story", callback_data="wiz_set:mode:story")],
            [InlineKeyboardButton(f"{'✅ ' if session.mode == 'custom' else ''}🤖 Custom AI Agent", callback_data="wiz_set:mode:custom")],
            [
                InlineKeyboardButton("🏠 Main Menu", callback_data="wiz_nav:menu"),
                InlineKeyboardButton("➡️ Next", callback_data="wiz_nav:next")
            ]
        ]
        return text, InlineKeyboardMarkup(kb)

    elif step == "upload":
        has_media = bool(session.input_path and os.path.exists(session.input_path))
        if has_media:
            fname = session.original_filename or Path(session.input_path).name
            text = (
                "🧙‍♂️ **ជំហានទី ២/៥៖ វីដេអូ (Upload Video)**\n\n"
                f"✅ **វីដេអូត្រូវបានផ្ទុកឡើងរួចរាល់៖** `{fname}`\n\n"
                "💡 *លោកអ្នកអាចចុច **Next** ដើម្បីបន្ត ឬផ្ញើឯកសារវីដេអូថ្មីដើម្បីជំនួសបានគ្រប់ពេល។*"
            )
            kb = [
                [
                    InlineKeyboardButton("⬅️ Back", callback_data="wiz_nav:back"),
                    InlineKeyboardButton("➡️ Next", callback_data="wiz_nav:next")
                ],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="wiz_nav:menu")]
            ]
        else:
            text = (
                "🧙‍♂️ **ជំហានទី ២/៥៖ ផ្ញើវីដេអូ (Upload Video)**\n\n"
                "📥 **សូមផ្ញើឯកសារវីដេអូមកទីនេះ (Telegram Video / Document file)...**\n\n"
                "• គាំទ្រឯកសាររហូតដល់ **2GB (2,000MB)** តាមរយៈ MTProto\n"
                "• វីដេអូនឹងត្រូវរក្សាទុកក្នុងប្រព័ន្ធសុវត្ថិភាព Local PC\n\n"
                "*(បន្ទាប់ពីផ្ញើរួច ប្រព័ន្ធនឹងនាំលោកអ្នកទៅជំហានបន្ទាប់ដោយស្វ័យប្រវត្តិ)*"
            )
            kb = [
                [
                    InlineKeyboardButton("⬅️ Back", callback_data="wiz_nav:back"),
                    InlineKeyboardButton("🏠 Main Menu", callback_data="wiz_nav:menu")
                ]
            ]
        return text, InlineKeyboardMarkup(kb)

    elif step == "style":
        text = (
            "🧙‍♂️ **ជំហានទី ៣/៥៖ រចនាប័ទ្ម Theme & Font & ភ្លេង (Style)**\n\n"
            f"• **Theme បច្ចុប្បន្ន៖** `{session.style_theme}`\n"
            f"• **Font ខ្មែរ៖** `{session.custom_font or 'Default (Kdam Thmor)'}`\n"
            f"• **ភ្លេង BGM៖** `{session.bgm}`\n\n"
            "👉 សូមចុចជ្រើសរើសជម្រើសដែលលោកអ្នកពេញចិត្ត៖"
        )
        kb = [
            [
                InlineKeyboardButton(f"{'✅ ' if session.style_theme == 'tiktok_viral' else ''}🔥 TikTok Viral", callback_data="wiz_set:theme:tiktok_viral"),
                InlineKeyboardButton(f"{'✅ ' if session.style_theme == 'bold_yellow' else ''}🟡 Bold Gold", callback_data="wiz_set:theme:bold_yellow"),
                InlineKeyboardButton(f"{'✅ ' if session.style_theme == 'minimal_clean' else ''}⚪ Clean White", callback_data="wiz_set:theme:minimal_clean")
            ],
            [
                InlineKeyboardButton(f"{'✅ ' if session.bgm == 'lofi' else ''}☕ Lofi Chill", callback_data="wiz_set:bgm:lofi"),
                InlineKeyboardButton(f"{'✅ ' if session.bgm == 'energetic' else ''}⚡ Energetic", callback_data="wiz_set:bgm:energetic"),
                InlineKeyboardButton(f"{'✅ ' if session.bgm == 'none' else ''}🔇 គ្មានភ្លេង", callback_data="wiz_set:bgm:none")
            ],
            [
                InlineKeyboardButton("🔤 ជ្រើសរើស Font ខ្មែរបន្ថែម...", callback_data="wiz_font_menu")
            ],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="wiz_nav:back"),
                InlineKeyboardButton("➡️ Next", callback_data="wiz_nav:next")
            ],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="wiz_nav:menu")]
        ]
        return text, InlineKeyboardMarkup(kb)

    elif step == "length":
        text = (
            "🧙‍♂️ **ជំហានទី ៤/៥៖ ប្រវែងគោលដៅ (Target Video Length)**\n\n"
            "• **Auto៖** រក្សាប្រវែងវីដេអូដើម (កាត់តែ Dead Air/ភាពស្ងាត់)\n"
            "• **Short (< 30s)៖** សង្ខេប Highlight សំខាន់ៗក្រោម ៣០ វិនាទី\n"
            "• **Medium (< 60s)៖** សង្ខេប Highlight ក្រោម ៦០ វិនាទី\n"
            "• **Full Length៖** រក្សាគ្រប់ឃ្លានិយាយទាំងអស់\n\n"
            f"👉 ជម្រើសបច្ចុប្បន្ន៖ **{session.target_length}**"
        )
        kb = [
            [InlineKeyboardButton(f"{'✅ ' if session.target_length == 'auto' else ''}⚡ Auto (Smart Cut)", callback_data="wiz_set:length:auto")],
            [InlineKeyboardButton(f"{'✅ ' if session.target_length == 'short_30s' else ''}⏱️ ខ្លី Short (< 30s)", callback_data="wiz_set:length:short_30s")],
            [InlineKeyboardButton(f"{'✅ ' if session.target_length == 'medium_60s' else ''}⏱️ មធ្យម Medium (< 60s)", callback_data="wiz_set:length:medium_60s")],
            [InlineKeyboardButton(f"{'✅ ' if session.target_length == 'full' else ''}🎞️ ពេញលេញ Full", callback_data="wiz_set:length:full")],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="wiz_nav:back"),
                InlineKeyboardButton("➡️ Next", callback_data="wiz_nav:next")
            ],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="wiz_nav:menu")]
        ]
        return text, InlineKeyboardMarkup(kb)

    elif step == "review":
        has_media = bool(session.input_path and os.path.exists(session.input_path))
        fname = session.original_filename or (Path(session.input_path).name if has_media else "⚠️ មិនទាន់មានវីដេអូ")
        prompt_desc = f"«{session.custom_prompt}»" if session.custom_prompt else "គ្មាន (Standard Auto)"

        text = (
            "🧙‍♂️ **ជំហានទី ៥/៥៖ ពិនិត្យឡើងវិញ & បញ្ជាក់ (Review & Confirm)**\n\n"
            "📋 **សេចក្ដីសង្ខេបនៃការកំណត់៖**\n"
            f"• **ប្រភេទ (Mode)៖** `{session.mode}`\n"
            f"• **វីដេអូដើម៖** `{fname}`\n"
            f"• **Theme៖** `{session.style_theme}`\n"
            f"• **Font ខ្មែរ៖** `{session.custom_font or 'Default (Kdam Thmor)'}`\n"
            f"• **ភ្លេង BGM៖** `{session.bgm}`\n"
            f"• **ប្រវែងគោលដៅ៖** `{session.target_length}`\n"
            f"• **ការណែនាំពិសេស (Custom Instructions)៖**\n"
            f"  > {prompt_desc}\n\n"
            "💡 *បើចង់បន្ថែមការណែនាំពិសេស លោកអ្នកគ្រាន់តែវាយអត្ថបទផ្ញើមកទីនេះផ្ទាល់!*\n\n"
            "👉 សូមចុច **[ 🚀 បញ្ជាក់ & ចាប់ផ្តើម Render ]** ដើម្បីបញ្ចូលការងារទៅក្នុង Queue!"
        )

        if has_media:
            kb = [
                [InlineKeyboardButton("🚀 បញ្ជាក់ & ចាប់ផ្តើម Render (Confirm)", callback_data="wiz_confirm_start")],
                [
                    InlineKeyboardButton("⬅️ Back", callback_data="wiz_nav:back"),
                    InlineKeyboardButton("🏠 Main Menu", callback_data="wiz_nav:menu")
                ]
            ]
        else:
            kb = [
                [InlineKeyboardButton("📥 សូម Upload វីដេអូជាមុន", callback_data="wiz_nav:upload")],
                [
                    InlineKeyboardButton("⬅️ Back", callback_data="wiz_nav:back"),
                    InlineKeyboardButton("🏠 Main Menu", callback_data="wiz_nav:menu")
                ]
            ]
        return text, InlineKeyboardMarkup(kb)

    # Fallback to mode
    session.current_step = "mode"
    return build_wizard_view(session)


def navigate_wizard(db: DatabaseManager, user_id: int, chat_id: int, direction: str) -> WizardSession:
    """
    Handles 'next' and 'back' navigation through the 5 steps without losing media or settings.
    """
    session = db.get_or_create_wizard(user_id, chat_id)
    cur = session.current_step if session.current_step in WIZARD_STEPS else "mode"
    idx = WIZARD_STEPS.index(cur)

    if direction == "next":
        new_idx = min(len(WIZARD_STEPS) - 1, idx + 1)
    elif direction == "back":
        new_idx = max(0, idx - 1)
    elif direction in WIZARD_STEPS:
        new_idx = WIZARD_STEPS.index(direction)
    else:
        new_idx = idx

    new_step = WIZARD_STEPS[new_idx]
    return db.update_wizard(user_id, current_step=new_step, chat_id=chat_id)


def update_wizard_field(db: DatabaseManager, user_id: int, chat_id: int, field: str, value: str) -> WizardSession:
    """
    Updates a specific setting in the wizard session.
    """
    updates = {"chat_id": chat_id}
    if field == "mode":
        updates["mode"] = value
    elif field == "theme":
        updates["style_theme"] = value
    elif field == "bgm":
        updates["bgm"] = value
    elif field == "font":
        updates["custom_font"] = value if value != "default" else None
    elif field == "length":
        updates["target_length"] = value
    elif field == "prompt":
        updates["custom_prompt"] = value

    return db.update_wizard(user_id, **updates)


def create_job_from_wizard(db: DatabaseManager, session: WizardSession, temp_dir: Path) -> DbJob:
    """
    Transforms wizard session into an active/queued DbJob with a unique UUID.
    """
    job_id = str(uuid.uuid4())
    job_dir = Path(temp_dir) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    params = {
        "theme": session.style_theme,
        "custom_font": session.custom_font,
        "bgm": session.bgm,
        "target_length": session.target_length,
        "custom_prompt": session.custom_prompt,
        "original_filename": session.original_filename,
        "language": "km"
    }

    job = db.insert_job(
        job_id=job_id,
        user_id=session.user_id,
        chat_id=session.chat_id,
        mode=session.mode,
        input_path=session.input_path or "",
        job_dir=str(job_dir),
        params=params
    )
    return job
