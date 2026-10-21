"""Unit tests for Telegram large file MTProto downloader and fallback."""
import pytest
from pathlib import Path
from aiogram.exceptions import TelegramBadRequest
from app.services.tg_downloader import (
    download_telegram_media,
    stop_pyrogram_client,
    MediaWrapper,
)


class DummyVideo:
    def __init__(self, file_id="vid_123", file_size=1000, file_name="sample.mp4", mime_type="video/mp4"):
        self.file_id = file_id
        self.file_size = file_size
        self.file_name = file_name
        self.mime_type = mime_type


class DummyDocument:
    def __init__(self, file_id="doc_123", file_size=1000, file_name="sample.mp4", mime_type="video/mp4"):
        self.file_id = file_id
        self.file_size = file_size
        self.file_name = file_name
        self.mime_type = mime_type


class DummyMessage:
    def __init__(self, video=None, document=None):
        self.video = video
        self.document = document


class MockBotSuccess:
    def __init__(self):
        self.get_file_called = False
        self.download_file_called = False

    async def get_file(self, file_id):
        self.get_file_called = True
        return type("FileObj", (), {"file_path": f"/remote/{file_id}"})()

    async def download_file(self, file_path, destination):
        self.download_file_called = True
        p = Path(destination)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"downloaded content via http")


class MockBotTooBig:
    async def get_file(self, file_id):
        raise TelegramBadRequest(method="getFile", message="file is too big")

    async def download_file(self, file_path, destination):
        pass


class MockPyroClient:
    def __init__(self):
        self.downloaded_media = None
        self.destination_file_name = None
        self.is_connected = True

    async def download_media(self, message, file_name=None, progress=None, **kwargs):
        self.downloaded_media = message
        self.destination_file_name = file_name
        dest = Path(file_name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"large content via mtproto")
        if progress:
            await progress(10 * 1024 * 1024, 25 * 1024 * 1024)
            await progress(25 * 1024 * 1024, 25 * 1024 * 1024)
        return str(dest)

    async def stop(self):
        self.is_connected = False


@pytest.mark.asyncio
async def test_download_small_file_via_http(tmp_path):
    """Small files (<= 20MB) should use standard Bot API HTTP download directly."""
    dest = tmp_path / "out_small.mp4"
    bot = MockBotSuccess()
    msg = DummyMessage(video=DummyVideo(file_size=5 * 1024 * 1024))

    result = await download_telegram_media(msg, dest, bot=bot)
    assert result == dest
    assert dest.exists()
    assert dest.read_bytes() == b"downloaded content via http"
    assert bot.get_file_called is True
    assert bot.download_file_called is True


@pytest.mark.asyncio
async def test_download_fallback_when_http_fails_with_file_is_too_big(monkeypatch, tmp_path):
    """When Bot API HTTP raises 'file is too big', it should automatically fall back to Pyrogram MTProto."""
    dest = tmp_path / "out_fallback.mp4"
    bot = MockBotTooBig()
    msg = DummyMessage(video=DummyVideo(file_size=19 * 1024 * 1024))

    mock_client = MockPyroClient()
    monkeypatch.setattr("app.services.tg_downloader.get_pyrogram_client", lambda: _async_return(mock_client))

    result = await download_telegram_media(msg, dest, bot=bot)
    assert result == dest
    assert dest.exists()
    assert dest.read_bytes() == b"large content via mtproto"
    assert mock_client.downloaded_media.file_id == "vid_123"


@pytest.mark.asyncio
async def test_download_large_file_directly_via_mtproto(monkeypatch, tmp_path):
    """Files > 20MB should bypass HTTP and directly use Pyrogram MTProto."""
    dest = tmp_path / "out_large.mp4"
    bot = MockBotSuccess()
    # 50MB file
    msg = DummyMessage(video=DummyVideo(file_id="large_vid_999", file_size=50 * 1024 * 1024))

    mock_client = MockPyroClient()
    monkeypatch.setattr("app.services.tg_downloader.get_pyrogram_client", lambda: _async_return(mock_client))

    edited_texts = []
    class MockStatusMsg:
        async def edit_text(self, text, **kwargs):
            edited_texts.append(text)

    status_msg = MockStatusMsg()
    result = await download_telegram_media(msg, dest, bot=bot, status_msg=status_msg)
    assert result == dest
    assert dest.exists()
    assert dest.read_bytes() == b"large content via mtproto"
    # HTTP bot was bypassed entirely for > 20MB
    assert bot.get_file_called is False
    assert mock_client.downloaded_media.file_id == "large_vid_999"
    # Progress callback executed
    assert len(edited_texts) > 0
    assert any("100%" in t or "25.0 MB" in t for t in edited_texts)


@pytest.mark.asyncio
async def test_download_fails_when_pyrogram_unconfigured_for_large_file(monkeypatch, tmp_path):
    """When file is > 20MB and Pyrogram cannot be initialized, raises clear Khmer error."""
    dest = tmp_path / "out_fail.mp4"
    msg = DummyMessage(video=DummyVideo(file_size=30 * 1024 * 1024))
    monkeypatch.setattr("app.services.tg_downloader.get_pyrogram_client", lambda: _async_return(None))

    with pytest.raises(RuntimeError) as exc_info:
        await download_telegram_media(msg, dest, bot=None)

    assert "20MB" in str(exc_info.value)
    assert "TELEGRAM_API_ID" in str(exc_info.value)


@pytest.mark.asyncio
async def test_stop_pyrogram_client_graceful(monkeypatch):
    """Ensure stop_pyrogram_client cleanly calls client.stop and unsets singleton."""
    import app.services.tg_downloader as tgd
    mock_client = MockPyroClient()
    tgd._pyro_client = mock_client

    assert tgd._pyro_client.is_connected is True
    await stop_pyrogram_client()
    assert tgd._pyro_client is None
    assert mock_client.is_connected is False


async def _async_return(val):
    return val
