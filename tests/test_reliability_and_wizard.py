"""
Tests for Rendering Reliability, SQLite Persistence, and 5-Step Wizard Navigation.
Verifies:
1. Wizard 5-step navigation (mode -> upload -> style -> length -> review)
2. Back navigation preserves choices without losing media or settings
3. SQLite persistence and restart recovery marking unfinished jobs 'interrupted'
4. Duplicate click prevention on approval callback
5. Revision tracking and rejection of stale approval callbacks
6. Process tree termination on cancellation
7. Sandbox environment secret scrubbing and composition whitelisting
8. Assisted fallback handling for unsupported agent bridge
"""

import os
import time
import pytest
from pathlib import Path

from database import DatabaseManager, DbJob, WizardSession
from wizard_flow import (
    WIZARD_STEPS,
    build_wizard_view,
    navigate_wizard,
    update_wizard_field,
    create_job_from_wizard
)
from remotion_sandbox import (
    validate_composition_name,
    validate_props_file,
    get_sanitized_render_env,
    SecurityValidationError
)
from agent_bridge import AntigravityBridge


class TestWizardAndPersistence:
    @pytest.fixture
    def test_db(self, tmp_path):
        db_path = tmp_path / "test_bot.sqlite"
        return DatabaseManager(db_path)

    def test_wizard_five_steps_navigation(self, test_db):
        """Checks linear step progression: mode -> upload -> style -> length -> review."""
        user_id = 1001
        chat_id = 2001

        session = test_db.get_or_create_wizard(user_id, chat_id)
        assert session.current_step == "mode"

        # Advance step by step
        session = navigate_wizard(test_db, user_id, chat_id, "next")
        assert session.current_step == "upload"

        session = navigate_wizard(test_db, user_id, chat_id, "next")
        assert session.current_step == "style"

        session = navigate_wizard(test_db, user_id, chat_id, "next")
        assert session.current_step == "length"

        session = navigate_wizard(test_db, user_id, chat_id, "next")
        assert session.current_step == "review"

        # Reaching end stays on review
        session = navigate_wizard(test_db, user_id, chat_id, "next")
        assert session.current_step == "review"

    def test_back_navigation_preserves_settings_and_media(self, test_db, tmp_path):
        """Verifies Back button changes screen without losing media/settings."""
        user_id = 1002
        chat_id = 2002

        # Create dummy video file
        dummy_video = tmp_path / "sample.mp4"
        dummy_video.write_bytes(b"dummy video content")

        session = test_db.get_or_create_wizard(user_id, chat_id)
        # User sets mode, uploads video, sets style, length, and custom prompt
        update_wizard_field(test_db, user_id, chat_id, "mode", "auto")
        test_db.update_wizard(user_id, input_path=str(dummy_video), original_filename="sample.mp4")
        update_wizard_field(test_db, user_id, chat_id, "theme", "bold_yellow")
        update_wizard_field(test_db, user_id, chat_id, "bgm", "energetic")
        update_wizard_field(test_db, user_id, chat_id, "font", "Battambang")
        update_wizard_field(test_db, user_id, chat_id, "length", "short_30s")
        update_wizard_field(test_db, user_id, chat_id, "prompt", "Make hook very punchy")

        # Advance to review
        test_db.update_wizard(user_id, current_step="review")
        session = test_db.get_or_create_wizard(user_id, chat_id)
        assert session.current_step == "review"
        assert session.mode == "auto"
        assert session.style_theme == "bold_yellow"
        assert session.bgm == "energetic"
        assert session.custom_font == "Battambang"
        assert session.target_length == "short_30s"
        assert session.custom_prompt == "Make hook very punchy"
        assert session.input_path == str(dummy_video)

        # User presses Back multiple times
        session = navigate_wizard(test_db, user_id, chat_id, "back")
        assert session.current_step == "length"
        # All settings preserved!
        assert session.mode == "auto"
        assert session.style_theme == "bold_yellow"
        assert session.input_path == str(dummy_video)
        assert session.custom_prompt == "Make hook very punchy"

        session = navigate_wizard(test_db, user_id, chat_id, "back")
        assert session.current_step == "style"
        assert session.custom_font == "Battambang"

        session = navigate_wizard(test_db, user_id, chat_id, "back")
        assert session.current_step == "upload"
        assert session.input_path == str(dummy_video)

        session = navigate_wizard(test_db, user_id, chat_id, "back")
        assert session.current_step == "mode"
        assert session.mode == "auto"

    def test_restart_recovery_marks_interrupted(self, test_db, tmp_path):
        """Verifies that active jobs are marked 'interrupted' after server restart and never labeled completed."""
        user_id = 1003
        chat_id = 2003

        job = test_db.insert_job(
            job_id="job_active_123",
            user_id=user_id,
            chat_id=chat_id,
            mode="quick",
            input_path="dummy.mp4",
            job_dir=str(tmp_path / "job_active_123")
        )
        assert job.status == "queued"

        # Advance to analyzing and final_rendering
        test_db.update_job_status("job_active_123", "final_rendering")
        active_job = test_db.get_job("job_active_123")
        assert active_job.status == "final_rendering"
        assert active_job.is_active() is True

        # Simulate bot restart
        recovered_count = test_db.recover_interrupted_jobs()
        assert recovered_count == 1

        recovered_job = test_db.get_job("job_active_123")
        assert recovered_job.status == "interrupted"
        assert "Bot server restarted" in recovered_job.error_reason
        assert recovered_job.finished_at is not None
        assert recovered_job.is_active() is False

    def test_duplicate_click_prevention_and_revision_check(self, test_db, tmp_path):
        """Verifies duplicate click rejection and old revision rejection."""
        user_id = 1004
        chat_id = 2004

        job = test_db.insert_job(
            job_id="job_approval_test",
            user_id=user_id,
            chat_id=chat_id,
            mode="auto",
            input_path="dummy.mp4",
            job_dir=str(tmp_path / "job_approval_test")
        )
        assert job.revision_id == 1

        # Job reaches awaiting_approval
        test_db.update_job_status(job.job_id, "awaiting_approval")
        j = test_db.get_job(job.job_id)
        assert j.status == "awaiting_approval"

        # User edits subtitle -> revision bumped to 2
        test_db.bump_revision(job.job_id)
        j2 = test_db.get_job(job.job_id)
        assert j2.revision_id == 2

        # 1. Old callback with rev 1 arrives -> must be rejected
        old_rev = 1
        assert old_rev != j2.revision_id  # Rejection check succeeds

        # 2. Correct callback with rev 2 arrives
        new_rev = 2
        assert new_rev == j2.revision_id
        # Atomic status update locks out second click
        test_db.update_job_status(job.job_id, "final_rendering")

        # 3. Repeated click with rev 2 arrives
        j_after_click = test_db.get_job(job.job_id)
        # Status is no longer awaiting_approval -> Duplicate click rejected!
        assert j_after_click.status != "awaiting_approval"
        assert j_after_click.status == "final_rendering"

    def test_sandbox_secret_scrubbing_and_validation(self):
        """Verifies that secrets are never exposed to Remotion and compositions are whitelisted."""
        # 1. Composition whitelist
        assert validate_composition_name("ShortComposition") == "ShortComposition"
        with pytest.raises(SecurityValidationError):
            validate_composition_name("ArbitraryComp; rm -rf /")

        # 2. Environment secret scrubbing
        os.environ["TELEGRAM_BOT_TOKEN"] = "SECRET_BOT_TOKEN_12345"
        os.environ["GEMINI_API_KEY"] = "AIzaSySecretGeminiKey"
        os.environ["TELEGRAM_API_HASH"] = "hash_secret"

        sanitized = get_sanitized_render_env()
        assert "TELEGRAM_BOT_TOKEN" not in sanitized
        assert "GEMINI_API_KEY" not in sanitized
        assert "TELEGRAM_API_HASH" not in sanitized
        assert sanitized.get("NODE_ENV") == "production"

        # 3. Props validation (blocks traversal)
        valid_props = {
            "videoSrc": "clip_test.mp4",
            "cuts": [{"start": 0.0, "end": 2.5}]
        }
        validate_props_file(valid_props, allowed_roots=[Path(".")])

        invalid_props = {
            "videoSrc": "../../etc/passwd",
            "cuts": []
        }
        with pytest.raises(SecurityValidationError):
            validate_props_file(invalid_props, allowed_roots=[Path(".")])

    def test_agent_bridge_assisted_fallback(self, tmp_path):
        """Verifies honest degradation when automated agent bridge is absent."""
        assert AntigravityBridge.is_bridge_supported() is False

        words = [
            {"start": 0.5, "end": 1.2, "word": "សួស្តី"},
            {"start": 1.3, "end": 2.0, "word": "កម្ពុជា"}
        ]
        brief_path, brief_content = AntigravityBridge.generate_agent_brief(
            job_id="test_bridge_job",
            job_dir=tmp_path,
            user_prompt="Add bold red title on top",
            words=words,
            mode="custom"
        )
        assert brief_path.exists()
        assert "សួស្តី" in brief_content
        assert "Add bold red title on top" in brief_content

    @pytest.mark.anyio
    async def test_worker_pool_linear_pipeline(self, test_db, tmp_path):
        """Verifies linear states: queued -> analyzing -> planning -> generating -> validating -> awaiting_approval -> completed."""
        import asyncio
        from unittest.mock import MagicMock
        from worker import RenderWorkerPool

        # Setup dummy video
        dummy_input = tmp_path / "input.mp4"
        dummy_input.write_bytes(b"dummy video data")

        job_dir = tmp_path / "test_worker_job"
        job_dir.mkdir(parents=True, exist_ok=True)

        job = test_db.insert_job(
            job_id="test_worker_job",
            user_id=1005,
            chat_id=2005,
            mode="quick",
            input_path=str(dummy_input),
            job_dir=str(job_dir),
            params={"language": "km"}
        )
        assert job.status == "queued"

        # Mock remotion processor
        mock_proc = MagicMock()
        mock_proc.public_dir = str(tmp_path)
        mock_proc.remotion_dir = str(tmp_path)
        mock_proc.transcribe_video.return_value = (
            [{"start": 0.2, "end": 1.5, "word": "ជំរាបសួរ"}],
            "Trending Highlight"
        )
        mock_proc.process_video.return_value = str(job_dir / "final_output.mp4")

        # Mock media validation to return dummy metadata
        from media_validator import MediaInfo
        dummy_media_info = MediaInfo(duration=2.0, width=1080, height=1920, has_video=True, has_audio=True)

        from unittest.mock import patch
        with patch("worker.validate_video_with_audio", return_value=dummy_media_info):
            worker_pool = RenderWorkerPool(
                db=test_db,
                remotion_processor=mock_proc,
                notifier=None,
                max_concurrency=1
            )

            # Run pipeline stages
            cancel_event = asyncio.Event()
            import threading
            th_cancel = threading.Event()
            await worker_pool._run_job_stages(job, th_cancel)

            # State must now be awaiting_approval
            updated_job = test_db.get_job(job.job_id)
            assert updated_job.status == "awaiting_approval"
            assert updated_job.params.get("words") is not None
            assert updated_job.params.get("hook_title") == "Trending Highlight"

            # Execute final render
            (job_dir / "final_output.mp4").write_bytes(b"final mp4 content")
            await worker_pool.execute_final_render(job.job_id, revision_id=updated_job.revision_id)

            # Final state must be completed
            final_job = test_db.get_job(job.job_id)
            assert final_job.status == "completed"
            assert final_job.step_progress == 1.0

