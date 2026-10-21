"""Tests for segment-level translation, ID-preservation, and validation."""
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
