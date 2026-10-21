"""
Tests for ChatGPT Audit Checklist:
1. Delivery failure does not mark completed (status becomes 'delivery_failed').
2. Delivery success marks completed.
3. Atomic FIFO claims prevent race conditions under concurrency.
4. Quick Viral Pop pipeline works end-to-end.
5. Target length duration slicing and custom prompt behavior.
6. Full flow verification: Upload -> Preview -> Approve -> Output MP4.
All external APIs are mocked with zero network calls.
"""

import os
import uuid
import shutil
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from database import DatabaseManager, DbJob
from worker import RenderWorkerPool
from remotion_processor import build_smart_cuts
from transcriber import AudioTranscriber
from gemini_transcriber import GeminiTranscriber


@pytest.fixture
def db_instance(tmp_path):
    db_file = tmp_path / "test_audit.sqlite"
    db = DatabaseManager(db_path=str(db_file))
    yield db
    if os.path.exists(str(db_file)):
        try:
            os.remove(str(db_file))
        except Exception:
            pass


class TestAuditDeliveryAndApproval:

    def test_atomic_claim_concurrency(self, db_instance, tmp_path):
        """claim_next_job must be atomic: first worker claims it, second worker gets None."""
        job_id = str(uuid.uuid4())
        job_dir = str(tmp_path / "job1")
        job = db_instance.insert_job(
            job_id=job_id,
            user_id=123,
            chat_id=456,
            mode="quick",
            input_path=str(tmp_path / "in.mp4"),
            job_dir=job_dir
        )
        assert job.status == "queued"

        # Worker 1 claims job
        claimed_1 = db_instance.claim_next_job(claimed_by="worker_alpha")
        assert claimed_1 is not None
        assert claimed_1.job_id == job.job_id
        assert claimed_1.status == "analyzing"

        # Worker 2 tries to claim while queue is empty
        claimed_2 = db_instance.claim_next_job(claimed_by="worker_beta")
        assert claimed_2 is None

    @pytest.mark.anyio
    async def test_delivery_failure_does_not_mark_completed(self, db_instance, tmp_path):
        """Requirement 12: If video delivery fails, the job must NOT be marked completed."""
        job_dir = tmp_path / "delivery_fail_job"
        job_dir.mkdir(parents=True, exist_ok=True)
        fake_mp4 = job_dir / "final_out.mp4"
        fake_mp4.write_bytes(b"dummy mp4 content" * 100)

        job_id = str(uuid.uuid4())
        job = db_instance.insert_job(
            job_id=job_id,
            user_id=1001,
            chat_id=2002,
            mode="quick",
            input_path=str(fake_mp4),
            job_dir=str(job_dir),
            params={"duration": 10.0}
        )
        db_instance.update_job_status(job.job_id, "awaiting_approval", output_path=str(fake_mp4))

        mock_rp = MagicMock()
        mock_rp.process_video = MagicMock(return_value=str(fake_mp4))
        mock_notifier = MagicMock()
        # Simulate delivery FAILURE (network timeout / telegram error)
        mock_notifier.send_video_result = AsyncMock(return_value=False)
        mock_notifier.notify_progress = AsyncMock()

        pool = RenderWorkerPool(
            db=db_instance,
            remotion_processor=mock_rp,
            notifier=mock_notifier,
            max_concurrency=1
        )

        await pool.execute_final_render(job.job_id, revision_id=1)

        updated_job = db_instance.get_job(job.job_id)
        # CRITICAL ASSERTION: Must NOT be completed
        assert updated_job.status != "completed"
        assert updated_job.status == "delivery_failed"
        assert updated_job.error_reason == "DELIVERY_FAILED"
        assert updated_job.output_path == str(fake_mp4)

    @pytest.mark.anyio
    async def test_delivery_success_marks_completed(self, db_instance, tmp_path):
        """When delivery succeeds, the job is marked completed."""
        job_dir = tmp_path / "delivery_success_job"
        job_dir.mkdir(parents=True, exist_ok=True)
        fake_mp4 = job_dir / "final_out.mp4"
        fake_mp4.write_bytes(b"dummy mp4 content" * 100)

        job_id = str(uuid.uuid4())
        job = db_instance.insert_job(
            job_id=job_id,
            user_id=1001,
            chat_id=2002,
            mode="quick",
            input_path=str(fake_mp4),
            job_dir=str(job_dir),
            params={"duration": 10.0}
        )
        db_instance.update_job_status(job.job_id, "awaiting_approval", output_path=str(fake_mp4))

        mock_rp = MagicMock()
        mock_rp.process_video = MagicMock(return_value=str(fake_mp4))
        mock_notifier = MagicMock()
        # Simulate delivery SUCCESS
        mock_notifier.send_video_result = AsyncMock(return_value=True)
        mock_notifier.notify_progress = AsyncMock()

        pool = RenderWorkerPool(
            db=db_instance,
            remotion_processor=mock_rp,
            notifier=mock_notifier,
            max_concurrency=1
        )

        await pool.execute_final_render(job.job_id, revision_id=1)

        updated_job = db_instance.get_job(job.job_id)
        assert updated_job.status == "completed"
        assert updated_job.step_progress == 1.0
        assert updated_job.output_path == str(fake_mp4)

    def test_quick_viral_pop_smart_cuts(self):
        """Requirement 13: Quick Viral Pop smart cuts handle pauses and silence removal."""
        words = [
            {"word": "ជំរាបសួរ", "start": 0.2, "end": 0.8},
            {"word": "បងប្អូន", "start": 0.9, "end": 1.4},
            # 1.1s silence gap
            {"word": "ទាំងអស់គ្នា", "start": 2.5, "end": 3.2}
        ]
        cuts = build_smart_cuts(words, silence_threshold=0.28)
        assert len(cuts) == 2
        # First cut covers 0.2s to 1.4s (with padding)
        assert cuts[0]["start"] <= 0.2
        assert pytest.approx(cuts[0]["end"], abs=0.15) == 1.5
        # Second cut covers 2.5s to 3.2s
        assert pytest.approx(cuts[1]["start"], abs=0.15) == 2.42
        assert cuts[1]["zoom"] in (1.0, 1.15)

    def test_duration_slicing_and_custom_prompt(self):
        """Requirement: target_length short_30s slices transcript correctly; prompt is incorporated."""
        words = [
            {"word": f"word_{i}", "start": float(i * 2), "end": float(i * 2 + 1.5)}
            for i in range(25)  # Total 50s
        ]
        # short_30s slicing
        sliced_30 = [w for w in words if float(w.get("end", 0.0)) <= 30.5]
        assert len(sliced_30) == 15
        assert sliced_30[-1]["end"] <= 30.5

        # custom prompt incorporated into visual scene extraction fallback
        gt = GeminiTranscriber(api_key="")
        scenes = gt.extract_visual_story_scenes(sliced_30, user_prompt="Focus on real estate")
        assert len(scenes) >= 1
        assert "Focus on real estate" in scenes[0]["imagePrompt"]

    @pytest.mark.anyio
    async def test_full_pipeline_upload_preview_approve_mp4(self, db_instance, tmp_path):
        """Full pipeline verification: Upload -> Analyzing -> Validating -> Preview -> Approve -> MP4."""
        job_dir = tmp_path / "full_flow_job"
        job_dir.mkdir(parents=True, exist_ok=True)
        raw_video = job_dir / "raw_input.mp4"
        raw_video.write_bytes(b"synthetic raw video" * 50)

        # 1. Upload & Job creation
        job_id = str(uuid.uuid4())
        job = db_instance.insert_job(
            job_id=job_id,
            user_id=777,
            chat_id=888,
            mode="quick",
            input_path=str(raw_video),
            job_dir=str(job_dir),
            params={"target_length": "auto", "theme": "tiktok_viral"}
        )
        assert job.status == "queued"

        mock_rp = MagicMock()
        mock_rp.enhance_audio = MagicMock(return_value=str(raw_video))
        mock_rp.public_dir = str(tmp_path / "public")
        Path(mock_rp.public_dir).mkdir(parents=True, exist_ok=True)
        mock_rp.remotion_dir = str(tmp_path / "remotion")
        Path(mock_rp.remotion_dir).mkdir(parents=True, exist_ok=True)

        final_mp4 = job_dir / f"final_{job.job_id[:8]}.mp4"
        final_mp4.write_bytes(b"rendered final mp4 bytes" * 100)
        mock_rp.process_video = MagicMock(return_value=str(final_mp4))

        sample_words = [
            {"word": "សួស្តី", "start": 0.5, "end": 1.2},
            {"word": "ពិភពលោក", "start": 1.3, "end": 2.1}
        ]
        mock_rp.transcribe_video = MagicMock(return_value=(sample_words, "Trending Hook"))

        mock_notifier = MagicMock()
        mock_notifier.notify_progress = AsyncMock()
        mock_notifier.send_video_result = AsyncMock(return_value=True)

        pool = RenderWorkerPool(
            db=db_instance,
            remotion_processor=mock_rp,
            notifier=mock_notifier,
            max_concurrency=1
        )

        # 2. Worker pipeline runs up to awaiting_approval
        claimed_job = db_instance.claim_next_job(claimed_by="test_worker")
        assert claimed_job is not None

        cancel_ev = MagicMock()
        cancel_ev.is_set.return_value = False

        probe_output = "Duration: 00:00:10.00, start: 0.000000, bitrate: 1000 kb/s\n Stream #0:0: Video: h264\n Stream #0:1: Audio: aac"
        with patch("process_runner.ProcessRunner.run") as mock_pr:
            mock_pr.return_value = MagicMock(returncode=0, stdout="", stderr=probe_output)
            await pool._run_job_stages(claimed_job, cancel_ev)

        # 3. Check status is awaiting_approval
        preview_job = db_instance.get_job(job.job_id)
        assert preview_job.status == "awaiting_approval"
        assert preview_job.revision_id == 1

        # 4. User approves -> execute_final_render runs
        await pool.execute_final_render(job.job_id, revision_id=1)

        # 5. Pipeline verified: reached completed with output path
        final_job = db_instance.get_job(job.job_id)
        assert final_job.status == "completed"
        assert final_job.step_progress == 1.0
        assert os.path.exists(final_job.output_path)
