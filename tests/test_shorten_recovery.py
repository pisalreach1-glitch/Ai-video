from unittest.mock import AsyncMock, Mock
import pytest
from aiogram.types import CallbackQuery, User
from app.domain.dubbing import DubbingPlan, SourceSegment, TranslatedSegment, DubClip

def plan():
    return DubbingPlan(source_duration_ms=9000,
        segments=[SourceSegment('s008',1000,1600,'Hello'),SourceSegment('s009',8000,8600,'Goodbye')],
        translations=[TranslatedSegment('s008','ឃ្លាវែង'),TranslatedSegment('s009','ឃ្លាវែងទៀត')],
        clips=[DubClip('s008','a','a.wav',status='too_long'),DubClip('s009','b','b.wav',status='too_long')])

def callback(data):
    return CallbackQuery(id='test',from_user=User(id=1,is_bot=False,first_name='Test'),chat_instance='test',data=data)

@pytest.mark.asyncio
@pytest.mark.parametrize('single',[False,True])
async def test_shortening_resumes_with_real_immutable_callback_and_exact_window(monkeypatch,single):
    from app.handlers import dubbing
    saved=plan()
    monkeypatch.setattr(dubbing,'verify_callback_job',AsyncMock(return_value=True))
    monkeypatch.setattr(dubbing,'load_dubbing_plan',lambda *args:saved)
    monkeypatch.setattr(dubbing,'save_dubbing_plan',Mock())
    monkeypatch.setattr(dubbing,'invalidate_segment_tts',Mock())
    monkeypatch.setattr(CallbackQuery,'answer',AsyncMock())
    proceed=AsyncMock()
    monkeypatch.setattr(dubbing,'execute_dubbing_proceed',proceed)
    shorten=AsyncMock(return_value='ខ្លី' if single else {'s008':'ខ្លី','s009':'ខ្លីទៀត'})
    monkeypatch.setattr(dubbing,'shorten_single_segment_khmer' if single else 'shorten_overlong_segments',shorten)
    data='d_sh:job:1:s008' if single else 'd_sha:job:1'
    call=callback(data)
    state=object()
    handler=dubbing.cb_dubbing_shorten_single_segment if single else dubbing.cb_dubbing_shorten_all_overlong_segments
    await handler(call,state)
    assert call.data==data
    proceed.assert_awaited_once_with(call,'job',1,state=state,acknowledge=False)
    if single:
        assert shorten.call_args.kwargs['target_duration_s']==0.6
    else:
        assert [item['target_seconds'] for item in shorten.call_args.args[0]]==[0.6,0.6]
    assert saved.get_translation('s008').full_translation=='ឃ្លាវែង'

@pytest.mark.asyncio
async def test_already_shortened_batch_continues_without_another_ai_request(monkeypatch):
    from app.handlers import dubbing
    saved=plan()
    saved.clips=[]
    monkeypatch.setattr(dubbing,'verify_callback_job',AsyncMock(return_value=True))
    monkeypatch.setattr(dubbing,'load_dubbing_plan',lambda *args:saved)
    monkeypatch.setattr(CallbackQuery,'answer',AsyncMock())
    proceed=AsyncMock()
    monkeypatch.setattr(dubbing,'execute_dubbing_proceed',proceed)
    call=callback('d_sha:job:1')
    await dubbing.cb_dubbing_shorten_all_overlong_segments(call)
    proceed.assert_awaited_once_with(call,'job',1,state=None,acknowledge=False)
