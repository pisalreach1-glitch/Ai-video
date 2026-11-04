from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendVideo
from app.domain.models import VoiceSettings, MediaInfo
from app.domain.states import JobState
from app.domain.features import QueueTask, JobFeature
from app.features.video_voiceover import adapter


@pytest.mark.asyncio
async def test_delivered_preview_timeout_keeps_approval_available(temp_job_storage,temp_workspace,monkeypatch):
    store = temp_job_storage
    monkeypatch.setattr(adapter,"job_storage",store)
    monkeypatch.setattr(adapter,"workspace",temp_workspace)
    job = store.create_job(user_id=1,chat_id=2)
    store.set_job_source(job.job_id,"source.mp4",MediaInfo(640,360,5,True))
    rev = store.create_revision(job.job_id,"text",VoiceSettings(),mode="free_narration")
    store.update_revision(job.job_id,rev.revision_id,audio_path="voice.wav",audio_duration=5)
    async def render(**kwargs):
        kwargs["output_preview_path"].write_bytes(b"preview")
    monkeypatch.setattr("app.services.previews.render_preview_video",render)
    bot = SimpleNamespace(send_video=AsyncMock(side_effect=TelegramNetworkError(method=SendVideo(chat_id=2,video="file"),message="Request timeout error")),send_message=AsyncMock())
    worker = SimpleNamespace(get_bot=lambda:bot,is_cancelled=lambda _:False,register_pid=lambda *args:None)
    await adapter.video_voiceover_pipeline.run(QueueTask(job_id=job.job_id,revision_id=rev.revision_id,feature=JobFeature.VIDEO_VOICEOVER.value,task_type="preview",user_id=1),worker)
    assert store.get_job(job.job_id).status == JobState.AWAITING_APPROVAL
    assert store.get_revision(job.job_id,rev.revision_id).preview_path
    bot.send_video.assert_awaited_once()
    bot.send_message.assert_not_awaited()
    assert bot.send_video.await_args.kwargs["request_timeout"] == 180


@pytest.mark.asyncio
async def test_blocked_final_displays_fit_resolution_instead_of_silent_failure(temp_job_storage,temp_workspace,monkeypatch):
    from app.domain.dubbing import DubbingPlan,SourceSegment,TranslatedSegment,DubClip,DubbingIssue
    store=temp_job_storage
    monkeypatch.setattr(adapter,"job_storage",store)
    monkeypatch.setattr(adapter,"workspace",temp_workspace)
    job=store.create_job(user_id=1,chat_id=2)
    store.set_job_source(job.job_id,"source.mp4",MediaInfo(640,360,5,True))
    rev=store.create_revision(job.job_id,"text",VoiceSettings(),mode="source_timed")
    store.update_revision(job.job_id,rev.revision_id,audio_path="voice.wav",audio_duration=5)
    plan=DubbingPlan(source_duration_ms=5000,segments=[SourceSegment("s1",0,640,"Hello")],translations=[TranslatedSegment("s1","សួស្តី",status="ready")],clips=[DubClip("s1","cache","raw.wav",status="too_long")],issues=[DubbingIssue("s1","too_long","too long",severity="blocking")])
    monkeypatch.setattr("app.storage.dubbing.load_dubbing_plan",lambda *args:plan)
    bot=SimpleNamespace(send_message=AsyncMock(),send_video=AsyncMock())
    worker=SimpleNamespace(get_bot=lambda:bot,is_cancelled=lambda _:False,register_pid=lambda *args:None)
    await adapter.video_voiceover_pipeline.run(QueueTask(job_id=job.job_id,revision_id=rev.revision_id,feature=JobFeature.VIDEO_VOICEOVER.value,task_type="final",user_id=1),worker)
    assert store.get_job(job.job_id).status==JobState.AWAITING_FIT_RESOLUTION
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["reply_markup"]
    bot.send_video.assert_not_awaited()
