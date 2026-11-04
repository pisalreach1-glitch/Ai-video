"""Validated, cached, cancellable local voice conversion for Khmer dubbing."""
import asyncio
from functools import lru_cache
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
from app.config import config
from app.jobs.gpu_scheduler import gpu_scheduler
from app.jobs.processes import run_process, kill_process_tree
from app.services.media import probe_audio_duration

logger=logging.getLogger(__name__)
ROOT=Path(__file__).resolve().parents[2]
_process=None
_log=None
_lock=asyncio.Lock()

def enabled():
    return os.getenv('OPENVOICE_ENABLED','false').lower() in ('1','true','yes')

@lru_cache(maxsize=64)
def _hash_file(path,size,mtime):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def file_hash(path):
    path=Path(path).resolve();stat=path.stat()
    return _hash_file(str(path),stat.st_size,stat.st_mtime_ns)

def reference_window(plan,segment):
    assignment=plan.get_assignment(segment.segment_id)
    speaker=assignment.speaker_id if assignment else segment.speaker_id
    choices=[segment]
    if speaker:
        choices=[s for s in plan.segments if (plan.get_assignment(s.segment_id).speaker_id if plan.get_assignment(s.segment_id) else s.speaker_id)==speaker]
    reference=max(choices,key=lambda s:s.duration_ms)
    return reference.start_ms,min(reference.end_ms,reference.start_ms+8000)

async def close_worker():
    global _process,_log
    process=_process;_process=None
    if process and process.returncode is None:
        kill_process_tree(process.pid)
        await process.wait()
    if _log:
        _log.close();_log=None

async def _read_response(cancel_check,timeout):
    task=asyncio.create_task(_process.stdout.readline())
    started=asyncio.get_running_loop().time()
    try:
        while True:
            done,_=await asyncio.wait({task},timeout=0.25)
            if cancel_check and cancel_check():raise asyncio.CancelledError('Voice conversion cancelled')
            if done:
                line=task.result()
                if not line:raise RuntimeError('OpenVoice worker stopped')
                return json.loads(line)
            if asyncio.get_running_loop().time()-started>timeout:raise TimeoutError('OpenVoice timed out')
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)

async def _infer(source,reference,output,cancel_check=None):
    global _process,_log
    async with _lock:
        async with gpu_scheduler.acquire('openvoice_v2',str(output)):
            try:
                if _process is None or _process.returncode is not None:
                    await close_worker()
                    python=Path(os.getenv('OPENVOICE_PYTHON',str(ROOT/'.venv-openvoice'/('Scripts/python.exe' if os.name=='nt' else 'bin/python'))))
                    if not python.is_file():raise RuntimeError('OpenVoice runtime not installed')
                    config.runtime_dir.mkdir(parents=True,exist_ok=True)
                    _log=open(config.runtime_dir/'openvoice.log','ab')
                    _process=await asyncio.create_subprocess_exec(str(python),str(ROOT/'scripts'/'openvoice_worker.py'),str(ROOT/'models'/'openvoice_v2'/'converter'),
                        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=_log,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                    response=await _read_response(cancel_check,120)
                    if not response.get('ready'):raise RuntimeError('OpenVoice failed to initialize')
                request={'source':str(source),'reference':str(reference),'output':str(output)}
                _process.stdin.write((json.dumps(request)+'\n').encode())
                await _process.stdin.drain()
                response=await _read_response(cancel_check,120)
                if not response.get('ok') or response.get('engine')!='openvoice_v2':
                    raise RuntimeError(response.get('error','OpenVoice inference failed'))
            except BaseException:
                await close_worker()
                raise

async def convert_segment(source_wav,video_path,start_ms,end_ms,output_wav,cancel_check=None):
    source=Path(source_wav).resolve();video=Path(video_path).resolve();output=Path(output_wav).resolve()
    if not 0<=start_ms<end_ms:raise ValueError('Invalid voice reference interval')
    if cancel_check and cancel_check():raise asyncio.CancelledError('Voice conversion cancelled')
    model=ROOT/'models'/'openvoice_v2'/'converter'
    if not (model/'checkpoint.pth').is_file():raise RuntimeError('មិនទាន់មានម៉ូដែល OpenVoice V2 ក្នុង PC ទេ។')
    key=await asyncio.to_thread(lambda:hashlib.sha256(json.dumps([file_hash(source),file_hash(video),file_hash(model/'checkpoint.pth'),file_hash(model/'config.json'),start_ms,end_ms,'openvoice_v2-v1']).encode()).hexdigest())
    manifest=output.with_suffix('.openvoice.json')
    if output.is_file() and manifest.is_file():
        try:
            cached=json.loads(manifest.read_text(encoding='utf-8'))
            if cached['key']==key and cached['output_sha256']==file_hash(output):return output
        except (ValueError,KeyError,OSError):pass
    output.parent.mkdir(parents=True,exist_ok=True)
    duration=probe_audio_duration(source)
    with tempfile.TemporaryDirectory(prefix='openvoice-',dir=output.parent) as attempt:
        attempt=Path(attempt);reference=attempt/'reference.wav';converted=attempt/'converted.wav';normalized=attempt/'normalized.wav'
        result=await run_process([config.ffmpeg_path,'-y','-ss',str(start_ms/1000),'-i',str(video),'-t',str((end_ms-start_ms)/1000),'-vn','-ac','1','-ar','22050',str(reference)],timeout=60,cancel_check=cancel_check)
        if result.returncode!=0:raise RuntimeError('មិនអាចទាញសំឡេងគំរូពីវីដេអូបានទេ។')
        await _infer(source,reference,converted,cancel_check)
        actual=probe_audio_duration(converted)
        if actual<=0 or abs(actual-duration)>0.12:raise RuntimeError('OpenVoice changed the speech duration; output rejected')
        result=await run_process([config.ffmpeg_path,'-y','-i',str(converted),'-af',f'apad,atrim=0:{duration:.6f}', '-ar','48000','-ac','2','-c:a','pcm_s16le',str(normalized)],timeout=60,cancel_check=cancel_check)
        if cancel_check and cancel_check():raise asyncio.CancelledError('Voice conversion cancelled')
        if result.returncode!=0:raise RuntimeError('Could not normalize converted voice')
        if abs(probe_audio_duration(normalized)-duration)>0.005:raise RuntimeError('Converted audio failed timing validation')
        normalized.replace(output)
        temporary=manifest.with_suffix('.tmp')
        temporary.write_text(json.dumps({'key':key,'engine':'openvoice_v2','output_sha256':file_hash(output),'duration':duration}),encoding='utf-8')
        temporary.replace(manifest)
    return output
