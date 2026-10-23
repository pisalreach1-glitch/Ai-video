"""Media validation, face checking, and audio normalization for Talking Photo."""
import logging
from pathlib import Path
from PIL import Image
from app.config import config
from app.jobs.processes import run_process

logger = logging.getLogger(__name__)

async def validate_portrait_image(image_path: Path) -> tuple[bool, str, int, int]:
    """
    Validate that the file is a readable image with sensible dimensions.
    Returns (is_valid, error_message, width, height).
    """
    if not image_path.exists():
        return False, "File does not exist.", 0, 0

    try:
        with Image.open(image_path) as img:
            img.verify()
        with Image.open(image_path) as img:
            w, h = img.size
            if w < 128 or h < 128:
                return False, f"រូបថតតូចពេក ({w}x{h})។ សូមផ្ញើរូបថតដែលមានទំហំចាប់ពី 128x128 ឡើងទៅ។", w, h
            if w > 4096 or h > 4096:
                return False, f"រូបថតធំពេក ({w}x{h})។", w, h
            return True, "", w, h
    except Exception as e:
        logger.warning(f"Failed to decode image {image_path}: {e}")
        return False, "មិនអាចបើករូបថតនេះបានឡើយ។ សូមផ្ញើរូបថត JPG ឬ PNG ត្រឹមត្រូវ។", 0, 0

async def normalize_voice_recording(
    source_voice_path: Path,
    master_audio_wav: Path,
    inference_wav: Path,
) -> float:
    """
    Convert recorded Telegram Voice (.ogg / Opus / audio) into:
    1. master_audio.wav: 48kHz stereo/mono 16-bit PCM lossless master audio
    2. inference.wav: 16kHz mono 16-bit PCM for SadTalker model inference
    Returns measured duration in seconds.
    """
    master_audio_wav.parent.mkdir(parents=True, exist_ok=True)
    inference_wav.parent.mkdir(parents=True, exist_ok=True)

    # 1. Produce master_audio.wav
    cmd_master = [
        config.ffmpeg_path,
        "-y",
        "-i", str(source_voice_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "48000",
        str(master_audio_wav),
    ]
    res_master = await run_process(cmd_master, timeout=120.0)
    if res_master.returncode != 0 or not master_audio_wav.exists():
        raise RuntimeError(f"Failed to decode master audio: {res_master.stderr[:200]}")

    # 2. Produce inference.wav (16kHz mono for speech-driven facial animation)
    cmd_infer = [
        config.ffmpeg_path,
        "-y",
        "-i", str(master_audio_wav),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(inference_wav),
    ]
    res_infer = await run_process(cmd_infer, timeout=120.0)
    if res_infer.returncode != 0 or not inference_wav.exists():
        raise RuntimeError(f"Failed to create inference wav: {res_infer.stderr[:200]}")

    # 3. Measure duration precisely with ffprobe
    duration = await measure_audio_duration(master_audio_wav)
    return duration

async def measure_audio_duration(audio_path: Path) -> float:
    """Measure duration in seconds using ffprobe."""
    cmd = [
        config.ffprobe_path,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    res = await run_process(cmd, timeout=30.0)
    if res.returncode == 0 and res.stdout.strip():
        try:
            return float(res.stdout.strip())
        except ValueError:
            pass
    return 0.0
