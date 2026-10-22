"""Inline keyboard builders for all bot interaction stages."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.ui import options as opt

def main_menu_keyboard(has_active_job: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if has_active_job:
        buttons.append([InlineKeyboardButton(text="▶️ បន្តការងារចាស់", callback_data="nav_resume")])
    buttons.append([InlineKeyboardButton(text="🎬 បង្កើតវីដេអូ", callback_data="nav_new_video")])
    buttons.append([
        InlineKeyboardButton(text="📂 វីដេអូរបស់ខ្ញុំ", callback_data="nav_my_videos:1"),
        InlineKeyboardButton(text="⚙️ ការកំណត់របស់ខ្ញុំ", callback_data="nav_my_settings"),
    ])
    buttons.append([InlineKeyboardButton(text="❓ របៀបប្រើ", callback_data="nav_help")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def source_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Upload វីដេអូ", callback_data="src_upload")],
        [InlineKeyboardButton(text="🔗 បញ្ចូលលីងវីដេអូ", callback_data="src_link")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="nav_main")],
    ])

def caption_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ប្រើ Caption នេះ", callback_data="caption_use")],
        [InlineKeyboardButton(text="✏️ បញ្ចូលអត្ថបទថ្មី", callback_data="caption_skip")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="nav_source")],
    ])

def link_download_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}")],
    ])

def link_failure_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 សាកល្បងលីងផ្សេង", callback_data="src_link")],
        [InlineKeyboardButton(text="📤 Upload វីដេអូវិញ", callback_data="src_upload")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="nav_main")],
    ])

def mode_choice_keyboard(job_id: str, has_caption: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🎙️ Narration ថ្មី (Free Narration)", callback_data=f"mode_free:{job_id}")],
        [InlineKeyboardButton(text="🌐 បកប្រែតាមពេលវីដេអូដើម (Source-Timed Dubbing)", callback_data=f"mode_dub:{job_id}")],
    ]
    if has_caption:
        rows.append([InlineKeyboardButton(text="📝 ប្រើ Caption នៃវីដេអូ", callback_data="caption_use")])
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="nav_source")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def narration_method_keyboard(job_id: str, has_caption: bool = False) -> InlineKeyboardMarkup:
    return mode_choice_keyboard(job_id, has_caption=has_caption)

def dubbing_review_keyboard(
    job_id: str,
    revision_id: int,
    page: int,
    total_pages: int,
    segments_on_page: list[tuple[str, str]], # [(segment_id, label)]
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✅ ប្រើអត្ថបទបកប្រែនេះ", callback_data=f"d_proc:{job_id}:{revision_id}")],
    ]

    # Edit buttons for segments visible on current page
    edit_btns = [
        InlineKeyboardButton(text=f"✏️ កែ {seg_id}", callback_data=f"d_ed:{job_id}:{revision_id}:{seg_id}")
        for seg_id, _ in segments_on_page
    ]
    if edit_btns:
        rows.append(edit_btns)

    # Pagination row
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton(text="◀️ ថយ", callback_data=f"d_p:{job_id}:{revision_id}:{page - 1}"))
        nav_row.append(InlineKeyboardButton(text=f"ទំព័រ {page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton(text="បន្ទាប់ ▶️", callback_data=f"d_p:{job_id}:{revision_id}:{page + 1}"))
        rows.append(nav_row)

    rows.append([
        InlineKeyboardButton(text="🎙️ ជ្រើសសំឡេង", callback_data=f"edit_voice:{job_id}:{revision_id}"),
        InlineKeyboardButton(text="📊 មើលការតម្រឹម", callback_data=f"d_rep:{job_id}:{revision_id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="🤖 បកប្រែដោយ AI ឡើងវិញ", callback_data=f"d_ai:{job_id}:{revision_id}"),
        InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def dubbing_fit_resolution_keyboard(
    job_id: str,
    revision_id: int,
    segment_id: str,
    overlong_count: int = 1,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🤖 សង្ខេបឃ្លានេះដោយ AI", callback_data=f"d_sh:{job_id}:{revision_id}:{segment_id}")],
    ]
    if overlong_count > 1:
        rows.append([
            InlineKeyboardButton(text=f"⚡ សង្ខេបឃ្លាវែងទាំង {overlong_count} ដោយ AI", callback_data=f"d_sha:{job_id}:{revision_id}")
        ])
    rows.extend([
        [InlineKeyboardButton(text="✏️ កែឃ្លានេះ (Edit Segment)", callback_data=f"d_ed:{job_id}:{revision_id}:{segment_id}")],
        [InlineKeyboardButton(text="🔄 សាកល្បងម្ដងទៀត (Regenerate)", callback_data=f"d_proc:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text="⬅️ ត្រឡប់ទៅពិនិត្យឡើងវិញ", callback_data=f"d_p:{job_id}:{revision_id}:1")],
        [InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def translation_review_keyboard(job_id: str, revision_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎙️ បង្កើតសំឡេងអាន AI", callback_data=f"set_proceed:{job_id}:{revision_id}")],
        [
            InlineKeyboardButton(text="✏️ កែអត្ថបទ", callback_data=f"edit_text:{job_id}:{revision_id}"),
            InlineKeyboardButton(text="⚙️ កែ Settings", callback_data=f"edit_voice:{job_id}:{revision_id}"),
        ],
        [InlineKeyboardButton(text="🔄 បកប្រែឡើងវិញ", callback_data=f"act_trans:{job_id}")],
        [InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}")],
    ])

def narration_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ប្រើអត្ថបទនេះ", callback_data="narration_confirm")],
        [InlineKeyboardButton(text="✏️ ប្ដូរអត្ថបទ", callback_data="narration_replace")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="nav_source")],
    ])

def after_narration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ប្រើការកំណត់របស់ខ្ញុំ", callback_data="cfg_use_defaults")],
        [InlineKeyboardButton(text="⚙️ កែការកំណត់", callback_data="cfg_customize")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="nav_narration")],
    ])

def settings_menu_keyboard(job_id: str, revision_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎙️ សំឡេង", callback_data=f"set_voice:{job_id}:{revision_id}"),
            InlineKeyboardButton(text="⚡ ល្បឿន", callback_data=f"set_speed:{job_id}:{revision_id}"),
        ],
        [
            InlineKeyboardButton(text="📝 Subtitle", callback_data=f"set_sub:{job_id}:{revision_id}"),
            InlineKeyboardButton(text="🔊 សំឡេងដើម", callback_data=f"set_audio:{job_id}:{revision_id}"),
        ],
        [
            InlineKeyboardButton(text="📐 ទំហំ & កាត់", callback_data=f"set_format:{job_id}:{revision_id}"),
        ],
        [
            InlineKeyboardButton(text="💾 Save as My Defaults", callback_data=f"set_save_def:{job_id}:{revision_id}"),
            InlineKeyboardButton(text="↩️ Restore Defaults", callback_data=f"set_rest_def:{job_id}:{revision_id}"),
        ],
        [
            InlineKeyboardButton(text="✅ បន្តទៅមុខ (Proceed)", callback_data=f"set_proceed:{job_id}:{revision_id}"),
            InlineKeyboardButton(text="⬅️ Back", callback_data="nav_narration"),
        ],
    ])

def voice_picker_keyboard(job_id: str, revision_id: int, current_voice: str) -> InlineKeyboardMarkup:
    sreymom_mark = " ✓" if current_voice == opt.VOICE_FEMALE else ""
    piseth_mark = " ✓" if current_voice == opt.VOICE_MALE else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👩 សំឡេងស្រី (Sreymom){sreymom_mark}", callback_data=f"v_pick:f:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text=f"👨 សំឡេងប្រុស (Piseth){piseth_mark}", callback_data=f"v_pick:m:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text="🔊 សាកស្ដាប់សំឡេង (Sample)", callback_data=f"v_sample:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text="⬅️ ត្រឡប់ក្រោយ", callback_data=f"cfg_customize:{job_id}:{revision_id}")],
    ])

def speed_picker_keyboard(job_id: str, revision_id: int, current_speed: str) -> InlineKeyboardMarkup:
    slow_mark = " ✓" if current_speed == opt.SPEED_SLOW else ""
    normal_mark = " ✓" if current_speed == opt.SPEED_NORMAL else ""
    fast_mark = " ✓" if current_speed == opt.SPEED_FAST else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🐢 យឺត (-15%){slow_mark}", callback_data=f"sp_pick:{opt.SPEED_SLOW}:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text=f"▶️ ធម្មតា (1.0x){normal_mark}", callback_data=f"sp_pick:{opt.SPEED_NORMAL}:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text=f"⚡ លឿន (+15%){fast_mark}", callback_data=f"sp_pick:{opt.SPEED_FAST}:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text="⬅️ ត្រឡប់ក្រោយ", callback_data=f"cfg_customize:{job_id}:{revision_id}")],
    ])

def subtitle_picker_keyboard(
    job_id: str,
    revision_id: int,
    enabled: bool,
    color: str,
    position: str
) -> InlineKeyboardMarkup:
    toggle_text = "✅ បើក Subtitle" if enabled else "❌ បិទ Subtitle"
    toggle_action = "0" if enabled else "1"
    white_mark = " ✓" if color == opt.SUBTITLE_COLOR_WHITE else ""
    yellow_mark = " ✓" if color == opt.SUBTITLE_COLOR_YELLOW else ""
    bottom_mark = " ✓" if position == opt.SUBTITLE_POS_BOTTOM else ""
    middle_mark = " ✓" if position == opt.SUBTITLE_POS_MIDDLE else ""

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"ស្ថានភាព៖ {toggle_text}", callback_data=f"sub_tog:{toggle_action}:{job_id}:{revision_id}")],
        [
            InlineKeyboardButton(text=f"⚪ ពណ៌ស{white_mark}", callback_data=f"sub_col:{opt.SUBTITLE_COLOR_WHITE}:{job_id}:{revision_id}"),
            InlineKeyboardButton(text=f"🟡 ពណ៌លឿង{yellow_mark}", callback_data=f"sub_col:{opt.SUBTITLE_COLOR_YELLOW}:{job_id}:{revision_id}"),
        ],
        [
            InlineKeyboardButton(text=f"⬇️ ខាងក្រោម{bottom_mark}", callback_data=f"sub_pos:{opt.SUBTITLE_POS_BOTTOM}:{job_id}:{revision_id}"),
            InlineKeyboardButton(text=f"⏸️ កណ្តាល{middle_mark}", callback_data=f"sub_pos:{opt.SUBTITLE_POS_MIDDLE}:{job_id}:{revision_id}"),
        ],
        [InlineKeyboardButton(text="⬅️ ត្រឡប់ក្រោយ", callback_data=f"cfg_customize:{job_id}:{revision_id}")],
    ])

def audio_picker_keyboard(job_id: str, revision_id: int, current_mode: str) -> InlineKeyboardMarkup:
    mute_mark = " ✓" if current_mode == opt.AUDIO_MUTE else ""
    low_mark = " ✓" if current_mode == opt.AUDIO_LOW_MIX else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔇 ជំនួសដោយសំឡេង AI (Default){mute_mark}", callback_data=f"aud_pick:{opt.AUDIO_MUTE}:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text=f"🔉 រក្សាសំឡេងដើមតិចៗ (15%){low_mark}", callback_data=f"aud_pick:{opt.AUDIO_LOW_MIX}:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text="⬅️ ត្រឡប់ក្រោយ", callback_data=f"cfg_customize:{job_id}:{revision_id}")],
    ])

def format_picker_keyboard(
    job_id: str,
    revision_id: int,
    current_ratio: str,
    current_framing: str
) -> InlineKeyboardMarkup:
    orig_mark = " ✓" if current_ratio == opt.RATIO_ORIGINAL else ""
    vert_mark = " ✓" if current_ratio == opt.RATIO_VERTICAL else ""
    sq_mark = " ✓" if current_ratio == opt.RATIO_SQUARE else ""
    fit_mark = " ✓" if current_framing == opt.FRAMING_FIT else ""
    fill_mark = " ✓" if current_framing == opt.FRAMING_FILL else ""

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="-- សមាមាត្រ (Aspect Ratio) --", callback_data="noop")],
        [
            InlineKeyboardButton(text=f"📐 ដើម{orig_mark}", callback_data=f"fmt_rat:orig:{job_id}:{revision_id}"),
            InlineKeyboardButton(text=f"📱 9:16{vert_mark}", callback_data=f"fmt_rat:vert:{job_id}:{revision_id}"),
            InlineKeyboardButton(text=f"⏹️ 1:1{sq_mark}", callback_data=f"fmt_rat:sq:{job_id}:{revision_id}"),
        ],
        [InlineKeyboardButton(text="-- របៀបតម្រឹម (Framing) --", callback_data="noop")],
        [
            InlineKeyboardButton(text=f"⬛ បន្ថែមគែម (Fit Pad){fit_mark}", callback_data=f"fmt_frm:{opt.FRAMING_FIT}:{job_id}:{revision_id}"),
            InlineKeyboardButton(text=f"✂️ កាត់ពេញ (Crop Fill){fill_mark}", callback_data=f"fmt_frm:{opt.FRAMING_FILL}:{job_id}:{revision_id}"),
        ],
        [InlineKeyboardButton(text="⬅️ ត្រឡប់ក្រោយ", callback_data=f"cfg_customize:{job_id}:{revision_id}")],
    ])

def audio_review_keyboard(job_id: str, revision_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ បន្តទៅ Video Preview", callback_data=f"aud_next:{job_id}:{revision_id}")],
        [
            InlineKeyboardButton(text="✏️ កែអត្ថបទ", callback_data=f"edit_text:{job_id}:{revision_id}"),
            InlineKeyboardButton(text="🎙️ ប្ដូរសំឡេង", callback_data=f"edit_voice:{job_id}:{revision_id}"),
        ],
        [
            InlineKeyboardButton(text="⚡ ប្ដូរល្បឿន", callback_data=f"edit_speed:{job_id}:{revision_id}"),
            InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}"),
        ],
    ])

def duration_choice_keyboard(job_id: str, revision_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧊 ពន្យារូបភាពចុងក្រោយ (Extend)", callback_data=f"dur_pick:{opt.DURATION_EXTEND}:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text="🔁 ចាក់វីដេអូឡើងវិញ (Loop)", callback_data=f"dur_pick:{opt.DURATION_LOOP}:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text="✏️ កាត់បន្ថយអត្ថបទ (Shorten)", callback_data=f"edit_text:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}")],
    ])

def video_preview_review_keyboard(job_id: str, revision_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ បង្កើតវីដេអូពេញ (Approve)", callback_data=f"apprv_final:{job_id}:{revision_id}")],
        [
            InlineKeyboardButton(text="📝 កែ Subtitle", callback_data=f"edit_sub:{job_id}:{revision_id}"),
            InlineKeyboardButton(text="🎨 កែទំហំ/ស្ទីល", callback_data=f"edit_fmt:{job_id}:{revision_id}"),
        ],
        [
            InlineKeyboardButton(text="✏️ កែអត្ថបទ", callback_data=f"edit_text:{job_id}:{revision_id}"),
            InlineKeyboardButton(text="❌ បោះបង់", callback_data=f"job_cancel:{job_id}"),
        ],
    ])

def job_in_progress_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ បោះបង់ការងារ (Cancel)", callback_data=f"job_cancel:{job_id}")],
    ])

def job_completed_keyboard(job_id: str, has_srt: bool = True) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📥 ទាញយកវីដេអូ (MP4)", callback_data=f"dl_video:{job_id}")],
    ]
    if has_srt:
        buttons.append([InlineKeyboardButton(text="📄 ទាញយក Subtitle (SRT)", callback_data=f"dl_srt:{job_id}")])
    buttons.append([
        InlineKeyboardButton(text="🔁 កែសម្រួលវីដេអូនេះ", callback_data=f"job_edit:{job_id}"),
        InlineKeyboardButton(text="🆕 វីដេអូថ្មី", callback_data="nav_new_video"),
    ])
    buttons.append([InlineKeyboardButton(text="🏠 ម៉ឺនុយដើម", callback_data="nav_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def delivery_retry_keyboard(job_id: str, revision_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 ព្យាយាមផ្ញើម្តងទៀត", callback_data=f"retry_dlv:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text="🏠 ម៉ឺនុយដើម", callback_data="nav_main")],
    ])

def interrupted_job_keyboard(job_id: str, revision_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 សាកល្បងម្ដងទៀត (Retry)", callback_data=f"retry_job:{job_id}:{revision_id}")],
        [InlineKeyboardButton(text="❌ បោះបង់ និងចាប់ផ្ដើមថ្មី", callback_data=f"job_cancel:{job_id}")],
    ])

def history_keyboard(page: int, total_pages: int, job_items: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for item in job_items:
        jid = item["job_id"]
        status = item["status"]
        status_icon = "✅" if status == "completed" else ("❌" if status == "failed" else "⏳")
        date_str = item.get("date_str", jid[:8])
        btn_text = f"{status_icon} {date_str} ({jid[:6]}..)"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"hist_job:{jid}")])

    # Pagination row
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="◀️ ថយក្រោយ", callback_data=f"nav_my_videos:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"ទំព័រ {page}/{max(1, total_pages)}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="បន្ទាប់ ▶️", callback_data=f"nav_my_videos:{page + 1}"))

    buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="🏠 ម៉ឺនុយដើម", callback_data="nav_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
