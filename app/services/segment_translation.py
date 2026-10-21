"""Segment-level translation preserving segment IDs, timing contracts, and Khmer script integrity."""
from __future__ import annotations
import os
import re
import json
import asyncio
import logging
import unicodedata
from typing import Callable, Any
from app.config import config
from app.domain.dubbing import SourceSegment, TranslatedSegment

logger = logging.getLogger(__name__)

class TranslationValidationError(Exception):
    """Raised when translation output fails segment map validation."""
    pass

class TranslationProviderUnavailableError(Exception):
    """Raised when translation provider is unavailable or missing credentials."""
    pass

def validate_translation_response(
    expected_segments: list[SourceSegment],
    response_data: dict[str, Any],
    provider_name: str = "gemini",
) -> list[TranslatedSegment]:
    """
    Strict validation of provider response:
    - Exactly one translation for each requested segment ID
    - Reject missing, duplicate, or unknown IDs
    - Reject empty translations
    - Normalize text to Unicode NFC
    """
    raw_list = response_data.get("segments")
    if not isinstance(raw_list, list):
        raise TranslationValidationError("Translation response missing 'segments' array.")

    expected_ids = [s.segment_id for s in expected_segments]
    expected_set = set(expected_ids)
    received_ids = []
    received_map: dict[str, str] = {}

    for item in raw_list:
        if not isinstance(item, dict):
            raise TranslationValidationError(f"Invalid segment item in response: {item}")
        seg_id = str(item.get("id", "")).strip()
        trans_text = str(item.get("translated_text", "")).strip()

        if not seg_id:
            raise TranslationValidationError("Response segment missing 'id'.")
        if seg_id not in expected_set:
            raise TranslationValidationError(f"Response contains unknown segment ID: {seg_id}")
        if seg_id in received_map:
            raise TranslationValidationError(f"Response contains duplicate segment ID: {seg_id}")
        if not trans_text:
            raise TranslationValidationError(f"Response contains empty translation for ID: {seg_id}")

        norm_text = unicodedata.normalize("NFC", trans_text).strip()
        received_map[seg_id] = norm_text
        received_ids.append(seg_id)

    missing_ids = expected_set - set(received_map.keys())
    if missing_ids:
        raise TranslationValidationError(f"Translation response missing segments: {sorted(missing_ids)}")

    # Construct validated list in original sequence
    results: list[TranslatedSegment] = []
    for s in expected_segments:
        text = received_map[s.segment_id]
        results.append(TranslatedSegment(
            segment_id=s.segment_id,
            translated_text=text,
            translation_provider=provider_name,
            status="ready",
        ))

    return results

async def translate_segments_gemini(
    segments: list[SourceSegment],
    api_key: str,
    cancel_check: Callable[[], bool] | None = None,
) -> list[TranslatedSegment]:
    """Translate segments in batch using Gemini 2.5 Flash with structured JSON output."""
    if not segments:
        return []

    from google import genai
    from google.genai import types

    request_payload = {
        "target_language": "km",
        "segments": [
            {
                "id": s.segment_id,
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "text": s.source_text,
            }
            for s in segments
        ]
    }

    prompt = (
        "You are an expert video translator specializing in natural, concise Khmer (ភាសាខ្មែរ) dubbing.\n"
        "Translate each of the following timed video utterances into natural, fluent Khmer.\n"
        "CRITICAL RULES:\n"
        "1. You MUST return a valid JSON object matching the exact format:\n"
        '   {"segments": [{"id": "s001", "translated_text": "..."}, ...]}\n'
        "2. Keep EXACTLY the same segment IDs ('id'). Do not skip, merge, rename, or reorder any IDs.\n"
        "3. Provide natural, concise Khmer phrasing that speaks smoothly within the time slot.\n"
        "4. Preserve factual meaning, names, quantities, and steps accurately.\n"
        "5. Output ONLY the raw JSON object, without any Markdown codeblocks or comments.\n\n"
        f"{json.dumps(request_payload, ensure_ascii=False, indent=2)}"
    )

    def _call_gemini() -> str:
        client = genai.Client(api_key=api_key)
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        res = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            )
        )
        return (res.text or "").strip()

    if cancel_check and cancel_check():
        raise RuntimeError("Translation cancelled before start.")

    raw_json = await asyncio.to_thread(_call_gemini)

    if cancel_check and cancel_check():
        raise RuntimeError("Translation cancelled.")

    # Clean markdown if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_json, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise TranslationValidationError(f"Failed to parse provider JSON: {e}\nRaw output: {raw_json[:300]}")

    return validate_translation_response(segments, data, provider_name="gemini")

async def translate_segments(
    segments: list[SourceSegment],
    provider: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[TranslatedSegment]:
    """
    Main entry point for segment-level translation:
    - If Gemini API key is configured, uses Gemini 2.5 Flash.
    - If provider is unavailable or 'manual', initializes segments for manual Khmer review.
    - Never returns foreign transcript text under a claim of successful Khmer translation.
    """
    if not segments:
        return []

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    selected_provider = provider or config.translation_provider or "gemini"

    if selected_provider == "gemini" and api_key:
        try:
            return await translate_segments_gemini(segments, api_key, cancel_check=cancel_check)
        except Exception as e:
            logger.warning(f"Gemini segment translation failed: {e}. Falling back to manual review segments.")

    # If no provider key or provider is manual, create review-needed segments without false Khmer text
    results: list[TranslatedSegment] = []
    for s in segments:
        results.append(TranslatedSegment(
            segment_id=s.segment_id,
            translated_text="",
            translation_provider="manual",
            status="needs_review",
        ))
    return results
