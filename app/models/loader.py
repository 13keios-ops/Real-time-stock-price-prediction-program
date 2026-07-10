"""Model loading helpers for runtime prediction."""

from __future__ import annotations

from pathlib import Path

from app.config.settings import AppSettings
from app.models.baseline import BaselineDirectionModel
from app.models.centroid import CentroidDirectionModel
from app.models.lightgbm_model import DEFAULT_LABELS, LightGbmDirectionModel, find_lightgbm_artifacts
from app.models.linear_score import LinearScoreConfig, LinearScoreDirectionModel
from app.models.registry import ModelRegistry


def _default_linear_score_model(settings: AppSettings, horizon_min: int) -> LinearScoreDirectionModel:
    version = f"linear-score-h{horizon_min}-v1"
    if horizon_min >= 60:
        weights = {
            "return_1m_pct": 0.55,
            "bid_ask_imbalance": 1.1,
            "spread_bps": -0.08,
            "hl_range_pct": -0.3,
        }
    else:
        weights = {
            "return_1m_pct": 0.75,
            "bid_ask_imbalance": 1.45,
            "spread_bps": -0.1,
            "hl_range_pct": -0.35,
        }
    return LinearScoreDirectionModel(
        LinearScoreConfig(
            model_version=version,
            feature_set_version=settings.feature_set_version,
            horizon_min=horizon_min,
            weights=weights,
            bias=0.0,
        )
    )


def load_named_builtin_model(settings: AppSettings, horizon_min: int, builtin_name: str, metadata: dict[str, object] | None = None):
    if builtin_name == "baseline":
        return BaselineDirectionModel(
            model_version_h15=settings.model_version_h15,
            model_version_h60=settings.model_version_h60,
        )
    if builtin_name == "linear_score":
        return _default_linear_score_model(settings, horizon_min=horizon_min)
    raise ValueError(f"Unsupported builtin model name: {builtin_name}")


def load_prediction_model(settings: AppSettings, horizon_min: int = 15):
    registry = ModelRegistry(settings.runtime_data_dir)
    active_entry = registry.get_active_model_entry(horizon_min=horizon_min)
    if active_entry is not None:
        if active_entry.model_kind == "builtin" and active_entry.builtin_name:
            return load_named_builtin_model(
                settings,
                horizon_min=horizon_min,
                builtin_name=active_entry.builtin_name,
                metadata=active_entry.metadata,
            )
        if active_entry.model_kind == "lightgbm_artifact" and active_entry.artifact_path:
            model = LightGbmDirectionModel.from_path(Path(active_entry.artifact_path))
            artifact = model.artifact
            if artifact.model_version != active_entry.model_version:
                raise ValueError("Active LightGBM registry model_version does not match its artifact.")
            if artifact.feature_set_version != active_entry.feature_set_version:
                raise ValueError("Active LightGBM registry feature_set_version does not match its artifact.")
            if artifact.horizon_min != horizon_min:
                raise ValueError("Active LightGBM registry horizon does not match its artifact.")
            metadata = active_entry.metadata or {}
            expected_sha256 = metadata.get("artifact_sha256")
            if not expected_sha256 or artifact.artifact_sha256 != str(expected_sha256):
                raise ValueError("Active LightGBM artifact hash is missing or does not match the registry.")
            expected_artifact_id = metadata.get("artifact_id")
            if expected_artifact_id and artifact.artifact_id != str(expected_artifact_id):
                raise ValueError("Active LightGBM artifact_id does not match the registry.")
            expected_training_run_id = metadata.get("training_run_id")
            if expected_training_run_id and artifact.training_run_id != str(expected_training_run_id):
                raise ValueError("Active LightGBM training_run_id does not match the registry.")
            return model
        if active_entry.artifact_path:
            return CentroidDirectionModel.from_path(Path(active_entry.artifact_path))
    return load_named_builtin_model(settings, horizon_min=horizon_min, builtin_name="baseline")


def load_latest_lightgbm_shadow_model(settings: AppSettings, horizon_min: int = 15):
    # Select the newest valid artifact, skipping corrupt or incompatible files.
    for artifact_path in find_lightgbm_artifacts(settings.runtime_data_dir, horizon_min=horizon_min):
        try:
            model = LightGbmDirectionModel.from_path(Path(artifact_path))
        except (OSError, KeyError, TypeError, ValueError, EOFError):
            continue
        artifact = getattr(model, "artifact", None)
        if artifact is None:
            return model
        if int(artifact.horizon_min) != horizon_min:
            continue
        if str(artifact.feature_set_version) != str(settings.feature_set_version):
            continue
        if tuple(str(label) for label in artifact.class_labels) != tuple(DEFAULT_LABELS):
            continue
        return model
    return None
