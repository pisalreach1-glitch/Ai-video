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
from app.domain.sync import SyncPolicy, SyncPlanningError
from app.services.sync_slots import plan_speech_slots
from app.services.sync_fitting import fit_clip_to_slot
from app.services.sync_validation import build_absolute_placements, validate_sync
from app.services.audio_fit import decode_mp3_to_wav, apply_atempo
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
    sync_policy: SyncPolicy | None = None,
) -> DubbingPlan:
    """
    Synthesizes each translated segment, decodes to PCM WAV, applies strict speech-window
    tempo fitting (fit_clip_to_slot), builds absolute placements, and validates sync.
    In multi-speaker mode, resolves the chosen voice for each segment individually.
    """
    plan.clips.clear()
    plan.placements.clear()
    # Retain non-synthesis issues instead of accumulating duplicates
    synthesis_issue_types = {
        "too_long", "collision", "overrun", "unknown_speaker",
        "missing_translation", "missing_source", "missing_voice", "invalid_voice",
        "unready_translation", "fit_failed", "start_offset", "late_end",
        "placement_audio_mismatch", "placement_source_mismatch", "sync_planning_error",
    }
    plan.issues = [i for i in plan.issues if i.issue_type not in synthesis_issue_types]

    policy = sync_policy or SyncPolicy(
        max_tempo=config.dub_max_tempo,
        start_tolerance_ms=config.dub_sync_start_tolerance_ms,
        end_tolerance_ms=config.dub_sync_end_tolerance_ms,
        filter_duration_tolerance_ms=config.dub_sync_filter_duration_tolerance_ms,
        guard_ms=config.dub_sync_guard_ms,
        sample_rate=config.dub_sample_rate,
    )
    plan.sample_rate = policy.sample_rate
    plan.sync_policy_metadata = {
        "max_tempo": policy.max_tempo,
        "start_tolerance_ms": policy.start_tolerance_ms,
        "end_tolerance_ms": policy.end_tolerance_ms,
        "filter_duration_tolerance_ms": policy.filter_duration_tolerance_ms,
        "guard_ms": policy.guard_ms,
        "sample_rate": policy.sample_rate,
    }

    if plan.source_duration_ms <= 0 and plan.segments:
        plan.source_duration_ms = max(s.end_ms for s in plan.segments)

    try:
        slots = plan_speech_slots(plan.segments, plan.source_duration_ms, policy)
    except SyncPlanningError as spe:
        logger.warning(f"Sync planning error for job {job_id}: {spe}")
        plan.issues.append(DubbingIssue(
            segment_id="global",
            issue_type="sync_planning_error",
            message=f"បញ្ហាកំណត់ Speech Window: {spe}",
            severity="blocking",
            producer="sync_slots",
        ))
        return plan

    translations_by_id = {t.segment_id: t for t in plan.translations}
    available_voices = await get_available_voices()
    available_voice_ids = {v["ShortName"] for v in available_voices}

    async def tempo_writer(input_path: Path, output_path: Path, factor: float) -> Path:
        return await apply_atempo(
            input_wav=input_path,
            output_wav=output_path,
            tempo=factor,
            sample_rate=policy.sample_rate,
            channels=2,
            cancel_check=cancel_check,
        )

    # Order by source timing to match the speech sequence
    ordered_segments = sorted(plan.segments, key=lambda s: (s.start_ms, s.end_ms, s.segment_id))

    for source in ordered_segments:
        if cancel_check and cancel_check():
            raise asyncio.CancelledError("Synthesis cancelled.")

        sid = source.segment_id
        slot = slots[sid]
        t_seg = translations_by_id.get(sid)

        if not t_seg:
            plan.issues.append(DubbingIssue(
                segment_id=sid,
                issue_type="missing_translation",
                message=f"មិនមានការបកប្រែសម្រាប់ឃ្លា {sid} ឡើយ។",
                severity="blocking",
                producer="synthesis",
            ))
            continue

        text = t_seg.translated_text.strip()
        if not text:
            plan.issues.append(DubbingIssue(
                segment_id=sid,
                issue_type="missing_translation",
                message=f"ឃ្លា {sid} គ្មានអត្ថបទបកប្រែឡើយ។",
                severity="blocking",
                producer="synthesis",
            ))
            continue

        if require_confirmed_voices and t_seg.status == "needs_review":
            plan.issues.append(DubbingIssue(
                segment_id=sid,
                issue_type="unready_translation",
                message=f"ឃ្លា {sid} ស្ថិតក្នុងស្ថានភាពត្រូវពិនិត្យ (needs_review) មុនអនុម័ត។",
                severity="blocking",
                producer="synthesis",
            ))
            continue

        # Resolve voice per utterance
        if plan.speaker_mode == "multi":
            if audition_speaker_id and (not audition_segment_id or sid == audition_segment_id):
                choice = plan.speaker_voice_map.get(audition_speaker_id)
                voice = choice.voice_id if choice else settings.voice
                speed = choice.rate if choice else settings.speed
                cache_key = compute_tts_cache_key(text, voice, speed)
            else:
                asgn = plan.get_assignment(sid)
                if not asgn or not asgn.speaker_id:
                    plan.issues.append(DubbingIssue(
                        segment_id=sid,
                        issue_type="unknown_speaker",
                        message=f"ឃ្លា {sid} មិនទាន់បានកំណត់អ្នកនិយាយឡើយ។",
                        severity="blocking",
                        producer="synthesis",
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
                            segment_id=sid,
                            issue_type=str(ve),
                            message=f"បញ្ហាសំឡេងលើឃ្លា {sid} ({ve})",
                            severity="blocking",
                            producer="synthesis",
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

        seg_dir = workspace.get_segment_dir(job_id, revision_id, sid)
        raw_mp3 = workspace.get_segment_voice_mp3(job_id, revision_id, sid)
        raw_wav = workspace.get_segment_voice_wav(job_id, revision_id, sid)
        events_json_path = workspace.get_segment_tts_events_path(job_id, revision_id, sid)
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
            raise asyncio.CancelledError("Synthesis cancelled.")

        # Decode MP3 to standardized 48kHz 16-bit PCM stereo WAV
        if not raw_wav.exists() or raw_wav.stat().st_size == 0:
            await decode_mp3_to_wav(
                mp3_path=raw_mp3,
                wav_path=raw_wav,
                sample_rate=policy.sample_rate,
                channels=2,
                trim_silence=True,
            )

        clip = DubClip(
            segment_id=sid,
            tts_cache_key=cache_key,
            raw_audio_path=str(raw_wav),
            raw_duration_ms=0,
            tts_events=timing_events,
            status="pending",
        )

        # Fit clip to speech window
        fitted_clip = await fit_clip_to_slot(
            clip=clip,
            slot=slot,
            policy=policy,
            output_dir=seg_dir,
            tempo_writer=tempo_writer,
            cancel_check=cancel_check,
        )

        plan.clips.append(fitted_clip)

        if fitted_clip.status == "too_long":
            lag_ms = fitted_clip.raw_duration_ms - (slot.source_end_ms - slot.start_ms)
            plan.issues.append(DubbingIssue(
                segment_id=sid,
                issue_type="too_long",
                message=(
                    f"ឃ្លា {sid} មានប្រវែង {fitted_clip.raw_duration_ms}ms "
                    f"លើសពី speech window ({slot.start_ms}ms–{slot.source_end_ms}ms)។ "
                    f"សំឡេងបញ្ចប់យឺត {max(0.0, lag_ms / 1000.0):.2f} វិនាទី។"
                ),
                severity="blocking",
                producer="sync_fitting",
            ))
        elif fitted_clip.status == "failed":
            plan.issues.append(DubbingIssue(
                segment_id=sid,
                issue_type="fit_failed",
                message=f"បរាជ័យក្នុងការតម្រឹមសំឡេងលើឃ្លា {sid}។",
                severity="blocking",
                producer="sync_fitting",
            ))

    # If all clips are ready and cover all segments, build absolute placements and validate sync
    if all(c.status == "ready" for c in plan.clips) and len(plan.clips) == len(plan.segments):
        try:
            plan.placements = build_absolute_placements(plan, slots, policy)
            sync_problems = validate_sync(plan, slots, policy)
            for prob in sync_problems:
                plan.issues.append(DubbingIssue(
                    segment_id=prob.segment_id,
                    issue_type=prob.issue_type,
                    message=prob.message,
                    severity=prob.severity,
                    producer=prob.producer,
                ))
        except Exception as ex:
            logger.warning(f"Sync validation warning for job {job_id}: {ex}")

    return plan
