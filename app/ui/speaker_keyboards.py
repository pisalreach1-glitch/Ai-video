"""Inline keyboard builders for multi-speaker dubbing, previews, and review alerts."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def speaker_mode_choice_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Choice between single voice and multi-speaker dubbing."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎙 សំឡេងមួយ", callback_data=f"spk_m:s:{job_id}")],
            [InlineKeyboardButton(text="👥 សំឡេងតាមអ្នកនិយាយ", callback_data=f"spk_m:m:{job_id}")],
            [InlineKeyboardButton(text="⬅️ ត្រឡប់ក្រោយ", callback_data=f"nav_source")],
        ]
    )


def speaker_card_keyboard(
    token: str,
    page: int,
    total_pages: int,
    is_confirmed: bool = False,
    open_issue_count: int = 0,
    has_full_preview: bool = False,
) -> InlineKeyboardMarkup:
    """Speaker card controls: samples, voice selection, confirmation, and review navigation."""
    rows = [
        [
            InlineKeyboardButton(text="🎬 មើលដើម", callback_data=f"spk_o:{token}"),
            InlineKeyboardButton(text="🎬 មើលសំឡេងថ្មី", callback_data=f"spk_d:{token}"),
        ],
        [
            InlineKeyboardButton(text="🎙 ជ្រើសសំឡេង AI", callback_data=f"spk_vl:{token}"),
            InlineKeyboardButton(text="✏️ ដាក់ឈ្មោះតួអង្គ", callback_data=f"spk_rn:{token}"),
        ],
    ]

    if not is_confirmed:
        rows.append([
            InlineKeyboardButton(text="✅ បញ្ជាក់សំឡេងនេះ", callback_data=f"spk_cf:{token}"),
        ])

    # Pagination row
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton(text="◀️ ថយ", callback_data=f"spk_p:{token}:{page - 1}"))
        nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton(text="បន្ទាប់ ▶️", callback_data=f"spk_p:{token}:{page + 1}"))
        rows.append(nav_row)

    # Review alerts or proceed
    action_row = []
    if open_issue_count > 0:
        action_row.append(
            InlineKeyboardButton(
                text=f"⚠️ ត្រូវពិនិត្យ ({open_issue_count})",
                callback_data=f"spk_rv:{token}:0",
            )
        )
    action_row.append(InlineKeyboardButton(text="🎬 Full Preview", callback_data=f"spk_fp:{token}"))
    rows.append(action_row)

    if has_full_preview and open_issue_count == 0:
        rows.append([
            InlineKeyboardButton(text="🚀 យល់ព្រម និង Render វីដេអូពេញ", callback_data=f"spk_ap:{token}"),
        ])

    rows.append([
        InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"spk_cx:{token}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def speaker_voice_picker_keyboard(
    token: str,
    available_voices: list[dict],
    current_voice_id: str,
) -> InlineKeyboardMarkup:
    """Voice preset picker for a speaker."""
    rows = []
    for idx, v in enumerate(available_voices):
        short_name = v.get("ShortName", "")
        gender = v.get("Gender", "")
        gender_km = "ប្រុស" if gender.lower() == "male" else "ស្រី"
        is_active = " (ជ្រើសរួច)" if short_name == current_voice_id else ""
        label = f"🎙️ {short_name} ({gender_km}){is_active}"
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"spk_vs:{token}:{idx}")
        ])

    rows.append([
        InlineKeyboardButton(text="⬅️ ត្រឡប់ក្រោយ", callback_data=f"spk_bk:{token}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def review_issue_keyboard(
    token: str,
    issue_idx: int,
    total_issues: int,
    allow_confirm: bool = False,
    segment_id: str = "",
) -> InlineKeyboardMarkup:
    """Action buttons for resolving or inspecting a specific review issue."""
    rows = [
        [
            InlineKeyboardButton(text="🎬 មើលដើម", callback_data=f"spk_io:{token}:{issue_idx}"),
            InlineKeyboardButton(text="🎬 មើលសំឡេងថ្មី", callback_data=f"spk_id:{token}:{issue_idx}"),
        ],
        [
            InlineKeyboardButton(text="👤 កែអ្នកនិយាយ", callback_data=f"spk_ie:{token}:{issue_idx}"),
            InlineKeyboardButton(text="🎙 ជ្រើសសំឡេង", callback_data=f"spk_vl:{token}"),
        ],
    ]

    action_row = []
    if segment_id:
        action_row.append(
            InlineKeyboardButton(text="✏️ កែអត្ថបទ", callback_data=f"spk_it:{token}:{segment_id}")
        )
    if allow_confirm:
        action_row.append(
            InlineKeyboardButton(text="✅ បញ្ជាក់ឈុតនេះ", callback_data=f"spk_ac:{token}:{issue_idx}")
        )
    if action_row:
        rows.append(action_row)

    # Navigation between issues
    if total_issues > 1:
        nav_row = []
        if issue_idx > 0:
            nav_row.append(InlineKeyboardButton(text="◀️ មុន", callback_data=f"spk_rv:{token}:{issue_idx - 1}"))
        nav_row.append(InlineKeyboardButton(text=f"បញ្ហា {issue_idx + 1}/{total_issues}", callback_data="noop"))
        if issue_idx < total_issues - 1:
            nav_row.append(InlineKeyboardButton(text="បន្ទាប់ ▶️", callback_data=f"spk_rv:{token}:{issue_idx + 1}"))
        rows.append(nav_row)

    rows.append([
        InlineKeyboardButton(text="⬅️ ត្រឡប់ទៅបញ្ជីអ្នកនិយាយ", callback_data=f"spk_bk:{token}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def speaker_assignment_picker_keyboard(
    token: str,
    segment_id: str,
    speakers: list[str],
) -> InlineKeyboardMarkup:
    """Pick which speaker to assign to an utterance."""
    rows = []
    for spk in speakers:
        rows.append([
            InlineKeyboardButton(text=f"👤 {spk}", callback_data=f"spk_sa:{token}:{segment_id}:{spk}")
        ])
    rows.append([
        InlineKeyboardButton(text="⬅️ ត្រឡប់ក្រោយ", callback_data=f"spk_bk:{token}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
