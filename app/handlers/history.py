"""User job history and video management handlers."""
import math
import time
from pathlib import Path
from aiogram import Router, F
from aiogram.types import CallbackQuery
from app.config import config
from app.domain.states import JobState
from app.storage.jobs import job_storage
from app.handlers.common import safe_edit_message
from app.ui import texts_km as texts
from app.ui.keyboards import history_keyboard, job_completed_keyboard, main_menu_keyboard

router = Router(name="history")

PAGE_SIZE = 5

@router.callback_query(F.data.startswith("nav_my_videos:"))
async def cb_my_videos_page(call: CallbackQuery) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    _, page_str = call.data.split(":")
    page = max(1, int(page_str))
    user_id = call.from_user.id

    offset = (page - 1) * PAGE_SIZE
    jobs, total = job_storage.list_user_jobs(user_id=user_id, limit=PAGE_SIZE, offset=offset)

    if total == 0:
        await safe_edit_message(
            call,
            texts.HISTORY_EMPTY,
            reply_markup=main_menu_keyboard(has_active_job=False),
        )
        return

    total_pages = math.ceil(total / PAGE_SIZE)
    items = []
    for j in jobs:
        created_struct = time.localtime(j.created_at) if j.created_at > 0 else time.localtime()
        date_str = time.strftime("%d/%m %H:%M", created_struct)
        items.append({
            "job_id": j.job_id,
            "status": j.status.value,
            "date_str": date_str,
        })

    text = texts.HISTORY_TITLE.format(page=page, total_pages=total_pages)
    await safe_edit_message(
        call,
        text,
        reply_markup=history_keyboard(page=page, total_pages=total_pages, job_items=items),
    )

@router.callback_query(F.data.startswith("hist_job:"))
async def cb_history_job_detail(call: CallbackQuery) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    _, job_id = call.data.split(":")
    job = job_storage.get_job(job_id)
    if not job:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return

    rev = job_storage.get_latest_revision(job_id)
    has_final = bool(rev and rev.final_path and Path(rev.final_path).exists())
    has_srt = bool(rev and rev.subtitles_srt and Path(rev.subtitles_srt).exists())

    status_str = "ជោគជ័យ (Completed)" if job.status == JobState.COMPLETED else job.status.value
    msg = (
        f"🎬 **ព័ត៌មានលម្អិតវីដេអូ ({job.job_id[:8]}..)៖**\n\n"
        f"• ស្ថានភាព៖ {status_str}\n"
        f"• ប្រភព៖ {job.source_type}\n"
    )

    if not has_final:
        msg += f"\n{texts.HISTORY_EXPIRED.format(retention=config.job_retention_hours)}"

    await safe_edit_message(
        call,
        msg,
        reply_markup=job_completed_keyboard(job_id=job_id, has_srt=has_srt),
    )
    await call.answer()
