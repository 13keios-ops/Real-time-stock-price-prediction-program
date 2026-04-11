"""Centroid-based model artifact loader and predictor."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from app.storage.contracts import FeatureSnapshot, Prediction


def _softmax(values: list[float]) -> list[float]:
    if not values:
        return []
    max_value = max(values)
    exp_values = [math.exp(value - max_value) for value in values]
    total = sum(exp_values)
    return [value / total for value in exp_values]


@dataclass(slots=True)
class CentroidArtifact:
    model_version: str
    feature_set_version: str
    horizon_min: int
    feature_names: list[str]
    centroids: dict[str, list[float]]


class CentroidDirectionModel:
    def __init__(self, artifact: CentroidArtifact) -> None:
        self.artifact = artifact

    @classmethod
    def from_path(cls, artifact_path: Path) -> "CentroidDirectionModel":
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact = CentroidArtifact(
            model_version=payload["model_version"],
            feature_set_version=payload["feature_set_version"],
            horizon_min=int(payload["horizon_min"]),
            feature_names=list(payload["feature_names"]),
            centroids={key: [float(value) for value in values] for key, values in payload["centroids"].items()},
        )
        return cls(artifact)

    def predict(self, feature_snapshot: FeatureSnapshot, horizon_min: int, prediction_id: str) -> Prediction:
        vector = [float(feature_snapshot.values.get(name, 0.0)) for name in self.artifact.feature_names]
        labels = ["up", "flat", "down"]
        distances: dict[str, float] = {}
        for label in labels:
            centroid = self.artifact.centroids.get(label)
            if centroid is None:
                distances[label] = 1e9
                continue
            distance = math.sqrt(sum((value - centroid[index]) ** 2 for index, value in enumerate(vector)))
            distances[label] = distance

        logits = [-distances["up"], -distances["flat"], -distances["down"]]
        probability_up, probability_flat, probability_down = _softmax(logits)
        return Prediction(
            prediction_id=prediction_id,
            symbol=feature_snapshot.symbol,
            event_time=feature_snapshot.event_time,
            horizon_min=horizon_min,
            model_version=self.artifact.model_version,
            probability_up=probability_up,
            probability_flat=probability_flat,
            probability_down=probability_down,
        )


def find_latest_centroid_artifact(runtime_root: Path, horizon_min: int) -> Path | None:
    model_dir = runtime_root / "ml" / "models"
    if not model_dir.exists():
        return None
    candidates = sorted(model_dir.glob(f"centroid-h{horizon_min}-*.json"))
    if candidates:
        return candidates[-1]
    exact = model_dir / f"centroid-h{horizon_min}-v1.json"
    return exact if exact.exists() else None
