"""Secure and reliable media downloader with SSRF protection and yt-dlp fallback."""
import os
import socket
import ipaddress
import logging
import urllib.parse
from pathlib import Path
from typing import Any, Callable
import aiohttp
import yt_dlp
from app.config import config

logger = logging.getLogger(__name__)

class DownloadSecurityError(Exception):
    """Raised when URL fails SSRF or destination validation."""
    pass

class DownloadLimitError(Exception):
    """Raised when media exceeds size, duration, or timeout limits."""
    pass

def validate_public_url(url: str) -> str:
    """
    Validate that URL points to a public, safe network destination.
    Rejects private, loopback, link-local, and multicast IP addresses (SSRF prevention).
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise DownloadSecurityError("Only HTTP and HTTPS URLs are supported.")

    hostname = parsed.hostname
    if not hostname:
        raise DownloadSecurityError("Invalid URL hostname.")

    # Check for localhost aliases
    if hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise DownloadSecurityError("Access to localhost is prohibited.")

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise DownloadSecurityError(f"Could not resolve hostname '{hostname}': {e}")

    for family, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                raise DownloadSecurityError(f"Access to private/internal IP {ip_str} is prohibited.")
        except ValueError:
            raise DownloadSecurityError(f"Invalid resolved IP address: {ip_str}")

    return url

_guards_installed = False

def _install_network_guards() -> None:
    """Install network interceptors to ensure all HTTP requests validate destination against SSRF."""
    global _guards_installed
    if _guards_installed:
        return
    _guards_installed = True

    # 1. Intercept requests.Session.send
    try:
        import requests
        orig_requests_send = requests.Session.send

        def safe_requests_send(self, request, **kwargs):
            if hasattr(request, "url") and request.url:
                validate_public_url(request.url)
            return orig_requests_send(self, request, **kwargs)

        requests.Session.send = safe_requests_send
    except Exception as e:
        logger.debug(f"Requests guard skipped: {e}")

    # 2. Intercept standard urllib redirect handler
    try:
        import urllib.request
        orig_urllib_redirect = urllib.request.HTTPRedirectHandler.redirect_request

        def safe_urllib_redirect(self, req, fp, code, msg, headers, newurl):
            validate_public_url(newurl)
            return orig_urllib_redirect(self, req, fp, code, msg, headers, newurl)

        urllib.request.HTTPRedirectHandler.redirect_request = safe_urllib_redirect
    except Exception as e:
        logger.debug(f"Urllib redirect guard skipped: {e}")

    # 3. Intercept yt-dlp urllib redirect handler
    try:
        import yt_dlp.networking._urllib
        orig_ytdlp_redirect = yt_dlp.networking._urllib.RedirectHandler.redirect_request

        def safe_ytdlp_redirect(self, req, fp, code, msg, headers, newurl):
            validate_public_url(newurl)
            return orig_ytdlp_redirect(self, req, fp, code, msg, headers, newurl)

        yt_dlp.networking._urllib.RedirectHandler.redirect_request = safe_ytdlp_redirect
    except Exception as e:
        logger.debug(f"yt-dlp urllib redirect guard skipped: {e}")

    # 4. Intercept yt-dlp RequestDirector.send
    try:
        import yt_dlp.networking
        orig_rd_send = yt_dlp.networking.RequestDirector.send

        def safe_rd_send(self, request):
            if hasattr(request, "url") and request.url:
                validate_public_url(request.url)
            return orig_rd_send(self, request)

        yt_dlp.networking.RequestDirector.send = safe_rd_send
    except Exception as e:
        logger.debug(f"yt-dlp RequestDirector guard skipped: {e}")

async def download_direct_url(
    url: str,
    destination_path: Path | str,
    max_bytes: int,
    timeout_seconds: int = 120,
    cancel_check: Callable[[], bool] | None = None,
) -> bool:
    """
    Attempt direct download of media file with hop-by-hop SSRF validation on every redirect.
    Returns True if direct download succeeded, False if server returned non-media.
    """
    validate_public_url(url)
    dest = Path(destination_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    client_timeout = aiohttp.ClientTimeout(total=float(timeout_seconds))
    current_url = url
    max_redirects = 5

    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            for _ in range(max_redirects + 1):
                # Validate URL destination before connecting to prevent SSRF
                validate_public_url(current_url)

                if cancel_check and cancel_check():
                    raise DownloadLimitError("Download cancelled by user.")

                async with session.get(current_url, allow_redirects=False) as response:
                    # Check for redirect status
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            return False
                        current_url = urllib.parse.urljoin(current_url, location)
                        continue

                    if response.status != 200:
                        return False

                    content_type = response.headers.get("Content-Type", "").lower()
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > max_bytes:
                        raise DownloadLimitError(f"File size {int(content_length)} exceeds limit of {max_bytes} bytes.")

                    # If content-type is HTML or not video/stream, let yt-dlp handle it
                    if "html" in content_type:
                        return False

                    downloaded = 0
                    with open(dest, "wb") as f:
                        async for chunk in response.content.iter_chunked(65536):
                            if cancel_check and cancel_check():
                                f.close()
                                if dest.exists():
                                    dest.unlink(missing_ok=True)
                                raise DownloadLimitError("Download cancelled by user.")

                            downloaded += len(chunk)
                            if downloaded > max_bytes:
                                f.close()
                                if dest.exists():
                                    dest.unlink(missing_ok=True)
                                raise DownloadLimitError(f"Downloaded stream exceeded maximum allowed size of {max_bytes} bytes.")
                            f.write(chunk)

                    return True

            return False
    except (DownloadSecurityError, DownloadLimitError):
        raise
    except Exception as e:
        logger.info(f"Direct download failed ({e}), falling back to yt-dlp...")
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False

def download_with_ytdlp(
    url: str,
    destination_path: Path | str,
    max_bytes: int,
    max_seconds: int = 300,
    timeout_seconds: int = 120,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """
    Download video using yt-dlp with SSRF protection on initial URL, redirects,
    and media stream URLs discovered by extractors.
    """
    _install_network_guards()
    validate_public_url(url)
    dest = Path(destination_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_template = str(dest.parent / f"temp_{dest.stem}.%(ext)s")

    def progress_hook(d: dict[str, Any]) -> None:
        if cancel_check and cancel_check():
            raise DownloadLimitError("Download cancelled by user.")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": temp_template,
        "noplaylist": True,
        "max_filesize": max_bytes,
        "socket_timeout": timeout_seconds,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "progress_hooks": [progress_hook],
        "postprocessors": [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if cancel_check and cancel_check():
                raise DownloadLimitError("Download cancelled before start.")

            info = ydl.extract_info(url, download=False)
            if not info:
                raise DownloadLimitError("Could not retrieve media info from URL.")

            # Validate all media format URLs discovered by the extractor before downloading
            media_urls = []
            if "url" in info and isinstance(info["url"], str):
                media_urls.append(info["url"])
            for fmt in info.get("formats", []):
                if isinstance(fmt, dict):
                    if "url" in fmt and isinstance(fmt["url"], str):
                        media_urls.append(fmt["url"])
                    if "manifest_url" in fmt and isinstance(fmt["manifest_url"], str):
                        media_urls.append(fmt["manifest_url"])

            for m_url in media_urls:
                if m_url.startswith(("http://", "https://")):
                    validate_public_url(m_url)

            duration = info.get("duration")
            if duration and duration > max_seconds:
                raise DownloadLimitError(f"Video duration ({duration:.1f}s) exceeds limit of {max_seconds}s.")

            if cancel_check and cancel_check():
                raise DownloadLimitError("Download cancelled by user.")

            ydl.download([url])

            if cancel_check and cancel_check():
                raise DownloadLimitError("Download cancelled by user.")

            # Find the output file
            candidates = list(dest.parent.glob(f"temp_{dest.stem}.*"))
            if not candidates:
                raise DownloadLimitError("yt-dlp completed but output file was not found.")

            chosen = candidates[0]
            if chosen.stat().st_size > max_bytes:
                chosen.unlink(missing_ok=True)
                raise DownloadLimitError("Downloaded file exceeded maximum size.")

            if dest.exists():
                dest.unlink()
            chosen.rename(dest)
            return dest

    except Exception as e:
        # Clean up any partials
        for p in dest.parent.glob(f"temp_{dest.stem}.*"):
            try:
                p.unlink()
            except Exception:
                pass
        raise e

async def download_media(
    url: str,
    destination_path: Path | str,
    max_mb: int | None = None,
    max_seconds: int | None = None,
    timeout_seconds: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """
    Top-level download coordinator:
    1. Validates URL against SSRF
    2. Tries direct stream download
    3. Falls back to yt-dlp for social media platforms
    """
    max_mb = max_mb or config.max_media_mb
    max_seconds = max_seconds or config.max_video_seconds
    timeout = timeout_seconds or config.download_timeout_seconds
    max_bytes = max_mb * 1024 * 1024
    dest = Path(destination_path)

    # 1. Try direct stream
    direct_success = await download_direct_url(
        url=url,
        destination_path=dest,
        max_bytes=max_bytes,
        timeout_seconds=timeout,
        cancel_check=cancel_check,
    )
    if direct_success and dest.exists() and dest.stat().st_size > 0:
        return dest

    # 2. Fall back to yt-dlp
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: download_with_ytdlp(
            url=url,
            destination_path=dest,
            max_bytes=max_bytes,
            max_seconds=max_seconds,
            timeout_seconds=timeout,
            cancel_check=cancel_check,
        )
    )
