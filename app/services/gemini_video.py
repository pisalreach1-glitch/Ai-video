"""Upload original video once per translation; release the remote file afterwards."""
import asyncio
from contextlib import asynccontextmanager
import logging
import mimetypes
from pathlib import Path
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


@asynccontextmanager
async def video_context(path, api_key):
    path = Path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("Source video is missing or empty")
    if path.stat().st_size > 2 * 1024**3:
        raise ValueError("Source video exceeds the 2 GB upload limit")
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    if not mime.startswith("video/"):
        raise ValueError("Source file is not a supported video")
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
        timeout=90000, retry_options=types.HttpRetryOptions(attempts=1)))
    uploaded = None
    async with client.aio as api:
        try:
            uploaded = await api.files.upload(file=path, config=types.UploadFileConfig(mime_type=mime))
            if not uploaded.name:
                raise RuntimeError("Gemini upload returned no file name")
            while getattr(uploaded.state, "name", uploaded.state) != "ACTIVE":
                state = getattr(uploaded.state, "name", uploaded.state)
                if state not in ("PROCESSING", "STATE_UNSPECIFIED", None):
                    raise RuntimeError("Gemini could not process the source video")
                await asyncio.sleep(1)
                uploaded = await api.files.get(name=uploaded.name)
            if not uploaded.uri:
                raise RuntimeError("Gemini upload returned no video reference")
            yield types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type or mime)
        finally:
            if uploaded and uploaded.name:
                try:
                    await asyncio.wait_for(api.files.delete(name=uploaded.name), timeout=10)
                except Exception:
                    logger.warning("Could not remove temporary Gemini video upload; server retention applies.")
