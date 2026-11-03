"""Slow AI requests must finish, report progress, or respect cancellation."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.domain.dubbing import SourceSegment, TranslatedSegment
from app.services import segment_translation as translation


@pytest.mark.parametrize("stage", ["analyzing_source", "translating_segments"])
def test_restart_makes_stuck_translation_retryable(temp_job_storage, stage):
    from app.domain.states import JobState
    job = temp_job_storage.create_job(user_id=1, chat_id=1)
    temp_job_storage.set_job_status(job.job_id, JobState(stage))
    assert temp_job_storage.recover_interrupted_jobs() == 1
    recovered = temp_job_storage.get_job(job.job_id)
    assert recovered.status == JobState.AWAITING_TEXT
    assert recovered.stage == "translation_interrupted"
    assert recovered.job_id in {j.job_id for j in temp_job_storage.get_user_active_jobs(1, 1)}


def source():
    return [SourceSegment(segment_id="s001", start_ms=1000, end_ms=3000, source_text="Hello")]


@pytest.mark.asyncio
async def test_hung_provider_times_out_and_closes_pending_operation(monkeypatch):
    stopped = asyncio.Event()

    async def hung(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setenv("GEMINI_API_KEY", "fixture")
    monkeypatch.setattr(translation, "TRANSLATION_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(translation, "translate_segments_gemini", hung)
    result = await asyncio.wait_for(translation.translate_segments(source(), provider="gemini"), 2)
    assert stopped.is_set()
    assert result[0].status == "needs_review"
    assert result[0].translated_text == ""


@pytest.mark.asyncio
async def test_cancel_during_provider_wait_does_not_return_manual_success(monkeypatch):
    cancelled = False
    stopped = asyncio.Event()

    async def hung(*args, **kwargs):
        nonlocal cancelled
        cancelled = True
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setenv("GEMINI_API_KEY", "fixture")
    monkeypatch.setattr(translation, "translate_segments_gemini", hung)
    with pytest.raises(translation.TranslationCancelledError):
        await asyncio.wait_for(translation.translate_segments(source(), provider="gemini", cancel_check=lambda: cancelled), 2)
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_wait_updates_progress_and_preserves_success(monkeypatch):
    async def slow(*args, **kwargs):
        await asyncio.sleep(0.35)
        return [TranslatedSegment(segment_id="s001", translated_text="សួស្តី", status="ready")]

    progress = AsyncMock()
    monkeypatch.setenv("GEMINI_API_KEY", "fixture")
    monkeypatch.setattr(translation, "TRANSLATION_PROGRESS_SECONDS", 0.01)
    monkeypatch.setattr(translation, "translate_segments_gemini", slow)
    result = await translation.translate_segments(source(), provider="gemini", on_progress=progress)
    progress.assert_awaited()
    assert result[0].translated_text == "សួស្តី"


@pytest.mark.asyncio
async def test_async_gemini_timeout_options_and_client_cleanup(monkeypatch):
    from google import genai
    captured = {}

    class FakeAsyncClient:
        async def __aenter__(self):
            self.models = self
            return self

        async def __aexit__(self, *args):
            captured["closed"] = True

        async def generate_content(self, **kwargs):
            return SimpleNamespace(text='{"segments":[{"id":"s001","translated_text":"សួស្តី"}]}', parsed=None)

    def client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(aio=FakeAsyncClient())

    monkeypatch.setattr(genai, "Client", client)
    result = await translation._translate_single_batch_gemini(source(), "fixture")
    assert captured["http_options"].timeout == translation.GEMINI_HTTP_TIMEOUT_MS
    assert captured["closed"]
    assert result[0].segment_id == "s001"
