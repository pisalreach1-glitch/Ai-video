"""Explicit feature-to-pipeline registry."""
from typing import Dict
from app.domain.features import JobFeature, FeaturePipeline
from app.features.video_voiceover.adapter import video_voiceover_pipeline
from app.features.talking_photo.pipeline import talking_photo_pipeline

class FeatureRegistry:
    def __init__(self):
        self._registry: Dict[str, FeaturePipeline] = {}
        # Register standard pipelines
        self.register(JobFeature.VIDEO_VOICEOVER, video_voiceover_pipeline)
        self.register(JobFeature.TALKING_PHOTO, talking_photo_pipeline)

    def register(self, feature: JobFeature | str, pipeline: FeaturePipeline) -> None:
        key = feature.value if isinstance(feature, JobFeature) else str(feature)
        self._registry[key] = pipeline

    def get(self, feature: JobFeature | str) -> FeaturePipeline:
        key = feature.value if isinstance(feature, JobFeature) else str(feature)
        if key not in self._registry:
            raise KeyError(f"Unknown feature '{key}'. Registered features: {list(self._registry.keys())}")
        return self._registry[key]

feature_registry = FeatureRegistry()
