"""Tests for segment-level translation, ID-preservation, and validation."""
import asyncio
import pytest
from app.domain.dubbing import SourceSegment
from app.services.segment_translation import (
    validate_translation_response,
    TranslationValidationError,
    translate_segments,
)

def test_translation_preserves_ids_successfully():
    """Requirement 6: Response must match requested segment IDs exactly in order."""
    sources = [
        SourceSegment(segment_id="s001", start_ms=2000, end_ms=4000, source_text="Pour in the water."),
        SourceSegment(segment_id="s002", start_ms=8000, end_ms=10000, source_text="Now add the sugar."),
    ]
    response = {
        "segments": [
            {"id": "s001", "translated_text": "ចាក់ទឹកចូល។"},
            {"id": "s002", "translated_text": "ឥឡូវបន្ថែមស្ករ។"},
        ]
    }
    translated = validate_translation_response(sources, response)
    assert len(translated) == 2
    assert translated[0].segment_id == "s001"
    assert translated[0].translated_text == "ចាក់ទឹកចូល។"
    assert translated[1].segment_id == "s002"
    assert translated[1].translated_text == "ឥឡូវបន្ថែមស្ករ។"

def test_translation_rejects_missing_duplicate_or_unknown_ids():
    """Requirement 6: Missing, duplicate, or unknown IDs are strictly rejected."""
    sources = [
        SourceSegment(segment_id="s001", start_ms=2000, end_ms=4000, source_text="First"),
        SourceSegment(segment_id="s002", start_ms=5000, end_ms=7000, source_text="Second"),
    ]

    # Missing s002
    with pytest.raises(TranslationValidationError, match="missing segments"):
        validate_translation_response(sources, {"segments": [{"id": "s001", "translated_text": "ឃ្លា ១"}]})

    # Duplicate s001
    with pytest.raises(TranslationValidationError, match="duplicate segment ID"):
        validate_translation_response(sources, {
            "segments": [
                {"id": "s001", "translated_text": "ឃ្លា ១"},
                {"id": "s001", "translated_text": "ឃ្លា ១ ដដែល"},
            ]
        })

    # Unknown ID s999
    with pytest.raises(TranslationValidationError, match="unknown segment ID"):
        validate_translation_response(sources, {
            "segments": [
                {"id": "s001", "translated_text": "ឃ្លា ១"},
                {"id": "s999", "translated_text": "ឃ្លា មិនស្គាល់"},
            ]
        })

    # Empty text
    with pytest.raises(TranslationValidationError, match="empty translation"):
        validate_translation_response(sources, {
            "segments": [
                {"id": "s001", "translated_text": "ឃ្លា ១"},
                {"id": "s002", "translated_text": ""},
            ]
        })

@pytest.mark.asyncio
async def test_no_key_provider_never_produces_false_khmer_success():
    """Requirement 7: Without working translation provider, never return English transcript under Khmer success."""
    sources = [
        SourceSegment(segment_id="s001", start_ms=2000, end_ms=4000, source_text="Pour in the water."),
    ]
    # No API key configured & manual provider
    translated = await translate_segments(sources, provider="manual")
    assert len(translated) == 1
    # Does not copy English text as Khmer
    assert translated[0].translated_text != "Pour in the water."
    assert translated[0].status == "needs_review"

@pytest.mark.asyncio
async def test_gemini_translation_chunks_large_segment_counts(monkeypatch):
    """Ensure translate_segments_gemini breaks lists >35 into batches and aggregates them."""
    from app.services.segment_translation import translate_segments_gemini
    from app.domain.dubbing import TranslatedSegment

    # 80 segments
    sources = [
        SourceSegment(segment_id=f"s{i:03d}", start_ms=i * 1000, end_ms=(i + 1) * 1000, source_text=f"Text {i}")
        for i in range(1, 81)
    ]

    call_batch_sizes = []

    async def mock_batch(batch, api_key, cancel_check=None):
        call_batch_sizes.append(len(batch))
        return [
            TranslatedSegment(segment_id=s.segment_id, translated_text=f"Khmer {s.segment_id}", status="ready")
            for s in batch
        ]

    monkeypatch.setattr("app.services.segment_translation._translate_single_batch_gemini", mock_batch)

    results = await translate_segments_gemini(sources, api_key="dummy_key")
    assert len(results) == 80
    assert call_batch_sizes == [35, 35, 10]
    assert results[0].translated_text == "Khmer s001"
    assert results[-1].translated_text == "Khmer s080"

@pytest.mark.asyncio
async def test_shorten_single_segment_khmer_no_key_returns_original(monkeypatch):
    """When GEMINI_API_KEY is missing, shorten_single_segment_khmer returns the current Khmer text."""
    from app.services.segment_translation import shorten_single_segment_khmer
    monkeypatch.setenv("GEMINI_API_KEY", "")
    res = await shorten_single_segment_khmer("Chinese text", "អត្ថបទខ្មែរវែង", target_duration_s=1.5)
    assert res == "អត្ថបទខ្មែរវែង"

@pytest.mark.asyncio
async def test_shorten_overlong_segments_mapping(monkeypatch):
    """Ensure shorten_overlong_segments correctly parses and maps shortened text."""
    from app.services.segment_translation import shorten_overlong_segments
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_key")

    class DummyItem:
        def __init__(self, id, text):
            self.id = id
            self.shortened_text = text

    class DummyBatch:
        def __init__(self, segments):
            self.segments = segments

    def mock_call():
        return DummyBatch([
            DummyItem("s001", "ផ្កាឈូកធំ"),
            DummyItem("s002", "រៀបចំសំណង់"),
        ])

    monkeypatch.setattr("asyncio.to_thread", lambda fn: asyncio.sleep(0.01, result=mock_call()))

    items = [
        {"id": "s001", "source_text": "text1", "current_khmer": "long1", "target_seconds": 1.5},
        {"id": "s002", "source_text": "text2", "current_khmer": "long2", "target_seconds": 2.0},
    ]
    res = await shorten_overlong_segments(items)
    assert res == {"s001": "ផ្កាឈូកធំ", "s002": "រៀបចំសំណង់"}
