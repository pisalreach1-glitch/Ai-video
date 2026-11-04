import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from google import genai
from app.domain.dubbing import SourceSegment
from app.services import segment_translation as translation
from app.services import gemini_video


def segments():
    return [SourceSegment("s001", 0, 1000, "Noisy ASR")]


@pytest.fixture
def fake_api(monkeypatch):
    uploaded = SimpleNamespace(name="files/test", uri="https://example.test/video", mime_type="video/mp4", state="ACTIVE")
    files = SimpleNamespace(upload=AsyncMock(return_value=uploaded), get=AsyncMock(return_value=uploaded), delete=AsyncMock())
    models = SimpleNamespace(generate_content=AsyncMock(return_value=SimpleNamespace(parsed=None,text='{"segments":[{"id":"s001","translated_text":"សួស្តី","needs_review":false}]}')))
    class Api:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    api = Api()
    api.files, api.models = files, models
    monkeypatch.setattr(genai, "Client", lambda **kwargs: SimpleNamespace(aio=api))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return api


@pytest.mark.asyncio
async def test_real_video_part_reaches_translation_and_upload_is_deleted(tmp_path, fake_api):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"mock-video")
    results = await translation.translate_segments(segments(), provider="gemini", video_path=path)
    assert results[0].status == "ready"
    assert results[0].translation_provider == "gemini_video"
    contents = fake_api.models.generate_content.await_args.kwargs["contents"]
    assert contents[0].file_data.file_uri == "https://example.test/video"
    assert "noisy hint" in contents[1]
    fake_api.files.upload.assert_awaited_once()
    fake_api.files.delete.assert_awaited_once_with(name="files/test")


@pytest.mark.asyncio
async def test_failed_video_does_not_silently_fall_back_to_noisy_text(tmp_path, fake_api):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"mock-video")
    fake_api.files.upload.return_value.state = "FAILED"
    results = await translation.translate_segments(segments(), provider="gemini", video_path=path)
    assert results[0].status == "needs_review"
    assert not results[0].translated_text
    fake_api.models.generate_content.assert_not_awaited()
    fake_api.files.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_processing_cleans_remote_upload(tmp_path, fake_api, monkeypatch):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"mock-video")
    fake_api.files.upload.return_value.state = "PROCESSING"
    with pytest.raises(translation.TranslationCancelledError):
        await translation.translate_segments(segments(), provider="gemini", video_path=path,
            cancel_check=lambda: fake_api.files.upload.await_count > 0)
    fake_api.files.delete.assert_awaited_once()
    fake_api.models.generate_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_uncertain_video_translation_requires_review(tmp_path, fake_api):
    fake_api.models.generate_content.return_value.text = '{"segments":[{"id":"s001","translated_text":"សួស្តី","needs_review":true}]}'
    path = tmp_path / "source.mp4"
    path.write_bytes(b"mock-video")
    results = await translation.translate_segments(segments(), provider="gemini", video_path=path)
    assert results[0].status == "needs_review"


@pytest.mark.asyncio
async def test_video_uploaded_once_for_all_batches_and_context_kept(tmp_path, fake_api, monkeypatch):
    source = [SourceSegment(f"s{i}", i*1000, (i+1)*1000, "Hint") for i in range(36)]
    calls = []
    async def batch(items, api_key, cancel_check=None, video_part=None, context_segments=None):
        calls.append((video_part, context_segments))
        return []
    monkeypatch.setattr(translation, "_translate_single_batch_gemini", batch)
    path = tmp_path / "source.mp4"
    path.write_bytes(b"mock-video")
    await translation.translate_segments(source, provider="gemini", video_path=path)
    assert len(calls) == 2
    assert calls[0][0] is calls[1][0]
    assert all(context is source for _,context in calls)
    fake_api.files.upload.assert_awaited_once()
    fake_api.files.delete.assert_awaited_once()
