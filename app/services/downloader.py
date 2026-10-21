"""Secure and reliable media downloader with SSRF protection and yt-dlp fallback."""
import os
import socket
import ipaddress
import logging
import urllib.parse
from pathlib import Path
from typing import Callable
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

async def download_direct_url(
    url: str,
    destination_path: Path | str,
    max_bytes: int,
    timeout_seconds: int = 120,
    cancel_check: Callable[[], bool] | None = None,
) -> bool:
    """
    Attempt direct download of media file with streaming byte-limit validation.
    Returns True if direct download succeeded, False if server returned non-media.
    """
    validate_public_url(url)
    dest = Path(destination_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    client_timeout = aiohttp.ClientTimeout(total=float(timeout_seconds))
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    return False

                # Verify final redirect destination against SSRF
                final_url = str(response.url)
                validate_public_url(final_url)

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
                                dest.unlink()
                            raise DownloadLimitError("Download cancelled by user.")

                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            f.close()
                            if dest.exists():
                                dest.unlink()
                            raise DownloadLimitError(f"Downloaded stream exceeded maximum allowed size of {max_bytes} bytes.")
                        f.write(chunk)

                return True
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
    Download video using yt-dlp with single video enforcement, format limits, and SSRF check.
    """
    validate_public_url(url)
    dest = Path(destination_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_template = str(dest.parent / f"temp_{dest.stem}.%(ext)s")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": temp_template,
        "noplaylist": True,
        "max_filesize": max_bytes,
        "socket_timeout": timeout_seconds,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
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

            duration = info.get("duration")
            if duration and duration > max_seconds:
                raise DownloadLimitError(f"Video duration ({duration:.1f}s) exceeds limit of {max_seconds}s.")

            ydl.download([url])

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
