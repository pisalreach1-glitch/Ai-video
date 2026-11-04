from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.domain.states import JobState, WizardStep
from app.domain.models import VoiceSettings
from app.handlers import previews


@pytest.mark.asyncio
async def test_ready_audio_queues_full_video_without_preview_approval(temp_job_storage,monkeypatch):
    store=temp_job_storage
    monkeypatch.setattr(previews,"job_storage",store)
    edit=AsyncMock()
    monkeypatch.setattr(previews,"safe_edit_message",edit)
    job=store.create_job(user_id=1,chat_id=2)
    rev=store.create_revision(job.job_id,"សួស្តី",VoiceSettings())
    store.set_job_status(job.job_id,JobState.AWAITING_AUDIO_REVIEW)
    call=SimpleNamespace(from_user=SimpleNamespace(id=1),answer=AsyncMock())
    state=SimpleNamespace(set_state=AsyncMock())
    await previews._start_full_video(call,job.job_id,rev.revision_id,state,acknowledge=False)
    task=store.claim_next_task()
    assert task["task_type"]=="final"
    assert store.get_job(job.job_id).status==JobState.FINAL_QUEUED
    state.set_state.assert_awaited_once_with(WizardStep.rendering_in_progress)
    call.answer.assert_not_awaited()
    assert not store.get_revision(job.job_id,rev.revision_id).preview_path


@pytest.mark.asyncio
@pytest.mark.parametrize("status",[JobState.CANCELLED,JobState.RENDERING,JobState.UPLOADING,JobState.COMPLETED])
async def test_full_video_handoff_does_not_restart_cancelled_or_active_work(temp_job_storage,monkeypatch,status):
    store=temp_job_storage
    monkeypatch.setattr(previews,"job_storage",store)
    monkeypatch.setattr(previews,"safe_edit_message",AsyncMock())
    job=store.create_job(user_id=1,chat_id=2)
    rev=store.create_revision(job.job_id,"text",VoiceSettings())
    store.set_job_status(job.job_id,status)
    call=SimpleNamespace(from_user=SimpleNamespace(id=1),answer=AsyncMock())
    await previews._start_full_video(call,job.job_id,rev.revision_id,None)
    assert store.claim_next_task() is None
    assert store.get_job(job.job_id).status==status
