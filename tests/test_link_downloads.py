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

@pytest.mark.asyncio
async def test_download_direct_url_blocks_redirect_to_private_ip(tmp_path, monkeypatch):
    """Ensure redirect to private/internal IP is rejected by SSRF guard."""
    from app.services.downloader import download_direct_url, DownloadSecurityError
    dest = tmp_path / "redirect_dest.mp4"

    class RedirectResponse:
        status = 302
        headers = {"Location": "http://127.0.0.1:8080/evil.mp4"}
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
            return RedirectResponse()

    monkeypatch.setattr("aiohttp.ClientSession", MockSession)

    with pytest.raises(DownloadSecurityError):
        await download_direct_url(
            url="https://example.com/redirect",
            destination_path=dest,
            max_bytes=10000,
            timeout_seconds=5,
        )

def test_is_douyin_url():
    """Verify Douyin domain detection for various URL formats."""
    from app.services.downloader import is_douyin_url
    assert is_douyin_url("https://v.douyin.com/iLXXXXX/") is True
    assert is_douyin_url("http://v.douyin.com/BsqnCLa/") is True
    assert is_douyin_url("https://www.douyin.com/video/7342938491823912345") is True
    assert is_douyin_url("https://www.iesdouyin.com/share/video/7342938491823912345") is True
    assert is_douyin_url("https://douyin.com/note/7342938491823912345") is True
    assert is_douyin_url("https://www.tiktok.com/@user/video/7123456789012345678") is False
    assert is_douyin_url("https://youtube.com/watch?v=123") is False
    assert is_douyin_url("not a url") is False

def test_extract_douyin_aweme_id():
    """Verify extraction of aweme IDs across various Douyin URL styles."""
    from app.services.downloader import extract_douyin_aweme_id
    assert extract_douyin_aweme_id("https://www.douyin.com/video/7342938491823912345") == "7342938491823912345"
    assert extract_douyin_aweme_id("https://www.douyin.com/video/7342938491823912345?previous_page=app_code") == "7342938491823912345"
    assert extract_douyin_aweme_id("https://www.iesdouyin.com/share/video/7342938491823912345/?mid=123") == "7342938491823912345"
    assert extract_douyin_aweme_id("https://www.douyin.com/note/7342938491823912345") == "7342938491823912345"
    assert extract_douyin_aweme_id("https://www.douyin.com/?modal_id=7342938491823912345") == "7342938491823912345"
    assert extract_douyin_aweme_id("https://v.douyin.com/7342938491823912345/") == "7342938491823912345"

def test_get_or_create_cookiefile_from_env(monkeypatch, tmp_path):
    """Verify Netscape cookie file generation from config.douyin_cookie."""
    import dataclasses
    from pathlib import Path
    from app.services import downloader
    from app.services.downloader import get_or_create_cookiefile

    mock_config = dataclasses.replace(
        downloader.config,
        ytdlp_cookiefile=None,
        douyin_cookie="ttwid=test_ttwid_123; passport_csrf_token=test_token_456",
    )
    monkeypatch.setattr(downloader, "config", mock_config)
    
    # Run in temp directory to avoid touching real runtime
    orig_resolve = Path.resolve
    def mock_resolve(p):
        if str(p) == "runtime":
            return tmp_path / "runtime"
        if str(p) == "cookies.txt":
            return tmp_path / "cookies.txt"
        return orig_resolve(p)
    monkeypatch.setattr(Path, "resolve", mock_resolve)

    cookiefile = get_or_create_cookiefile()
    assert cookiefile is not None
    assert cookiefile.exists()
    content = cookiefile.read_text(encoding="utf-8")
    assert "Netscape HTTP Cookie File" in content
    assert "test_ttwid_123" in content
    assert "test_token_456" in content

@pytest.mark.asyncio
async def test_resolve_douyin_canonical_redirect(monkeypatch):
    """Verify following redirects for short Douyin URLs to canonical URL."""
    from app.services.downloader import resolve_douyin_canonical

    class MockRedirectResponse:
        status = 302
        headers = {"Location": "https://www.douyin.com/video/7342938491823912345?previous_page=app_code"}
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
            return MockRedirectResponse()

    monkeypatch.setattr("aiohttp.ClientSession", MockSession)

    canonical, aweme_id = await resolve_douyin_canonical("https://v.douyin.com/iLXXXXX/")
    assert canonical == "https://www.douyin.com/video/7342938491823912345"
    assert aweme_id == "7342938491823912345"

def test_extract_url_from_douyin_share_text():
    """Verify extracting URL from realistic Douyin mobile app copy-paste snippets."""
    import re
    snippet = "7.11 03/24 J@m.vt YhY:/ 听说这是全网最甜的女孩... https://v.douyin.com/iL29jB8/ 复制此链接，打开DouYin搜索，直接观看视频！"
    match = re.search(r"https?://[^\s<>\"\'\u4e00-\u9fff\u1780-\u17ff]+", snippet)
    assert match is not None
    url = match.group(0).rstrip("，。；！？）)》>\"'")
    assert url == "https://v.douyin.com/iL29jB8/"

@pytest.mark.asyncio
async def test_try_download_douyin_direct_resolver(tmp_path, monkeypatch):
    """Verify that Douyin universal resolver successfully streams media without cookies."""
    from app.services.downloader import try_download_douyin_direct
    dest = tmp_path / "douyin_out.mp4"

    class MockResolverResp:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
        async def json(self):
            return {"code": 200, "data": {"url": "https://example.com/stream.mp4"}}

    class MockStreamResp:
        status = 200
        headers = {"Content-Type": "video/mp4"}
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
        @property
        def content(self):
            class Content:
                def iter_chunked(self, size):
                    class AsyncIter:
                        def __init__(self):
                            self.done = False
                        def __aiter__(self):
                            return self
                        async def __anext__(self):
                            if self.done:
                                raise StopAsyncIteration
                            self.done = True
                            return b"fake_mp4_bytes"
                    return AsyncIter()
            return Content()

    class MockSession:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
        def get(self, url, **kwargs):
            if "suxun.site" in url:
                return MockResolverResp()
            return MockStreamResp()

    monkeypatch.setattr("aiohttp.ClientSession", MockSession)

    success = await try_download_douyin_direct(
        url="https://v.douyin.com/6wNQ9uM7eGI/",
        canonical_url="https://www.douyin.com/video/7189183796351143226",
        aweme_id="7189183796351143226",
        destination_path=dest,
        max_bytes=10*1024*1024,
    )
    assert success is True
    assert dest.exists()
    assert dest.read_bytes() == b"fake_mp4_bytes"


