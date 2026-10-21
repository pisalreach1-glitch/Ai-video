"""
Background Worker and Processing Job Pipeline.
Provides:
- Non-blocking execution of video processing jobs.
- Configurable maximum concurrency (default: 1 on local PC).
- Linear processing state machine:
  queued -> analyzing -> planning -> generating -> validating
  -> preview_rendering -> awaiting_approval -> final_rendering
  -> uploading -> completed
- Additional states: awaiting_manual_agent, failed, cancelled, interrupted.
- Bounded retries and secret scrubbing.
- Process tree termination on cancellation.
"""

import os
import sys
import time
import shutil
import logging
import asyncio
import threading
import traceback
from pathlib import Path
from typing import Dict, Any, Optional, Callable

from database import DatabaseManager, DbJob
from errors import (
    BotProcessingError,
    JobCancelledError,
    ProcessTimeoutError,
    QuotaExceededError,
    NetworkError,
    CorruptMediaError,
    NoAudioStreamError,
    NoSpeechDetectedError
)
from media_validator import validate_video_with_audio
from remotion_sandbox import (
    validate_composition_name,
    validate_props_file,
    get_sanitized_render_env
)
from agent_bridge import AntigravityBridge
from process_runner import kill_process_tree

logger = logging.getLogger(__name__)

MAX_RENDER_CONCURRENCY = int(os.getenv("MAX_RENDER_CONCURRENCY", "1"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))


class JobNotificationService:
    """Interface to send progress updates and finished videos back to Telegram."""
    def __init__(self, bot_app=None, get_pyro_func=None):
        self.bot_app = bot_app
        self.get_pyro_func = get_pyro_func

    async def notify_progress(self, job: DbJob, message: str, reply_markup=None):
        if not self.bot_app:
            return
        try:
            await self.bot_app.bot.send_message(
                chat_id=job.chat_id,
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"[Job {job.job_id[:8]}] Failed to send progress update: {e}")

    async def send_video_result(self, job: DbJob, video_path: str, caption: str, reply_markup=None):
        if not self.bot_app:
            return
        try:
            pyro = None
            if self.get_pyro_func:
                pyro = await self.get_pyro_func()
            if pyro and getattr(pyro, "is_connected", False):
                await pyro.send_video(
                    chat_id=job.chat_id,
                    video=video_path,
                    caption=caption,
                    supports_streaming=True
                )
                if reply_markup:
                    await self.bot_app.bot.send_message(
                        chat_id=job.chat_id,
                        text="💡 ជម្រើសកែសម្រួលបន្ថែម (Actions)៖",
                        reply_markup=reply_markup
                    )
            else:
                with open(video_path, "rb") as vf:
                    await self.bot_app.bot.send_video(
                        chat_id=job.chat_id,
                        video=vf,
                        caption=caption,
                        reply_markup=reply_markup,
                        supports_streaming=True
                    )
        except Exception as e:
            logger.error(f"[Job {job.job_id[:8]}] Failed to send video: {e}", exc_info=True)
            try:
                await self.bot_app.bot.send_message(
                    chat_id=job.chat_id,
                    text=f"✅ វីដេអូបាន Render រួចរាល់នៅ៖ `{video_path}` ប៉ុន្តែមានបញ្ហាពេលផ្ញើ៖ {str(e)[:150]}"
                )
            except Exception:
                pass


