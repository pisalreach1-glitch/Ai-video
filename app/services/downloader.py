"""Secure and reliable media downloader with SSRF protection and yt-dlp fallback."""
import os
import socket
import ipaddress
import logging
import urllib.parse
import re
import json
import time
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

def is_douyin_url(url: str) -> bool:
    """Check if URL belongs to Douyin (douyin.com or iesdouyin.com)."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in ("douyin.com", "iesdouyin.com"))
    except Exception:
        return False

def extract_douyin_aweme_id(url: str) -> str | None:
    """Extract numeric aweme ID from Douyin URL paths and queries."""
    patterns = [
        r'/video/(\d+)',
        r'/note/(\d+)',
        r'/slides/(\d+)',
        r'/share/video/(\d+)',
        r'modal_id=(\d+)',
        r'vid=(\d+)',
        r'/(\d{15,25})',
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None

def get_or_create_cookiefile() -> Path | None:
    """
    Get existing cookiefile path or generate one from config.douyin_cookie.
    Checks:
    1. config.ytdlp_cookiefile if configured and exists.
    2. ./cookies.txt if exists in root.
    3. runtime/douyin_cookies.txt generated from config.douyin_cookie.
    """
    if config.ytdlp_cookiefile and config.ytdlp_cookiefile.exists():
        return config.ytdlp_cookiefile

    root_cookies = Path("cookies.txt").resolve()
    if root_cookies.exists():
        return root_cookies

    if config.douyin_cookie:
        try:
            runtime_dir = Path("runtime").resolve()
            runtime_dir.mkdir(parents=True, exist_ok=True)
            cookie_file = runtime_dir / "douyin_cookies.txt"

            lines = [
                "# Netscape HTTP Cookie File",
                "# https://curl.haxx.se/rfc/cookie_spec.html",
                "",
            ]
            now = int(time.time()) + 86400 * 365
            for item in config.douyin_cookie.split(";"):
                item = item.strip()
                if not item or "=" not in item:
                    continue
                k, v = item.split("=", 1)
                k = k.strip()
                v = v.strip()
                lines.append(f".douyin.com\tTRUE\t/\tTRUE\t{now}\t{k}\t{v}")
                lines.append(f".iesdouyin.com\tTRUE\t/\tTRUE\t{now}\t{k}\t{v}")

            cookie_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return cookie_file
        except Exception as e:
            logger.warning(f"Failed to write douyin cookiefile: {e}")

    return None

async def resolve_douyin_canonical(url: str, timeout_seconds: int = 15) -> tuple[str, str | None]:
    """
    Resolve short or redirected Douyin URL (e.g. v.douyin.com) to canonical URL and aweme_id.
    Validates every redirection against SSRF.
    """
    validate_public_url(url)

    # If ID is already in url and not a short link, return immediately
    aweme_id = extract_douyin_aweme_id(url)
    if aweme_id and "v.douyin.com" not in url:
        return f"https://www.douyin.com/video/{aweme_id}", aweme_id

    # Otherwise follow redirects to find the real destination
    client_timeout = aiohttp.ClientTimeout(total=float(timeout_seconds))
    current_url = url
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
        )
    }

    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            for _ in range(6):
                validate_public_url(current_url)
                async with session.get(current_url, headers=headers, allow_redirects=False) as response:
                    aweme_id = extract_douyin_aweme_id(current_url)
                    if aweme_id:
                        return f"https://www.douyin.com/video/{aweme_id}", aweme_id

                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            break
                        current_url = urllib.parse.urljoin(current_url, location)
                        aweme_id = extract_douyin_aweme_id(current_url)
                        if aweme_id:
                            return f"https://www.douyin.com/video/{aweme_id}", aweme_id
                        continue
                    else:
                        break
    except Exception as e:
        logger.warning(f"Failed to follow Douyin redirects for {url}: {e}")

    aweme_id = extract_douyin_aweme_id(current_url)
    if aweme_id:
        return f"https://www.douyin.com/video/{aweme_id}", aweme_id
    return current_url, None

async def try_download_douyin_direct(
    url: str,
    canonical_url: str,
    aweme_id: str | None,
    destination_path: Path | str,
    max_bytes: int,
    timeout_seconds: int = 60,
    cancel_check: Callable[[], bool] | None = None,
) -> bool:
    """
    Multi-strategy direct Douyin video parser & stream downloader.
    Uses the user's proven multi-tier engine from their Douyin downloader project:
    1. Universal Course & Protected Resolver (Suxun API - seamlessly handles monetized/protected videos)
    2. Direct Mobile Aweme Feed API (snssdk / amemv)
    3. Direct Aweme Play 302 Redirect Endpoint
    4. Mobile Web SSR Parser (iesdouyin.com/share/video)
    Bypasses JS challenges, anti-bot mechanisms, and monetized channel restrictions without requiring manual cookies.
    """
    # Candidate URLs to try
    candidate_targets = []
    if url:
        candidate_targets.append(url)
    if canonical_url and canonical_url != url:
        candidate_targets.append(canonical_url)
    if aweme_id:
        candidate_targets.append(f"https://www.douyin.com/video/{aweme_id}")

    # =========================================================================
    # Strategy 1: Universal Resolver Engine (bypasses protected/monetized channels)
    # =========================================================================
    for target in candidate_targets:
        if cancel_check and cancel_check():
            raise DownloadLimitError("Download cancelled by user.")
        try:
            resolver_url = f"https://api.suxun.site/api/douyin?url={urllib.parse.quote(target)}"
            validate_public_url(resolver_url)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10.0)) as session:
                async with session.get(resolver_url) as r:
                    if r.status == 200:
                        data = await r.json()
                        item_data = data.get("data")
                        if isinstance(item_data, dict):
                            v_url = item_data.get("url")
                            if v_url and isinstance(v_url, str) and v_url.startswith(("http://", "https://")):
                                success = await download_direct_url(
                                    url=v_url,
                                    destination_path=destination_path,
                                    max_bytes=max_bytes,
                                    timeout_seconds=timeout_seconds,
                                    cancel_check=cancel_check,
                                )
                                if success and Path(destination_path).exists() and Path(destination_path).stat().st_size > 0:
                                    logger.info(f"Successfully downloaded Douyin video via universal resolver for {target}")
                                    return True
        except Exception as e:
            logger.debug(f"Universal resolver failed for {target}: {e}")

    # =========================================================================
    # Strategy 2: Official Mobile Feed Endpoints (ByteDance CDN)
    # =========================================================================
    if aweme_id:
        feed_endpoints = [
            f"https://aweme.snssdk.com/aweme/v1/feed/?aweme_id={aweme_id}",
            f"https://api5-normal-c-hl.amemv.com/aweme/v1/feed/?aweme_id={aweme_id}",
            f"https://api3-normal-c-hl.amemv.com/aweme/v1/feed/?aweme_id={aweme_id}",
        ]
        feed_headers = {
            "User-Agent": (
                "com.ss.android.ugc.aweme/330601 (Linux; U; Android 13; zh_CN; "
                "Build/TQ3A.230901.001; Cronet/TTNetVersion:cf52e896 2024-04-18 QuicVersion:46e1e07b 2024-03-27)"
            ),
            "Accept": "application/json",
        }
        for ep in feed_endpoints:
            if cancel_check and cancel_check():
                raise DownloadLimitError("Download cancelled by user.")
            try:
                validate_public_url(ep)
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8.0)) as session:
                    async with session.get(ep, headers=feed_headers) as r:
                        if r.status == 200:
                            data = await r.json()
                            for item in data.get("aweme_list", []):
                                if str(item.get("aweme_id")) == str(aweme_id):
                                    play_list = item.get("video", {}).get("play_addr", {}).get("url_list", [])
                                    if play_list:
                                        clean_v = play_list[0].replace("playwm", "play")
                                        success = await download_direct_url(
                                            url=clean_v,
                                            destination_path=destination_path,
                                            max_bytes=max_bytes,
                                            timeout_seconds=timeout_seconds,
                                            cancel_check=cancel_check,
                                        )
                                        if success and Path(destination_path).exists() and Path(destination_path).stat().st_size > 0:
                                            logger.info(f"Successfully downloaded Douyin video {aweme_id} via mobile feed API.")
                                            return True
            except Exception as e:
                logger.debug(f"Feed endpoint {ep} failed: {e}")

    # =========================================================================
    # Strategy 3: Direct Aweme Play 302 Redirect Endpoint
    # =========================================================================
    if aweme_id:
        if cancel_check and cancel_check():
            raise DownloadLimitError("Download cancelled by user.")
        try:
            play_api = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={aweme_id}&ratio=1080p&line=0"
            validate_public_url(play_api)
            play_headers = {
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
                ),
            }
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8.0)) as session:
                async with session.get(play_api, headers=play_headers, allow_redirects=False) as r:
                    loc = r.headers.get("Location")
                    if loc:
                        clean_loc = loc.replace("playwm", "play")
                        success = await download_direct_url(
                            url=clean_loc,
                            destination_path=destination_path,
                            max_bytes=max_bytes,
                            timeout_seconds=timeout_seconds,
                            cancel_check=cancel_check,
                        )
                        if success and Path(destination_path).exists() and Path(destination_path).stat().st_size > 0:
                            logger.info(f"Successfully downloaded Douyin video {aweme_id} via play redirect endpoint.")
                            return True
        except Exception as e:
            logger.debug(f"Play endpoint failed for {aweme_id}: {e}")

    # =========================================================================
    # Strategy 4: Mobile Web SSR Parser (iesdouyin.com/share/video)
    # =========================================================================
    if aweme_id:
        if cancel_check and cancel_check():
            raise DownloadLimitError("Download cancelled by user.")
        share_url = f"https://www.iesdouyin.com/share/video/{aweme_id}"
        validate_public_url(share_url)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
            ),
            "Referer": "https://www.iesdouyin.com/",
        }
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10.0)) as session:
                async with session.get(share_url, headers=headers) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        stream_urls: list[str] = []
                        router_match = re.search(r'window\._ROUTER_DATA\s*=\s*(.+?)(?:;?\s*</script>|\n)', html)
                        if router_match:
                            try:
                                data = json.loads(router_match.group(1).strip().rstrip(";"))
                                loader_data = data.get("loaderData", {})
                                for _, page_val in loader_data.items():
                                    if isinstance(page_val, dict) and "videoInfoRes" in page_val:
                                        info = page_val["videoInfoRes"]
                                        for item in info.get("item_list", []):
                                            play_addr = item.get("video", {}).get("play_addr", {})
                                            for u in play_addr.get("url_list", []):
                                                if isinstance(u, str):
                                                    stream_urls.append(u)
                            except Exception:
                                pass

                        if not stream_urls:
                            raw_matches = re.findall(r'(https?:\\?/\\?/(?:aweme\.snssdk\.com|www\.douyin\.com)[^"\'\s<>]+)', html)
                            for rm in raw_matches:
                                clean_u = rm.replace(r"\/", "/")
                                if "play" in clean_u:
                                    stream_urls.append(clean_u)

                        for candidate in stream_urls:
                            clean_candidate = candidate.replace("playwm", "play")
                            success = await download_direct_url(
                                url=clean_candidate,
                                destination_path=destination_path,
                                max_bytes=max_bytes,
                                timeout_seconds=timeout_seconds,
                                cancel_check=cancel_check,
                            )
                            if success and Path(destination_path).exists() and Path(destination_path).stat().st_size > 0:
                                logger.info(f"Successfully downloaded Douyin video {aweme_id} via SSR parser.")
                                return True
        except Exception as e:
            logger.debug(f"Direct Douyin SSR extraction failed for {aweme_id}: {e}")

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

    ydl_opts: dict[str, Any] = {
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

    # Add cookie file if available
    cookiefile = get_or_create_cookiefile()
    if cookiefile and cookiefile.exists():
        ydl_opts["cookiefile"] = str(cookiefile)

    # For Douyin, specify browser headers
    if is_douyin_url(url):
        ydl_opts["http_headers"] = {
            "Referer": "https://www.douyin.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
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
        err_msg = str(e)
        if is_douyin_url(url) and any(kw in err_msg for kw in ("Fresh cookies", "403", "Forbidden", "Sign algorithm")):
            raise DownloadLimitError(
                "⚠️ វីដេអូ Douyin នេះស្ថិតក្នុង Channel ការពារ ឬរកប្រាក់ចំណូល (Protected/Monetized Channel) ដែលត្រូវការ Cookie ពី Browser ស្រស់ៗ។\n\n"
                "💡 ដំណោះស្រាយ៖ សូមដាក់ File `cookies.txt` (Douyin Netscape cookies) នៅក្នុង Folder របស់ Bot ឬកំណត់ `DOUYIN_COOKIE` នៅក្នុង file `.env`។"
            ) from e
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
    2. If Douyin URL:
       a. Resolves short/redirect links (v.douyin.com) to canonical aweme_id
       b. Tries direct mobile stream extraction (fast, watermark-free)
       c. Falls back to yt-dlp with canonical URL and cookiefile support
    3. Tries direct stream download
    4. Falls back to yt-dlp for social media platforms
    """
    max_mb = max_mb or config.max_media_mb
    max_seconds = max_seconds or config.max_video_seconds
    timeout = timeout_seconds or config.download_timeout_seconds
    max_bytes = max_mb * 1024 * 1024
    dest = Path(destination_path)

    target_url = url
    if is_douyin_url(url):
        canonical_url, aweme_id = await resolve_douyin_canonical(url, timeout_seconds=timeout)
        target_url = canonical_url

        direct_douyin = await try_download_douyin_direct(
            url=url,
            canonical_url=canonical_url,
            aweme_id=aweme_id,
            destination_path=dest,
            max_bytes=max_bytes,
            timeout_seconds=timeout,
            cancel_check=cancel_check,
        )
        if direct_douyin and dest.exists() and dest.stat().st_size > 0:
            return dest

    # 1. Try direct stream
    direct_success = await download_direct_url(
        url=target_url,
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
            url=target_url,
            destination_path=dest,
            max_bytes=max_bytes,
            max_seconds=max_seconds,
            timeout_seconds=timeout,
            cancel_check=cancel_check,
        )
    )
