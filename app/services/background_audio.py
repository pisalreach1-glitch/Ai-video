"""Cached non-vocal background extraction shared by every dubbed render path."""
import asyncio
import hashlib
import logging
import os
from pathlib import Path
import tempfile
from app.config import config
from app.jobs.processes import run_process
from app.jobs.gpu_scheduler import gpu_scheduler
from app.services.media import probe_audio_duration

logger = logging.getLogger(__name__)

MODEL = 'UVR-MDX-NET-Inst_HQ_3.onnx'
_locks = {}

def _source_digest(source):
    digest = hashlib.sha256(MODEL.encode())
    with source.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()[:24]

async def prepare_background(source_path, cancel_check=None, on_pid=None):
    source = Path(source_path).resolve()
    if cancel_check and cancel_check():
        raise RuntimeError('Background separation cancelled')
    digest = await asyncio.to_thread(_source_digest, source)
    cache = source.parent / 'background_audio'
    cache.mkdir(parents=True, exist_ok=True)
    final = cache / f'{digest}.wav'
    lock = _locks.setdefault(str(final), asyncio.Lock())
    async with lock:
        if final.is_file() and probe_audio_duration(final) > 0:
            return final
        root = Path(__file__).resolve().parents[2]
        default_python = root / '.venv-audio' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        python = Path(os.getenv('BACKGROUND_SEPARATOR_PYTHON', str(default_python)))
        if not python.is_file():
            raise RuntimeError('មិនទាន់ដំឡើងឧបករណ៍បំបែកសំឡេងរួចទេ។ សូមសាកល្បងម្ដងទៀតពេលដំឡើងរួច។')
        with tempfile.TemporaryDirectory(prefix='separate-', dir=cache) as attempt:
            attempt = Path(attempt)
            original = attempt / 'source.wav'
            separated = attempt / 'background.wav'
            result = await run_process([
                config.ffmpeg_path, '-y', '-i', str(source), '-vn', '-ac', '2',
                '-ar', '44100', '-c:a', 'pcm_s16le', str(original),
            ], timeout=120, cancel_check=cancel_check, on_pid=on_pid)
            if result.returncode != 0:
                raise RuntimeError('Could not extract source audio for background separation')
            duration = probe_audio_duration(original)
            # All inference shares the same GPU lease as ASR/avatars.
            async with gpu_scheduler.acquire('background_audio', digest):
                result = await run_process([
                    str(python), str(root / 'scripts' / 'separate_background.py'),
                    '--input', str(original), '--output', str(separated),
                    '--models', str(root / 'models' / 'audio_separator'), '--model', MODEL,
                ], timeout=900, cancel_check=cancel_check, on_pid=on_pid)
            if cancel_check and cancel_check():
                raise RuntimeError('Background separation cancelled')
            if result.returncode != 0 or not separated.is_file():
                logger.error('Background separator failed: %s', result.stderr[-1500:])
                raise RuntimeError('បំបែកសំឡេងនិយាយដើមមិនបាន។ សូមសាកល្បងម្ដងទៀត ឬប្ដូរការកំណត់សំឡេង។')
            if abs(probe_audio_duration(separated) - duration) > 0.25:
                raise RuntimeError('Separated background duration does not match the source')
            separated.replace(final)
        return final
