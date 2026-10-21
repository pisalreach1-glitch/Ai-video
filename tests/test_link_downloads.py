"""Test video URL downloading, SSRF filtering, and size limits."""
import pytest
from app.services.downloader import (
    validate_public_url,
    DownloadSecurityError,
    DownloadLimitError,
)

def test_public_url_ssrf_rejection():
    """Verify that private, loopback, and internal addresses are blocked."""
    unsafe_urls = [
        "http://localhost:8080/video.mp4",
        "http://127.0.0.1/video.mp4",
        "http://127.0.0.2:80/stream",
        "https://10.0.0.1/internal.mp4",
        "https://192.168.1.1/video.mp4",
        "https://172.16.0.5/cam",
        "ftp://example.com/video.mp4",
        "file:///etc/passwd",
    ]
    for url in unsafe_urls:
        with pytest.raises(DownloadSecurityError):
            validate_public_url(url)

def test_public_url_validation_success():
    """Ensure standard public web URLs pass destination validation."""
    safe_urls = [
        "https://www.google.com/test.mp4",
        "https://example.com/video.mp4",
    ]
    for url in safe_urls:
        assert validate_public_url(url) == url

@pytest.mark.asyncio
async def test_download_byte_limit_enforcement(tmp_path, monkeypatch):
    """Ensure downloaded stream is cut off and cleaned if it exceeds max size without Content-Length."""
    from app.services.downloader import download_direct_url
    dest = tmp_path / "oversized.mp4"

    class AsyncChunkIter:
        def __init__(self, chunks):
            self.chunks = list(chunks)
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self.chunks:
                raise StopAsyncIteration
            return self.chunks.pop(0)

    class MockContent:
        def iter_chunked(self, size):
            return AsyncChunkIter([b"x" * 100, b"y" * 100])

    class MockResponse:
        status = 200
        url = "https://example.com/stream.mp4"
        headers = {"Content-Type": "video/mp4"} # no Content-Length
        content = MockContent()
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass

    class MockSession:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
        def get(self, url, **kwargs):
            return MockResponse()

    monkeypatch.setattr("aiohttp.ClientSession", MockSession)

    with pytest.raises(DownloadLimitError):
        await download_direct_url(
            url="https://example.com/stream.mp4",
            destination_path=dest,
            max_bytes=50, # 50 bytes limit, stream sends 100+100
            timeout_seconds=10,
        )

    # Destination file must not be left behind
    assert not dest.exists()
