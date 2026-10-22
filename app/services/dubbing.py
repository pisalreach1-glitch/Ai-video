"""Orchestrator for per-utterance TTS synthesis, caching, and duration fitting."""
from __future__ import annotations
import hashlib
import json
import logging
from pathlib import Path
from typing import Callable, Any
from app.config import config
from app.domain.models import VoiceSettings
from app.domain.dubbing import DubbingPlan, DubClip, DubbingIssue, SourceSegment, TranslatedSegment
from app.services.tts import generate_narration
from app.services.audio_fit import decode_mp3_to_wav, fit_clip
from app.storage.workspaces import workspace

logger = logging.getLogger(__name__)

def compute_tts_cache_key(text: str, voice: str, speed: str) -> str:
    raw = f"{voice}:{speed}:{text.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

async def synthesize_and_fit_plan(
    plan: DubbingPlan,
    job_id: str,
    revision_id: int,
    settings: VoiceSettings,
    cancel_check: Callable[[], bool] | None = None,
) -> DubbingPlan:
    """
    Synthesizes each translated segment, decodes to PCM WAV, applies tempo fitting,
    and identifies any overlong or colliding segments.
    """
    plan.clips.clear()
    plan.issues.clear()

    voice = settings.voice
    speed = settings.speed

    for i, t_seg in enumerate(plan.translations):
        if cancel_check and cancel_check():
            raise RuntimeError("Synthesis cancelled.")

        s_seg = plan.get_segment(t_seg.segment_id)
        if not s_seg:
            plan.issues.append(DubbingIssue(
                segment_id=t_seg.segment_id,
                issue_type="missing_source",
                message=f"Missing corresponding source segment for {t_seg.segment_id}",
                severity="blocking",
            ))
            continue

        text = t_seg.translated_text.strip()
        if not text:
            plan.issues.append(DubbingIssue(
                segment_id=t_seg.segment_id,
                issue_type="missing_translation",
                message=f"Segment {t_seg.segment_id} has empty translation text.",
                severity="blocking",
            ))
            continue

        cache_key = compute_tts_cache_key(text, voice, speed)
        seg_dir = workspace.get_segment_dir(job_id, revision_id, t_seg.segment_id)
        raw_mp3 = workspace.get_segment_voice_mp3(job_id, revision_id, t_seg.segment_id)
        raw_wav = workspace.get_segment_voice_wav(job_id, revision_id, t_seg.segment_id)
        events_json_path = workspace.get_segment_tts_events_path(job_id, revision_id, t_seg.segment_id)

        # Generate audio via Edge-TTS (or reuse cached)
        timing_events: list[dict[str, Any]] = []
        if not raw_mp3.exists() or raw_mp3.stat().st_size == 0 or not events_json_path.exists():
            _, actual_sec, events = await generate_narration(
                text=text,
                voice=voice,
                rate=speed,
                output_audio_path=raw_mp3,
                cancel_check=cancel_check,
            )
            timing_events = events
            events_json_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            try:
                timing_events = json.loads(events_json_path.read_text(encoding="utf-8"))
            except Exception:
                timing_events = []

        if cancel_check and cancel_check():
            raise RuntimeError("Synthesis cancelled.")

        # Decode MP3 to standardized 48kHz 16-bit PCM stereo WAV
        if not raw_wav.exists() or raw_wav.stat().st_size == 0:
            await decode_mp3_to_wav(
                mp3_path=raw_mp3,
                wav_path=raw_wav,
                sample_rate=plan.sample_rate,
                channels=2,
            )

        clip = DubClip(
            segment_id=t_seg.segment_id,
            tts_cache_key=cache_key,
            raw_audio_path=str(raw_wav),
            raw_duration_ms=0,
            tts_events=timing_events,
            status="pending",
        )

        # Calculate available window before the next utterance starts (preventing collisions)
        next_s_seg = plan.segments[i + 1] if i + 1 < len(plan.segments) else None
        if next_s_seg and next_s_seg.start_ms > s_seg.start_ms:
            avail_ms = next_s_seg.start_ms - s_seg.start_ms
        else:
            avail_ms = max(s_seg.duration_ms, plan.source_duration_ms - s_seg.start_ms)

        # Run duration fitting against source slot and available gap
        fitted_clip = await fit_clip(
            clip=clip,
            source_segment=s_seg,
            max_tempo=config.dub_max_tempo,
            sample_rate=plan.sample_rate,
            available_slot_ms=avail_ms,
        )

        plan.clips.append(fitted_clip)

        if fitted_clip.status == "too_long":
            plan.issues.append(DubbingIssue(
                segment_id=t_seg.segment_id,
                issue_type="too_long",
                message=(
                    f"ឃ្លា {t_seg.segment_id} មានប្រវែង {fitted_clip.raw_duration_ms}ms "
                    f"ដែលលើសពីពេលវេលា {avail_ms}ms ក្នុងវីដេអូដើម។"
                ),
                severity="blocking",
            ))

    return plan
