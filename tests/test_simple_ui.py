from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.ui import keyboards as kb

def callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]

def test_primary_menus_keep_details_in_advanced_controls():
    assert callbacks(kb.main_menu_keyboard(True)) == ['nav_new_video','nav_resume','nav_my_videos:1','nav_more']
    assert 'nav_my_settings' in callbacks(kb.more_menu_keyboard())
    assert 'nav_talking_photo' not in callbacks(kb.more_menu_keyboard())
    assert 'mode_free:job' not in callbacks(kb.mode_choice_keyboard('job'))
    assert 'mode_free:job' in callbacks(kb.mode_choice_keyboard('job',advanced=True))
    basic=callbacks(kb.dubbing_review_keyboard('job',1,1,1,[('s001','1')]))
    detailed=callbacks(kb.dubbing_review_keyboard('job',1,1,1,[('s001','1')],advanced=True))
    assert 'd_proc:job:1' in basic
    assert 'd_more:job:1:1' in basic
    assert 'edit_voice:job:1' not in basic
    assert 'edit_voice:job:1' in detailed
    assert 'd_spk:job:1' in detailed

def test_new_controls_fit_telegram_callback_limit():
    job='12345678-1234-1234-1234-123456789abc'
    menus=[kb.main_menu_keyboard(True),kb.more_menu_keyboard(),kb.mode_choice_keyboard(job),
           kb.mode_choice_keyboard(job,advanced=True),kb.dubbing_review_keyboard(job,9999,999,999,[],advanced=True),
           kb.dubbing_review_keyboard(job,9999,999,999,[])]
    assert all(len(data.encode('utf-8'))<=64 for menu in menus for data in callbacks(menu))

@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
@pytest.mark.parametrize("expired_ack", [False, True])
async def test_translation_automatically_continues_only_when_complete(temp_job_storage,temp_preferences,temp_workspace,monkeypatch,complete,expired_ack):
    from app.handlers import modes,common,dubbing
    from app.storage import dubbing as plans
    from app.domain.models import MediaInfo
    from app.domain.states import JobState
    from app.domain.dubbing import SourceSegment,TranslatedSegment
    monkeypatch.setattr(modes,'job_storage',temp_job_storage)
    monkeypatch.setattr(common,'job_storage',temp_job_storage)
    monkeypatch.setattr(modes,'preferences_storage',temp_preferences)
    monkeypatch.setattr(plans,'workspace',temp_workspace)
    monkeypatch.setattr(modes,'safe_edit_message',AsyncMock())
    review=AsyncMock()
    monkeypatch.setattr(dubbing,'render_segment_review_page',review)
    proceed=AsyncMock()
    monkeypatch.setattr(dubbing,'execute_dubbing_proceed',proceed)
    monkeypatch.setattr('app.services.segment_translation.translate_segments',AsyncMock(return_value=[TranslatedSegment('s001','សួស្តី' if complete else '',status='ready' if complete else 'needs_review')]))
    job=temp_job_storage.create_job(user_id=1,chat_id=2)
    temp_job_storage.set_job_source(job.job_id,'source.mp4',MediaInfo(640,360,2,True))
    temp_job_storage.set_job_status(job.job_id,JobState.AWAITING_TEXT)
    plans.save_source_segments(job.job_id,[SourceSegment('s001',0,2000,'Hello')])
    call=SimpleNamespace(data=f'mode_dub:{job.job_id}',from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(chat=SimpleNamespace(id=2),answer=AsyncMock()),answer=AsyncMock())
    if expired_ack:
        from aiogram.exceptions import TelegramBadRequest
        from aiogram.methods import AnswerCallbackQuery
        call.answer.side_effect=TelegramBadRequest(method=AnswerCallbackQuery(callback_query_id="expired"),message="query is too old and response timeout expired or query ID is invalid")
    state=SimpleNamespace(update_data=AsyncMock(),set_state=AsyncMock())
    await modes.cb_choose_source_timed_dubbing(call,state)
    if complete:
        review.assert_not_awaited()
        proceed.assert_awaited_once_with(call,job.job_id,1,state=state,acknowledge=False)
    else:
        review.assert_awaited_once()
        proceed.assert_not_awaited()
    assert temp_job_storage.get_job(job.job_id).status==JobState.AWAITING_SEGMENT_REVIEW

@pytest.mark.asyncio
async def test_continue_restores_translated_review(temp_job_storage,monkeypatch):
    from app.handlers import navigation,dubbing
    from app.domain.models import VoiceSettings
    from app.domain.states import JobState
    job=temp_job_storage.create_job(user_id=1,chat_id=2)
    temp_job_storage.create_revision(job.job_id,'សួស្តី',VoiceSettings(),mode='source_timed')
    temp_job_storage.set_job_status(job.job_id,JobState.AWAITING_SEGMENT_REVIEW)
    assert temp_job_storage.get_user_active_job(1,2).job_id==job.job_id
    monkeypatch.setattr(navigation,'job_storage',temp_job_storage)
    review=AsyncMock()
    monkeypatch.setattr(dubbing,'render_segment_review_page',review)
    await navigation._resume_single_job(SimpleNamespace(),SimpleNamespace(update_data=AsyncMock(),set_state=AsyncMock()),temp_job_storage.get_job(job.job_id))
    review.assert_awaited_once()

@pytest.mark.asyncio
async def test_preview_advanced_targets_clicked_video_not_another_session(temp_job_storage,monkeypatch):
    from app.handlers import settings,common
    from app.domain.models import VoiceSettings
    from app.domain.states import JobState
    monkeypatch.setattr(settings,'job_storage',temp_job_storage)
    monkeypatch.setattr(common,'job_storage',temp_job_storage)
    jobs=[temp_job_storage.create_job(user_id=1,chat_id=2) for _ in range(2)]
    for job in jobs:
        temp_job_storage.create_revision(job.job_id,'សួស្តី',VoiceSettings())
        temp_job_storage.set_job_status(job.job_id,JobState.AWAITING_APPROVAL)
    edit=AsyncMock()
    monkeypatch.setattr(settings,'safe_edit_message',edit)
    call=SimpleNamespace(data=f'cfg_customize:{jobs[0].job_id}:1',from_user=SimpleNamespace(id=1),message=SimpleNamespace(chat=SimpleNamespace(id=2)),answer=AsyncMock())
    state=SimpleNamespace(get_data=AsyncMock(return_value={'job_id':jobs[1].job_id,'revision_id':1}),update_data=AsyncMock())
    await settings.cb_settings_customize(call,state)
    rendered=callbacks(edit.call_args.kwargs['reply_markup'])
    assert f'set_voice:{jobs[0].job_id}:1' in rendered
