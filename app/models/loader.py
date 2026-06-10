"""Model loading helpers for runtime prediction."""

from __future__ import annotations

from pathlib import Path

from app.config.settings import AppSettings
from app.models.baseline import BaselineDirectionModel
from app.models.centroid import CentroidDirectionModel
from app.models.lightgbm_model import LightGbmDirectionModel, find_latest_lightgbm_artifact
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
            return LightGbmDirectionModel.from_path(Path(active_entry.artifact_path))
        if active_entry.artifact_path:
            return CentroidDirectionModel.from_path(Path(active_entry.artifact_path))
    return load_named_builtin_model(settings, horizon_min=horizon_min, builtin_name="baseline")


def load_latest_lightgbm_shadow_model(settings: AppSettings, horizon_min: int = 15):
    artifact_path = find_latest_lightgbm_artifact(settings.runtime_data_dir, horizon_min=horizon_min)
    if artifact_path is None:
        return None
    return LightGbmDirectionModel.from_path(Path(artifact_path))
