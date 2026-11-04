from unittest.mock import AsyncMock
import pytest
from app.domain.dubbing import DubbingPlan,SourceSegment,TranslatedSegment,DubClip
from app.services.auto_fit import auto_fit_overlong,safe_proposal

def plan():
    return DubbingPlan(source_duration_ms=1000,segments=[SourceSegment('s001',0,600,'Hello')],
        translations=[TranslatedSegment('s001','សួស្តីអ្នកទាំងអស់គ្នា')],
        clips=[DubClip('s001','key','voice.wav',status='too_long')])

@pytest.mark.asyncio
async def test_automatically_repairs_and_resynthesizes_without_clicks():
    value=plan()
    async def synthesize(updated):
        updated.clips[0].status='ready'
        return updated
    shorten=AsyncMock(return_value={'s001':'សួស្តី'})
    result=await auto_fit_overlong(value,shorten,synthesize)
    assert result.clips[0].status=='ready'
    assert result.translations[0].full_translation=='សួស្តីអ្នកទាំងអស់គ្នា'
    assert shorten.call_args.args[0][0]['target_seconds']==0.6

@pytest.mark.asyncio
async def test_still_overlong_is_bounded_at_two_attempts():
    value=plan()
    shorten=AsyncMock(side_effect=[{'s001':'សួស្តីអ្នកទាំងអស់'},{'s001':'សួស្តី'}])
    synthesize=AsyncMock(side_effect=lambda value:value)
    result=await auto_fit_overlong(value,shorten,synthesize)
    assert shorten.await_count==2
    assert synthesize.await_count==2
    assert result.clips[0].status=='too_long'

@pytest.mark.asyncio
async def test_provider_failure_preserves_original_for_review():
    value=plan()
    synthesize=AsyncMock()
    result=await auto_fit_overlong(value,AsyncMock(side_effect=RuntimeError('offline')),synthesize)
    assert result.translations[0].translated_text=='សួស្តីអ្នកទាំងអស់គ្នា'
    synthesize.assert_not_awaited()

def test_rejects_dropped_numbers_negation_and_empty_text():
    assert not safe_proposal('កុំដាក់អំបិល ២ ស្លាបព្រា','ដាក់អំបិល ២ ស្លាបព្រា')
    assert not safe_proposal('ដាក់ទឹក ២ លីត្រ','ដាក់ទឹក')
    assert not safe_proposal('សួស្តី','')
    assert safe_proposal('ដាក់ទឹក ២ លីត្រ','បន្ថែមទឹក 2 លីត្រ')
