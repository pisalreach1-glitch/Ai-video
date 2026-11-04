from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
from app.services import job_messages as status


@pytest.fixture(autouse=True)
def clear_messages():
    status._messages.clear()
    yield
    status._messages.clear()


def message(media=False):
    return SimpleNamespace(message_id=12, chat=SimpleNamespace(id=34), video=True if media else None)


@pytest.mark.asyncio
async def test_handler_message_reused_across_render_and_upload():
    bot = SimpleNamespace(edit_message_text=AsyncMock(), send_message=AsyncMock(), delete_message=AsyncMock())
    status.bind("job", message())
    await status.update(bot, 34, "job", "Rendering")
    await status.update(bot, 34, "job", "Uploading")
    assert bot.edit_message_text.await_count == 2
    bot.send_message.assert_not_awaited()
    await status.finish(bot, "job", "Done")
    bot.delete_message.assert_awaited_once_with(chat_id=34, message_id=12)
    assert "job" not in status._messages


@pytest.mark.asyncio
async def test_preview_caption_reused_and_cancel_removed_at_completion():
    bot = SimpleNamespace(edit_message_caption=AsyncMock(), send_message=AsyncMock())
    status.bind("job", message(True))
    await status.update(bot, 34, "job", "Uploading", "cancel-buttons")
    await status.finish(bot, "job", "Done")
    assert bot.edit_message_caption.await_args.kwargs["reply_markup"] is None
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_network_failure_does_not_create_another_panel():
    bot = SimpleNamespace(edit_message_text=AsyncMock(side_effect=TimeoutError()), send_message=AsyncMock())
    status.bind("job", message())
    with pytest.raises(TimeoutError):
        await status.update(bot, 34, "job", "Rendering")
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_deleted_status_replaced_once_then_reused():
    bot = SimpleNamespace(edit_message_text=AsyncMock(side_effect=TelegramBadRequest(method=EditMessageText(chat_id=34,message_id=12,text="test"),message="message to edit not found")), send_message=AsyncMock(return_value=message()))
    status.bind("job", message())
    await status.update(bot, 34, "job", "Rendering")
    bot.edit_message_text.side_effect = None
    await status.update(bot, 34, "job", "Uploading")
    bot.send_message.assert_awaited_once()
