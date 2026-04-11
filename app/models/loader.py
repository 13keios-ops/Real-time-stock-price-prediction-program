"""Model loading helpers for runtime prediction."""

from __future__ import annotations

from app.config.settings import AppSettings
from app.models.baseline import BaselineDirectionModel
from app.models.centroid import CentroidDirectionModel, find_latest_centroid_artifact
from app.models.registry import ModelRegistry


def load_prediction_model(settings: AppSettings, horizon_min: int = 15):
    registry = ModelRegistry(settings.runtime_data_dir)
    artifact_path = registry.get_active_model_path(horizon_min=horizon_min)
    if artifact_path is None:
        artifact_path = find_latest_centroid_artifact(settings.runtime_data_dir, horizon_min=horizon_min)
    if artifact_path is not None:
        return CentroidDirectionModel.from_path(artifact_path)
    return BaselineDirectionModel(
        model_version_h15=settings.model_version_h15,
        model_version_h60=settings.model_version_h60,
    )
