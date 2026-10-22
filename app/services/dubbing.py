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

from app.services.speaker_voices import resolve_voice, speaker_tts_cache_key, VoiceSelectionRequired
from app.services.voices import get_available_voices

async def synthesize_and_fit_plan(
    plan: DubbingPlan,
    job_id: str,
    revision_id: int,
    settings: VoiceSettings,
    cancel_check: Callable[[], bool] | None = None,
    require_confirmed_voices: bool = False,
    audition_speaker_id: str | None = None,
    audition_segment_id: str | None = None,
) -> DubbingPlan:
    """
    Synthesizes each translated segment, decodes to PCM WAV, applies tempo fitting,
    and identifies any overlong or colliding segments.
    In multi-speaker mode, resolves the chosen voice for each segment individually.
    """
    plan.clips.clear()
    # Retain non-synthesis issues instead of accumulating duplicates
    synthesis_issue_types = {
        "too_long", "collision", "overrun", "unknown_speaker",
        "missing_translation", "missing_source", "missing_voice", "invalid_voice"
    }
    plan.issues = [i for i in plan.issues if i.issue_type not in synthesis_issue_types]

    available_voices = await get_available_voices()
    available_voice_ids = {v["ShortName"] for v in available_voices}

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

        # Resolve voice per utterance
        if plan.speaker_mode == "multi":
            if audition_speaker_id and (not audition_segment_id or t_seg.segment_id == audition_segment_id):
                choice = plan.speaker_voice_map.get(audition_speaker_id)
                voice = choice.voice_id if choice else settings.voice
                speed = choice.rate if choice else settings.speed
                cache_key = compute_tts_cache_key(text, voice, speed)
            else:
                asgn = plan.get_assignment(t_seg.segment_id)
                if not asgn or not asgn.speaker_id:
                    plan.issues.append(DubbingIssue(
                        segment_id=t_seg.segment_id,
                        issue_type="unknown_speaker",
                        message=f"ឃ្លា {t_seg.segment_id} មិនទាន់បានកំណត់អ្នកនិយាយឡើយ។",
                        severity="blocking",
                    ))
                    if require_confirmed_voices:
                        continue
                    # For audition/preview, use the default speaker voice so preview is audible
                    default_spk = plan.speakers[0].speaker_id if plan.speakers else "Speaker A"
                    choice = plan.speaker_voice_map.get(default_spk)
                    voice = choice.voice_id if choice else settings.voice
                    speed = choice.rate if choice else settings.speed
                    cache_key = compute_tts_cache_key(text, voice, speed)
                else:
                    try:
                        choice = resolve_voice(
                            assignment=asgn,
                            voice_map=plan.speaker_voice_map,
                            available_voice_ids=available_voice_ids,
                            require_confirmed=require_confirmed_voices,
                        )
                        voice = choice.voice_id
                        speed = choice.rate
                        cache_key = speaker_tts_cache_key(text, choice, "edge-tts")
                    except VoiceSelectionRequired as ve:
                        plan.issues.append(DubbingIssue(
                            segment_id=t_seg.segment_id,
                            issue_type=str(ve),
                            message=f"បញ្ហាសំឡេងលើឃ្លា {t_seg.segment_id} ({ve})",
                            severity="blocking",
                        ))
                        if require_confirmed_voices:
                            continue
                        default_spk = plan.speakers[0].speaker_id if plan.speakers else "Speaker A"
                        choice = plan.speaker_voice_map.get(default_spk)
                        voice = choice.voice_id if choice else settings.voice
                        speed = choice.rate if choice else settings.speed
                        cache_key = compute_tts_cache_key(text, voice, speed)
        else:
            voice = settings.voice
            speed = settings.speed
            cache_key = compute_tts_cache_key(text, voice, speed)

        seg_dir = workspace.get_segment_dir(job_id, revision_id, t_seg.segment_id)
        raw_mp3 = workspace.get_segment_voice_mp3(job_id, revision_id, t_seg.segment_id)
        raw_wav = workspace.get_segment_voice_wav(job_id, revision_id, t_seg.segment_id)
        events_json_path = workspace.get_segment_tts_events_path(job_id, revision_id, t_seg.segment_id)
        manifest_key_path = seg_dir / "tts_cache_key.txt"

        # Check if cached audio exists AND matches the exact cache key
        can_reuse_audio = (
            raw_mp3.exists()
            and raw_mp3.stat().st_size > 0
            and events_json_path.exists()
            and manifest_key_path.exists()
            and manifest_key_path.read_text(encoding="utf-8").strip() == cache_key
        )

        timing_events: list[dict[str, Any]] = []
        if not can_reuse_audio:
            # Stale or missing audio -> regenerate
            raw_mp3.unlink(missing_ok=True)
            raw_wav.unlink(missing_ok=True)
            events_json_path.unlink(missing_ok=True)

            _, actual_sec, events = await generate_narration(
                text=text,
                voice=voice,
                rate=speed,
                output_audio_path=raw_mp3,
                cancel_check=cancel_check,
            )
            timing_events = events
            events_json_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest_key_path.write_text(cache_key, encoding="utf-8")
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
                trim_silence=True,
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
