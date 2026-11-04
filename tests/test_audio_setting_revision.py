from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.domain.models import VoiceSettings
from app.domain.states import JobState
from app.domain.dubbing import DubbingPlan

@pytest.mark.asyncio
async def test_change_to_background_preserves_existing_dubbing_timeline(temp_job_storage, temp_workspace, monkeypatch):
    from app.handlers import settings, common
    from app.storage import dubbing
    monkeypatch.setattr(settings,'job_storage',temp_job_storage)
    monkeypatch.setattr(common,'job_storage',temp_job_storage)
    monkeypatch.setattr(dubbing,'workspace',temp_workspace)
    job=temp_job_storage.create_job(user_id=1,chat_id=2)
    rev=temp_job_storage.create_revision(job.job_id,'សួស្តី',VoiceSettings(source_audio_mode='mute'),mode='source_timed')
    temp_job_storage.set_job_status(job.job_id,JobState.AWAITING_SETTINGS)
    dubbing.save_dubbing_plan(job.job_id,rev.revision_id,DubbingPlan(source_duration_ms=8000))
    call=SimpleNamespace(data=f'aud_pick:background:{job.job_id}:{rev.revision_id}',
        from_user=SimpleNamespace(id=1),message=SimpleNamespace(chat=SimpleNamespace(id=2),edit_reply_markup=AsyncMock()),answer=AsyncMock())
    await settings.cb_aud_pick(call,SimpleNamespace(update_data=AsyncMock()))
    updated=temp_job_storage.get_latest_revision(job.job_id)
    assert updated.mode=='source_timed'
    assert updated.settings.source_audio_mode=='background'
    assert dubbing.load_dubbing_plan(job.job_id,updated.revision_id).source_duration_ms==8000
    assert updated.preview_path is None
