"""Configuration loader and validator."""
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    ffmpeg_path: str
    ffprobe_path: str
    runtime_dir: Path
    db_path: Path
    khmer_font_path: Path
    job_retention_hours: float
    max_queue_size: int
    max_media_mb: int
    max_video_seconds: int
    max_narration_chars: int
    max_concurrent_jobs: int
    download_timeout_seconds: int
    subprocess_timeout_seconds: int
    enable_timed_dubbing: bool = True
    source_asr_model: str = "base"
    source_asr_device: str = "cpu"
    source_asr_compute_type: str = "int8"
    dub_sample_rate: int = 48000
    dub_max_tempo: float = 1.15
    dub_sync_start_tolerance_ms: int = 80
    dub_sync_end_tolerance_ms: int = 120
    dub_sync_filter_duration_tolerance_ms: int = 80
    dub_sync_guard_ms: int = 0
    dub_max_segments: int = 120
    translation_provider: str = "gemini"
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    douyin_cookie: str | None = None
    ytdlp_cookiefile: Path | None = None
    enable_multi_speaker_dubbing: bool = True
    speaker_diarization_backend: str = "pyannote_local"
    speaker_diarization_model: str = "pyannote/speaker-diarization-community-1"
    speaker_device: str = "cpu"
    speaker_require_unscored_review: bool = True
    speaker_enable_visual_matching: bool = False
    speaker_preview_context_ms: int = 750
    hf_token: str = ""

def _find_binary(name: str, explicit_path: str | None = None) -> str:
    """Locate binary path or raise error."""
    if explicit_path and os.path.exists(explicit_path):
        return explicit_path
    
    found = shutil.which(name)
    if found:
        return found
    
    # Try imageio_ffmpeg fallback for ffmpeg
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            if ffmpeg_exe and os.path.exists(ffmpeg_exe):
                return ffmpeg_exe
        except ImportError:
            pass

    return name

def load_settings() -> Settings:
    """Load and validate settings from environment."""
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or ""
    
    runtime_dir = Path(os.getenv("RUNTIME_DIR", "runtime")).resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)

    db_path = runtime_dir / "state.sqlite3"
    
    ffmpeg_explicit = os.getenv("FFMPEG_PATH", "").strip() or None
    ffprobe_explicit = os.getenv("FFPROBE_PATH", "").strip() or None

    ffmpeg_path = _find_binary("ffmpeg", ffmpeg_explicit)
    ffprobe_path = _find_binary("ffprobe", ffprobe_explicit)

    font_path_raw = os.getenv("KHMER_FONT_PATH", "assets/fonts/KhmerOSbattambang.ttf")
    font_path = Path(font_path_raw).resolve()
    if not font_path.exists():
        # Fallback to any TTF in assets/fonts or Windows Fonts
        alt_fonts = [
            Path("assets/fonts/Siemreap.ttf").resolve(),
            Path("C:/Windows/Fonts/KhmerOSbattambang.ttf"),
            Path("C:/Windows/Fonts/KhmerOS.ttf"),
        ]
        for alt in alt_fonts:
            if alt.exists():
                font_path = alt
                break

    return Settings(
        telegram_bot_token=token,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        runtime_dir=runtime_dir,
        db_path=db_path,
        khmer_font_path=font_path,
        job_retention_hours=float(os.getenv("JOB_RETENTION_HOURS", "24")),
        max_queue_size=int(os.getenv("MAX_QUEUE_SIZE", "10")),
        max_media_mb=int(os.getenv("MAX_MEDIA_MB", "2000")),
        max_video_seconds=int(os.getenv("MAX_VIDEO_SECONDS", "600")),
        max_narration_chars=int(os.getenv("MAX_NARRATION_CHARS", "2000")),
        max_concurrent_jobs=int(os.getenv("MAX_CONCURRENT_JOBS", "1")),
        download_timeout_seconds=int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "120")),
        subprocess_timeout_seconds=int(os.getenv("SUBPROCESS_TIMEOUT_SECONDS", "300")),
        enable_timed_dubbing=os.getenv("ENABLE_TIMED_DUBBING", "true").lower() in ("true", "1", "yes"),
        source_asr_model=os.getenv("SOURCE_ASR_MODEL", "base"),
        source_asr_device=os.getenv("SOURCE_ASR_DEVICE", "cpu"),
        source_asr_compute_type=os.getenv("SOURCE_ASR_COMPUTE_TYPE", "int8"),
        dub_sample_rate=int(os.getenv("DUB_SAMPLE_RATE", "48000")),
        dub_max_tempo=float(os.getenv("DUB_MAX_TEMPO", "1.15")),
        dub_sync_start_tolerance_ms=int(os.getenv("DUB_SYNC_START_TOLERANCE_MS", "80")),
        dub_sync_end_tolerance_ms=int(os.getenv("DUB_SYNC_END_TOLERANCE_MS", "120")),
        dub_sync_filter_duration_tolerance_ms=int(os.getenv("DUB_SYNC_FILTER_DURATION_TOLERANCE_MS", "80")),
        dub_sync_guard_ms=int(os.getenv("DUB_SYNC_GUARD_MS", "0")),
        dub_max_segments=int(os.getenv("DUB_MAX_SEGMENTS", "120")),
        translation_provider=os.getenv("TRANSLATION_PROVIDER", "gemini" if os.getenv("GEMINI_API_KEY") else "manual"),
        telegram_api_id=int(os.getenv("TELEGRAM_API_ID").strip()) if os.getenv("TELEGRAM_API_ID") and os.getenv("TELEGRAM_API_ID").strip().isdigit() else None,
        telegram_api_hash=os.getenv("TELEGRAM_API_HASH", "").strip() or None,
        douyin_cookie=os.getenv("DOUYIN_COOKIE", "").strip() or None,
        ytdlp_cookiefile=(
            Path(os.getenv("YTDLP_COOKIEFILE").strip()).resolve()
            if os.getenv("YTDLP_COOKIEFILE") and Path(os.getenv("YTDLP_COOKIEFILE").strip()).exists()
            else (Path("cookies.txt").resolve() if Path("cookies.txt").exists() else None)
        ),
        enable_multi_speaker_dubbing=os.getenv("ENABLE_MULTI_SPEAKER_DUBBING", "true").lower() in ("true", "1", "yes"),
        speaker_diarization_backend=os.getenv("SPEAKER_DIARIZATION_BACKEND", "pyannote_local"),
        speaker_diarization_model=os.getenv("SPEAKER_DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1"),
        speaker_device=os.getenv("SPEAKER_DEVICE", "cpu"),
        speaker_require_unscored_review=os.getenv("SPEAKER_REQUIRE_UNSCORED_REVIEW", "true").lower() in ("true", "1", "yes"),
        speaker_enable_visual_matching=os.getenv("SPEAKER_ENABLE_VISUAL_MATCHING", "false").lower() in ("true", "1", "yes"),
        speaker_preview_context_ms=int(os.getenv("SPEAKER_PREVIEW_CONTEXT_MS", "750")),
        hf_token=os.getenv("HF_TOKEN", ""),
    )

config = load_settings()
