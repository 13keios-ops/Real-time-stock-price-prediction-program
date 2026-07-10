"""LightGBM artifact loader and predictor."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import uuid

import joblib
import numpy as np

from app.storage.contracts import FeatureSnapshot, Prediction


DEFAULT_LABELS = ("down", "flat", "up")


@dataclass(slots=True)
class LightGbmArtifact:
    model_version: str
    feature_set_version: str
    horizon_min: int
    feature_names: list[str]
    class_labels: list[str]
    training_run_id: str | None = None
    artifact_id: str | None = None
    artifact_sha256: str | None = None
    trained_at: str | None = None
    dataset_scope: str | None = None
    challenger_holdout_first_event_time: str | None = None


class LightGbmDirectionModel:
    def __init__(self, model, artifact: LightGbmArtifact) -> None:
        self.model = model
        self.artifact = artifact

    @classmethod
    def from_path(cls, artifact_path: Path) -> "LightGbmDirectionModel":
        artifact_sha256 = file_sha256(artifact_path)
        payload = joblib.load(artifact_path)
        artifact_payload = payload["artifact"]
        artifact = LightGbmArtifact(
            model_version=str(artifact_payload["model_version"]),
            feature_set_version=str(artifact_payload["feature_set_version"]),
            horizon_min=int(artifact_payload["horizon_min"]),
            feature_names=list(artifact_payload["feature_names"]),
            class_labels=[str(label) for label in artifact_payload["class_labels"]],
            training_run_id=artifact_payload.get("training_run_id"),
            artifact_id=artifact_payload.get("artifact_id") or artifact_payload.get("training_run_id"),
            artifact_sha256=artifact_sha256,
            trained_at=artifact_payload.get("trained_at"),
            dataset_scope=artifact_payload.get("dataset_scope"),
            challenger_holdout_first_event_time=artifact_payload.get("challenger_holdout_first_event_time"),
        )
        return cls(model=payload["model"], artifact=artifact)

    def save(self, artifact_path: Path) -> Path:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "artifact": {
                "model_version": self.artifact.model_version,
                "feature_set_version": self.artifact.feature_set_version,
                "horizon_min": self.artifact.horizon_min,
                "feature_names": self.artifact.feature_names,
                "class_labels": self.artifact.class_labels,
                "training_run_id": self.artifact.training_run_id,
                "artifact_id": self.artifact.artifact_id,
                "trained_at": self.artifact.trained_at,
                "dataset_scope": self.artifact.dataset_scope,
                "challenger_holdout_first_event_time": self.artifact.challenger_holdout_first_event_time,
            },
            "model": self.model,
        }
        temporary_path = artifact_path.with_name(f".{artifact_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            joblib.dump(payload, temporary_path)
            os.replace(temporary_path, artifact_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        self.artifact.artifact_sha256 = file_sha256(artifact_path)
        return artifact_path

    def predict(self, feature_snapshot: FeatureSnapshot, horizon_min: int, prediction_id: str) -> Prediction:
        vector = np.asarray(
            [[float(feature_snapshot.values.get(name, 0.0)) for name in self.artifact.feature_names]],
            dtype=float,
        )
        booster = getattr(self.model, "booster_", None)
        if booster is not None:
            probabilities = booster.predict(vector)
        else:
            probabilities = self.model.predict_proba(vector)
        row_probabilities = probabilities[0]
        label_to_probability = {label: 0.0 for label in DEFAULT_LABELS}
        for index, label in enumerate(self.artifact.class_labels):
            label_to_probability[str(label)] = float(row_probabilities[index])
        return Prediction(
            prediction_id=prediction_id,
            symbol=feature_snapshot.symbol,
            event_time=feature_snapshot.event_time,
            horizon_min=horizon_min,
            model_version=self.artifact.model_version,
            probability_up=label_to_probability["up"],
            probability_flat=label_to_probability["flat"],
            probability_down=label_to_probability["down"],
            training_run_id=self.artifact.training_run_id,
            artifact_id=self.artifact.artifact_id,
            artifact_sha256=self.artifact.artifact_sha256,
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_lightgbm_artifacts(runtime_root: Path, horizon_min: int) -> list[Path]:
    model_dir = runtime_root / "ml" / "models"
    if not model_dir.exists():
        return []
    candidates = list(model_dir.glob(f"lightgbm-h{horizon_min}-*.joblib"))
    candidates.extend((model_dir / "lightgbm" / f"h{horizon_min}").glob("*.joblib"))
    exact = model_dir / f"lightgbm-h{horizon_min}-v1.joblib"
    if exact.exists() and exact not in candidates:
        candidates.append(exact)
    return sorted(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)


def find_latest_lightgbm_artifact(runtime_root: Path, horizon_min: int) -> Path | None:
    candidates = find_lightgbm_artifacts(runtime_root, horizon_min)
    return candidates[0] if candidates else None
