from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import EditMessageText
from app.handlers import common
from app.services import job_messages
from app.domain.states import JobState
from app.domain.models import VoiceSettings


def network_error():
    return TelegramNetworkError(method=EditMessageText(chat_id=2,message_id=1,text="status"),message="Request timeout error")


@pytest.mark.asyncio
async def test_status_edit_retries_without_duplicate_messages(monkeypatch):
    monkeypatch.setattr(common.asyncio,"sleep",AsyncMock())
    message=SimpleNamespace(edit_text=AsyncMock(side_effect=[network_error(),network_error(),None]),answer=AsyncMock())
    await common.safe_edit_message(SimpleNamespace(message=message),"Rendering")
    assert message.edit_text.await_count==3
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_network_outage_does_not_abort_work(monkeypatch):
    monkeypatch.setattr(common.asyncio,"sleep",AsyncMock())
    message=SimpleNamespace(edit_text=AsyncMock(side_effect=network_error()),answer=AsyncMock())
    result=await common.safe_edit_message(SimpleNamespace(message=message),"Rendering")
    assert result is message
    assert message.edit_text.await_count==3
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_network_notification_does_not_abort_work():
    call=SimpleNamespace(answer=AsyncMock(side_effect=network_error()))
    await common.answer_callback_safely(call,"Working")


@pytest.mark.parametrize("status",[JobState.GENERATING_SEGMENTS,JobState.CHECKING_FIT,JobState.ASSEMBLING_TIMELINE])
def test_restart_recovers_all_dubbing_stages_and_keeps_audio(temp_job_storage,status):
    store=temp_job_storage
    job=store.create_job(user_id=1,chat_id=2)
    rev=store.create_revision(job.job_id,"សួស្តី",VoiceSettings(),mode="source_timed")
    store.update_revision(job.job_id,rev.revision_id,audio_path="saved-audio.wav",audio_duration=5)
    store.set_job_status(job.job_id,status)
    assert store.recover_interrupted_jobs()==1
    recovered=store.get_job(job.job_id)
    assert recovered.status==JobState.AWAITING_SEGMENT_REVIEW
    assert store.get_revision(job.job_id,rev.revision_id).audio_path=="saved-audio.wav"
    assert store.recover_interrupted_jobs()==0


@pytest.mark.asyncio
async def test_failed_status_stays_visible_and_cancel_is_removed():
    job_messages.bind("failed-job",SimpleNamespace(message_id=123,chat=SimpleNamespace(id=2)))
    bot=SimpleNamespace(edit_message_text=AsyncMock(),delete_message=AsyncMock())
    await job_messages.finish(bot,"failed-job","Failed; retry available",preserve=True)
    bot.delete_message.assert_not_awaited()
    bot.edit_message_text.assert_awaited_once_with(chat_id=2,message_id=123,text="Failed; retry available",reply_markup=None,parse_mode=None)
