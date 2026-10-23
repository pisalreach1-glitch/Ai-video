"""Unit tests for Avatar backend protocol and adapters."""
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from app.features.talking_photo.domain import AvatarRequest, AvatarResult
from app.features.talking_photo.engines.sadtalker import sadtalker_avatar_backend
from app.features.talking_photo.engines.wan2gp import wan2gp_avatar_backend

@pytest.mark.asyncio
async def test_sadtalker_backend_contract(tmp_path):
    img = tmp_path / "portrait.png"
    img.touch()
    wav = tmp_path / "speech.wav"
    wav.touch()
    out_dir = tmp_path / "out"

    req = AvatarRequest(
        task_id="task_st_01",
        snapshot_digest="snap_01",
        source_image=str(img),
        approved_master_wav=str(wav),
        audio_sha256="sha_speech",
        output_dir=str(out_dir),
        preview_seconds=5.0,
    )

    with patch("app.features.talking_photo.engines.sadtalker.sadtalker_engine.run_animation", new=AsyncMock(return_value=out_dir / "preview_raw.mp4")), \
         patch("app.features.talking_photo.engines.sadtalker.measure_audio_duration", new=AsyncMock(return_value=12.0)):
        res = await sadtalker_avatar_backend.render(req)

    assert isinstance(res, AvatarResult)
    assert res.backend_revision == "sadtalker-1.0"
    assert res.duration_seconds == 5.0
    assert (out_dir / "avatar_manifest.json").exists()

@pytest.mark.asyncio
async def test_wan2gp_unconfigured_raises_useful_error(tmp_path):
    req = AvatarRequest(
        task_id="task_w2_01",
        snapshot_digest="snap_02",
        source_image=str(tmp_path / "portrait.png"),
        approved_master_wav=str(tmp_path / "speech.wav"),
        audio_sha256="sha_speech",
        output_dir=str(tmp_path / "out"),
    )

    with patch.dict("os.environ", {"AVATAR_ENGINE_DIR": ""}):
        with pytest.raises(RuntimeError, match="Wan2GP / HunyuanVideo-Avatar backend is not configured"):
            await wan2gp_avatar_backend.render(req)
