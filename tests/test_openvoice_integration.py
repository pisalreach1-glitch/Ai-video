import asyncio
import json
import shutil
import subprocess
from unittest.mock import AsyncMock
import pytest
from app.domain.dubbing import DubbingPlan,SourceSegment
from app.services import openvoice_service as service

def test_reference_never_includes_adjacent_unknown_speakers():
    first=SourceSegment('s1',1000,1600,'one')
    second=SourceSegment('s2',1600,7000,'two')
    assert service.reference_window(DubbingPlan(segments=[first,second]),first)==(1000,1600)

@pytest.mark.asyncio
async def test_cancelled_conversion_stops_before_processing(monkeypatch):
    with pytest.raises(asyncio.CancelledError):
        await service.convert_segment('missing.wav','missing.mp4',0,1000,'out.wav',cancel_check=lambda:True)

@pytest.mark.asyncio
async def test_conversion_cache_is_validated_and_reference_changes_invalidate(session_media_dir,tmp_path,monkeypatch):
    from app.config import config
    root=tmp_path/'project'
    model=root/'models'/'openvoice_v2'/'converter'
    model.mkdir(parents=True)
    (model/'checkpoint.pth').write_bytes(b'fixture-model')
    (model/'config.json').write_text('{}')
    monkeypatch.setattr(service,'ROOT',root)
    async def infer(source,reference,output,cancel_check=None):
        shutil.copyfile(source,output)
    inference=AsyncMock(side_effect=infer)
    monkeypatch.setattr(service,'_infer',inference)
    source=session_media_dir['audio_sample']
    video=session_media_dir['video_with_audio']
    output=tmp_path/'converted.wav'
    await service.convert_segment(source,video,0,1000,output)
    await service.convert_segment(source,video,0,1000,output)
    assert inference.await_count==1
    assert json.loads(output.with_suffix('.openvoice.json').read_text())['engine']=='openvoice_v2'
    await service.convert_segment(source,video,500,1500,output)
    assert inference.await_count==2
    output.write_bytes(b'corrupt')
    await service.convert_segment(source,video,500,1500,output)
    assert inference.await_count==3

@pytest.mark.asyncio
async def test_bad_model_output_cannot_be_reported_as_success(session_media_dir,tmp_path,monkeypatch):
    root=tmp_path/'project'
    model=root/'models'/'openvoice_v2'/'converter'
    model.mkdir(parents=True)
    (model/'checkpoint.pth').write_bytes(b'fixture-model')
    (model/'config.json').write_text('{}')
    monkeypatch.setattr(service,'ROOT',root)
    monkeypatch.setattr(service,'_infer',AsyncMock())
    output=tmp_path/'converted.wav'
    with pytest.raises(RuntimeError,match='duration'):
        await service.convert_segment(session_media_dir['audio_sample'],session_media_dir['video_with_audio'],0,1000,output)
    assert not output.exists()
    assert not output.with_suffix('.openvoice.json').exists()

@pytest.mark.asyncio
async def test_dubbing_uses_clean_khmer_audio_and_source_utterance(session_media_dir,temp_job_storage,temp_workspace,monkeypatch):
    import wave
    from app.services import dubbing
    from app.domain.models import VoiceSettings
    from app.domain.dubbing import TranslatedSegment
    monkeypatch.setenv('OPENVOICE_ENABLED','true')
    monkeypatch.setattr('app.storage.jobs.job_storage',temp_job_storage)
    monkeypatch.setattr(dubbing,'workspace',temp_workspace)
    monkeypatch.setattr(dubbing,'get_available_voices',AsyncMock(return_value=[{'ShortName':'km-KH-SreymomNeural'}]))
    job=temp_job_storage.create_job(user_id=1,chat_id=1)
    from app.services.media import probe_media
    video=session_media_dir['video_with_audio']
    temp_job_storage.set_job_source(job.job_id,str(video),probe_media(video))
    async def tts(**kwargs):
        kwargs['output_audio_path'].write_bytes(b'fixture-mp3')
        return kwargs['output_audio_path'],1.0,[{'start':0,'end':1,'text':'សួស្តី'}]
    async def decode(**kwargs):
        with wave.open(str(kwargs['wav_path']),'wb') as stream:
            stream.setparams((2,2,48000,0,'NONE','not compressed'))
            stream.writeframes(b'\x01\x00\x01\x00'*48000)
        return kwargs['wav_path']
    async def convert(source,video,start,end,output,cancel_check=None):
        shutil.copyfile(source,output)
        return output
    converter=AsyncMock(side_effect=convert)
    monkeypatch.setattr(dubbing,'generate_narration',tts)
    monkeypatch.setattr(dubbing,'decode_mp3_to_wav',decode)
    monkeypatch.setattr(service,'convert_segment',converter)
    value=DubbingPlan(source_duration_ms=2000,segments=[SourceSegment('s1',0,2000,'Hello')],translations=[TranslatedSegment('s1','សួស្តី',status='ready')])
    result=await dubbing.synthesize_and_fit_plan(value,job.job_id,1,VoiceSettings())
    assert result.clips[0].status=='ready'
    args=converter.call_args.args
    assert args[0].name=='edge_voice.wav'
    assert args[1]==video
    assert args[2:4]==(0,2000)
    assert args[4].name!='edge_voice.wav'
