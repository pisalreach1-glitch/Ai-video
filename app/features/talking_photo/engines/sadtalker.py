"""SadTalker adapter conforming to AvatarBackend protocol."""
from pathlib import Path
from typing import Callable
from app.features.talking_photo.domain import AvatarRequest, AvatarResult, TalkingPhotoSettings
from app.features.talking_photo.engine import sadtalker_engine
from app.features.talking_photo.media import measure_audio_duration

class SadTalkerAvatarBackend:
    @property
    def backend_id(self) -> str:
        return "sadtalker"

    async def is_available(self) -> bool:
        return sadtalker_engine.is_available()

    async def render(
        self,
        request: AvatarRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
        on_pid: Callable[[int], None] | None = None,
    ) -> AvatarResult:
        out_dir = Path(request.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        settings = TalkingPhotoSettings(
            face_size=256,
            batch_size=1,
            still_mode=False,
            expression_scale=1.0,
            pose_style=0,
        )

        preview_mode = bool(request.preview_seconds and request.preview_seconds > 0)
        raw_video = await sadtalker_engine.run_animation(
            image_path=Path(request.source_image),
            audio_path=Path(request.approved_master_wav),
            output_dir=out_dir,
            settings=settings,
            preview_mode=preview_mode,
            on_pid=on_pid,
            cancel_check=cancel_check,
        )

        manifest_path = out_dir / "avatar_manifest.json"
        manifest_path.write_text(f'{{"backend": "sadtalker", "video": "{raw_video.name}"}}', encoding="utf-8")

        dur = await measure_audio_duration(Path(request.approved_master_wav))
        if preview_mode and request.preview_seconds:
            dur = min(dur, request.preview_seconds)

        return AvatarResult(
            video_path=str(raw_video),
            manifest_path=str(manifest_path),
            duration_seconds=dur,
            backend_revision="sadtalker-1.0",
        )

sadtalker_avatar_backend = SadTalkerAvatarBackend()