class RenderWorkerPool:
    """
    Async background worker pool managing render queue.
    """

    def __init__(
        self,
        db: DatabaseManager,
        remotion_processor,
        notifier: Optional[JobNotificationService] = None,
        max_concurrency: int = MAX_RENDER_CONCURRENCY
    ):
        self.db = db
        self.r_proc = remotion_processor
        self.notifier = notifier
        self.max_concurrency = max_concurrency
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self._new_job_event = asyncio.Event()
        self._running = False
        self._active_cancel_events: Dict[str, threading.Event] = {}
        self._active_pids: Dict[str, int] = {}
        self._worker_task: Optional[asyncio.Task] = None

    def start(self):
        if not self._running:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info(f"RenderWorkerPool started (max_concurrency={self.max_concurrency}).")

    async def stop(self):
        self._running = False
        self._new_job_event.set()
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("RenderWorkerPool stopped.")

    def notify_new_job(self):
        """Signals the worker loop that a new job is available in SQLite."""
        self._new_job_event.set()

    def cancel_job(self, job_id: str) -> bool:
        """Immediately terminates process tree and marks cancelled."""
        job = self.db.get_job(job_id)
        if not job:
            return False

        # Set cancel event
        if job_id in self._active_cancel_events:
            self._active_cancel_events[job_id].set()

        # Terminate active process tree
        pid = self._active_pids.get(job_id) or job.active_pid
        if pid:
            logger.info(f"[Job {job_id[:8]}] Terminating process tree for PID {pid}")
            kill_process_tree(pid)

        self.db.update_job_status(job_id, "cancelled", note="Cancelled via worker cancel_job")
        return True

    async def _worker_loop(self):
        """Continuous worker picking up jobs from SQLite."""
        while self._running:
            try:
                job = self.db.get_next_queued_job()
                if not job:
                    self._new_job_event.clear()
                    try:
                        await asyncio.wait_for(self._new_job_event.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        continue
                    continue

                # Acquired next job -> execute within semaphore limit
                await self.semaphore.acquire()
                asyncio.create_task(self._process_job_wrapper(job))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in worker loop: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    async def _process_job_wrapper(self, job: DbJob):
        try:
            cancel_event = threading.Event()
            self._active_cancel_events[job.job_id] = cancel_event
            await self._run_job_stages(job, cancel_event)
        finally:
            self._active_cancel_events.pop(job.job_id, None)
            self._active_pids.pop(job.job_id, None)
            self.semaphore.release()

    async def _run_job_stages(self, job: DbJob, cancel_event: threading.Event):
        """Runs the linear processing state machine."""
        job_id = job.job_id
        short_id = job_id[:8]
        params = job.params or {}

        def _check_cancel():
            if cancel_event.is_set():
                raise JobCancelledError("Job was cancelled by user.", job_id=job_id)

        try:
            logger.info(f"[Job {short_id}] Commencing processing pipeline (mode={job.mode})...")

            # -------------------------------------------------------------
            # Stage 1: ANALYZING
            # -------------------------------------------------------------
            _check_cancel()
            self.db.update_job_status(job_id, "analyzing", step_progress=0.15, note="Probing audio/video streams")
            if self.notifier:
                await self.notifier.notify_progress(
                    job,
                    f"🔍 **[Job {short_id}] ជំហានទី ១ (Analyzing)៖** ពិនិត្យសំឡេង និងទិន្នន័យវីដេអូ..."
                )

            loop = asyncio.get_running_loop()
            media_info = await loop.run_in_executor(None, validate_video_with_audio, job.input_path)

            params["duration"] = media_info.duration
            params["width"] = media_info.width
            params["height"] = media_info.height

            # -------------------------------------------------------------
            # Stage 2: PLANNING
            # -------------------------------------------------------------
            _check_cancel()
            self.db.update_job_status(job_id, "planning", step_progress=0.35, params=params, note="Transcribing speech")
            if self.notifier:
                await self.notifier.notify_progress(
                    job,
                    f"🎙️ **[Job {short_id}] ជំហានទី ២ (Planning)៖** AI កំពុងស្ដាប់សំឡេងទាញយក Timestamps & ឃ្លានិយាយ..."
                )

            words, hook_title = await loop.run_in_executor(
                None,
                lambda: self.r_proc.transcribe_video(
                    job.input_path,
                    language=params.get("language"),
                    cancel_event=cancel_event,
                    job_id=job_id
                )
            )

            if not words:
                raise NoSpeechDetectedError("No spoken speech detected in audio.", job_id=job_id)

            params["words"] = words
            params["hook_title"] = hook_title or "Trending Highlight"

            # Check if custom manual agent mode requested without automated bridge
            if job.mode == "custom" and not AntigravityBridge.is_bridge_supported():
                logger.info(f"[Job {short_id}] Unsupported custom agent bridge -> transition to awaiting_manual_agent")
                brief_path, brief_content = AntigravityBridge.generate_agent_brief(
                    job_id=job_id,
                    job_dir=Path(job.job_dir),
                    user_prompt=params.get("custom_prompt"),
                    words=words,
                    mode=job.mode
                )
                self.db.update_job_status(
                    job_id,
                    "awaiting_manual_agent",
                    step_progress=0.40,
                    params=params,
                    note=f"Exported brief to {brief_path.name}"
                )
                if self.notifier:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🚀 ប្រើ Template ស្វ័យប្រវត្តិនេះ", callback_data=f"appr:{job_id}:{job.revision_id}")],
                        [InlineKeyboardButton("🛑 បោះបង់ (Cancel)", callback_data=f"act_cancel:{job_id}")]
                    ])
                    await self.notifier.notify_progress(
                        job,
                        f"🤖 **[Job {short_id}] ជំនួយការ AI ឯកទេស (Antigravity Assistant)៖**\n\n"
                        "លោកអ្នកបានស្នើសុំ Mode Custom។ ដោយសារប្រព័ន្ធដំណើរការលើ Local PC គ្មាន Cloud Bridge ស្វ័យប្រវត្តិ ឯកសារ `agent_brief.md` ត្រូវបានបង្កើតរួចរាល់។\n\n"
                        "លោកអ្នកអាចចុច **[ 🚀 ប្រើ Template ស្វ័យប្រវត្តិនេះ ]** ដើម្បីបន្តកាត់តភ្លាមៗ ឬបោះបង់។",
                        reply_markup=kb
                    )
                return

            # -------------------------------------------------------------
            # Stage 3: GENERATING
            # -------------------------------------------------------------
            _check_cancel()
            self.db.update_job_status(job_id, "generating", step_progress=0.50, params=params, note="Generating cuts and scenes")
            if self.notifier:
                await self.notifier.notify_progress(
                    job,
                    f"✂️ **[Job {short_id}] ជំហានទី ៣ (Generating)៖** កាត់ Dead Air & រៀបចំ Smart Cuts..."
                )

            from remotion_processor import build_smart_cuts
            cuts = build_smart_cuts(words)
            params["cuts"] = cuts

            # If Mode is story, extract visual scenes
            if job.mode in ("story", "auto"):
                if getattr(self.r_proc, "gemini_transcriber", None):
                    scenes = await loop.run_in_executor(
                        None,
                        self.r_proc.gemini_transcriber.extract_visual_story_scenes,
                        words
                    )
                    import image_story_generator
                    overlays = await loop.run_in_executor(
                        None,
                        image_story_generator.generate_visual_overlays,
                        scenes,
                        self.r_proc.public_dir
                    )
                    params["story_overlays"] = overlays

            # -------------------------------------------------------------
            # Stage 4: VALIDATING
            # -------------------------------------------------------------
            _check_cancel()
            self.db.update_job_status(job_id, "validating", step_progress=0.60, params=params, note="Validating props and environment")
            validate_composition_name("ShortComposition")

            props_data = {
                "videoSrc": f"clip_{short_id}.mp4",
                "cuts": cuts,
                "sfxEvents": [],
                "hookTitle": params.get("hook_title", ""),
                "fps": 30,
                "theme": params.get("theme", "tiktok_viral"),
                "customFont": params.get("custom_font"),
                "bgm": params.get("bgm", "lofi"),
                "showProgressBar": True,
                "visualOverlays": params.get("story_overlays", [])
            }
            validate_props_file(props_data, allowed_roots=[Path(job.job_dir), Path(self.r_proc.public_dir)])

            # -------------------------------------------------------------
            # Stage 5 & 6: PREVIEW_RENDERING & AWAITING_APPROVAL
            # -------------------------------------------------------------
            _check_cancel()
            self.db.update_job_status(job_id, "awaiting_approval", step_progress=0.75, params=params, note="Awaiting user approval")

            if self.notifier:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                rev_id = job.revision_id
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 យល់ព្រម Render វីដេអូពេញលេញ (Approve)", callback_data=f"appr:{job_id}:{rev_id}")],
                    [
                        InlineKeyboardButton("✏️ កែ Subtitle", callback_data=f"rev_edit:{job_id}:{rev_id}"),
                        InlineKeyboardButton("🎨 ប្ដូរ Style", callback_data=f"rev_style:{job_id}:{rev_id}")
                    ],
                    [InlineKeyboardButton("🛑 បោះបង់ (Cancel)", callback_data=f"act_cancel:{job_id}")]
                ])

                preview_summary = (
                    f"📋 **[Job {short_id} - Rev {rev_id}] រៀបចំរួចរាល់សម្រាប់ពិនិត្យ (Review)៖**\n\n"
                    f"• ប្រភេទ (Mode)៖ `{job.mode}`\n"
                    f"• រយៈពេលសរុប៖ `{params.get('duration', 0.0):.1f}s`\n"
                    f"• ចំនួនឃ្លា Subtitles៖ `{len(words)} ឃ្លា`\n"
                    f"• ចំណងជើង Viral Hook៖ «{params.get('hook_title', '')}»\n"
                    f"• Font ខ្មែរ៖ `{params.get('custom_font') or 'Default'}`\n"
                    f"• ភ្លេងកំដរ BGM៖ `{params.get('bgm', 'lofi')}`\n\n"
                    "👉 សូមចុច **[ 🚀 យល់ព្រម Render វីដេអូពេញលេញ ]** ដើម្បី Render ឬចុចកែប្រែ Subtitle មុន Render!"
                )
                await self.notifier.notify_progress(job, preview_summary, reply_markup=kb)

        except JobCancelledError:
            logger.info(f"[Job {short_id}] Job was cancelled by user.")
            self.db.update_job_status(job_id, "cancelled", note="User cancelled")
            if self.notifier:
                await self.notifier.notify_progress(job, f"🛑 **[Job {short_id}] ការងារត្រូវបានបោះបង់ដោយជោគជ័យ។**")
        except Exception as e:
            logger.error(f"[Job {short_id}] Failure in pipeline: {e}", exc_info=True)
            self.db.update_job_status(
                job_id,
                "failed",
                error_reason=getattr(e, "error_code", "ERROR"),
                error_detail=traceback.format_exc(),
                note=str(e)
            )
            friendly = getattr(e, "user_friendly_message", None) or f"ជួបបញ្ហាពេលដំណើរការ៖ {str(e)[:150]}"
            if self.notifier:
                await self.notifier.notify_progress(
                    job,
                    f"❌ **[Job {short_id}] ជួបបញ្ហា៖**\n\n{friendly}\n\n💡 ប្រើពាក្យបញ្ជា `/new` ដើម្បីចាប់ផ្តើមឡើងវិញ។"
                )

    async def execute_final_render(self, job_id: str, revision_id: int):
        """
        Executes final Remotion render after user approval.
        Verifies revision_id, prevents duplicate execution, and executes bounded retries.
        """
        job = self.db.get_job(job_id)
        if not job:
            return

        short_id = job_id[:8]
        if job.status not in ("awaiting_approval", "awaiting_manual_agent"):
            logger.warning(f"[Job {short_id}] Final render called in invalid state: {job.status}")
            return

        if job.revision_id != revision_id:
            logger.warning(f"[Job {short_id}] Revision mismatch: requested {revision_id}, current {job.revision_id}")
            return

        cancel_event = threading.Event()
        self._active_cancel_events[job_id] = cancel_event

        params = job.params or {}
        output_path = job.output_path or str(Path(job.job_dir) / f"final_{short_id}.mp4")

        try:
            self.db.update_job_status(job_id, "final_rendering", step_progress=0.85, note="Starting Remotion render")
            if self.notifier:
                await self.notifier.notify_progress(
                    job,
                    f"⚡ **[Job {short_id}] ជំហានទី ៧ (Final Render)៖** កំពុង Render វីដេអូជាមួយ Remotion...\n"
                    "*(ពេលវេលា Render អាស្រ័យលើប្រវែងវីដេអូ និងល្បឿនម៉ាស៊ីន)*"
                )

            loop = asyncio.get_running_loop()

            def _pid_hook(pid):
                self._active_pids[job_id] = pid
                self.db.update_job_status(job_id, "final_rendering", active_pid=pid)

            # Bounded retry execution
            render_success = False
            last_err = None

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    if cancel_event.is_set():
                        raise JobCancelledError("Job was cancelled.", job_id=job_id)

                    logger.info(f"[Job {short_id}] Remotion render attempt {attempt}/{MAX_RETRIES}...")
                    await loop.run_in_executor(
                        None,
                        lambda: self.r_proc.process_video(
                            input_video_path=job.input_path,
                            output_video_path=output_path,
                            language=params.get("language"),
                            theme=params.get("theme", "tiktok_viral"),
                            bgm=params.get("bgm", "lofi"),
                            show_progress_bar=True,
                            words=params.get("words", []),
                            hook_title=params.get("hook_title", ""),
                            custom_font=params.get("custom_font"),
                            visual_overlays=params.get("story_overlays", []),
                            on_pid_assigned=_pid_hook,
                            cancel_event=cancel_event,
                            job_id=job_id
                        )
                    )
                    render_success = True
                    break
                except (JobCancelledError, ProcessTimeoutError):
                    raise
                except Exception as r_err:
                    last_err = r_err
                    logger.warning(f"[Job {short_id}] Render attempt {attempt} failed: {r_err}")
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(2.0)

            if not render_success:
                raise last_err or RuntimeError("Render failed after bounded retries.")

            # Stage: UPLOADING
            self.db.update_job_status(job_id, "uploading", step_progress=0.95, output_path=output_path)
            if self.notifier:
                await self.notifier.notify_progress(
                    job,
                    f"📤 **[Job {short_id}] ជំហានទី ៨ (Uploading)៖** កំពុងផ្ញើវីដេអូត្រឡប់ទៅកាន់លោកអ្នកវិញ..."
                )
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ កែប្រែអត្ថបទ Subtitle ឡើងវិញ", callback_data=f"rev_edit:{job_id}:{job.revision_id}")],
                    [InlineKeyboardButton("🧙‍♂️ បង្កើតវីដេអូថ្មី (New Wizard)", callback_data="wiz_start")]
                ])
                caption = (
                    f"🎬 **វីដេអូ Render រួចរាល់ហើយ!** ✨\n\n"
                    f"• **Job ID:** `{short_id}` (Rev {job.revision_id})\n"
                    f"• **Mode:** `{job.mode}`\n"
                    f"• **Theme:** `{params.get('theme', 'tiktok_viral')}`\n"
                    f"• **Font:** `{params.get('custom_font') or 'Default'}`\n"
                    f"• **BGM:** `{params.get('bgm', 'lofi')}`\n\n"
                    f"⚡ *ដំណើរការលឿនដោយ Local GPU/CPU & Remotion Engine*"
                )
                await self.notifier.send_video_result(job, output_path, caption=caption, reply_markup=kb)

            # Stage: COMPLETED
            self.db.update_job_status(job_id, "completed", step_progress=1.0, output_path=output_path)
            logger.info(f"[Job {short_id}] Processing pipeline fully COMPLETED!")

        except JobCancelledError:
            self.db.update_job_status(job_id, "cancelled", note="User cancelled render")
            if self.notifier:
                await self.notifier.notify_progress(job, f"🛑 **[Job {short_id}] ការងារត្រូវបានបោះបង់។**")
        except Exception as e:
            logger.error(f"[Job {short_id}] Final render failed: {e}", exc_info=True)
            self.db.update_job_status(
                job_id,
                "failed",
                error_reason=getattr(e, "error_code", "RENDER_FAILED"),
                error_detail=traceback.format_exc(),
                note=str(e)
            )
            if self.notifier:
                await self.notifier.notify_progress(
                    job,
                    f"❌ **[Job {short_id}] Render ជួបបញ្ហា៖** {str(e)[:150]}"
                )
        finally:
            self._active_cancel_events.pop(job_id, None)
            self._active_pids.pop(job_id, None)
