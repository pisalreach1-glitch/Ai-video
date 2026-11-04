"""Progress cannot hide results, undo cancellation, or fail a processing job."""
import asyncio
from unittest.mock import AsyncMock
import pytest
from app.services import progress


@pytest.mark.asyncio
async def test_slow_operation_updates_then_stops_before_result(monkeypatch):
    monkeypatch.setattr(progress, "PROGRESS_INTERVAL_SECONDS", 0.005)
    updates = []
    received = asyncio.Event()

    async def update(elapsed):
        updates.append(elapsed)
        received.set()

    async with progress.live_progress(update):
        await asyncio.wait_for(received.wait(), 1)
    count = len(updates)
    await asyncio.sleep(0.02)
    assert count >= 1
    assert len(updates) == count


@pytest.mark.asyncio
async def test_cancelled_operation_does_not_overwrite_cancel_screen(monkeypatch):
    monkeypatch.setattr(progress, "PROGRESS_INTERVAL_SECONDS", 0.005)
    update = AsyncMock()
    async with progress.live_progress(update, cancelled=lambda: True):
        await asyncio.sleep(0.02)
    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_update_failure_does_not_abort_operation(monkeypatch):
    monkeypatch.setattr(progress, "PROGRESS_INTERVAL_SECONDS", 0.005)
    update = AsyncMock(side_effect=RuntimeError("Telegram unavailable"))
    async with progress.live_progress(update):
        await asyncio.sleep(0.02)
        result = "processed"
    assert result == "processed"
    update.assert_awaited()


def test_status_text_is_human_readable_without_invented_completion():
    text = progress.progress_text(progress.stage_label("analyzing_source"), 75)
    assert "1 នាទី 15 វិនាទី" in text
    assert "ស្រង់ពាក្យ" in text
    assert "%" not in text
