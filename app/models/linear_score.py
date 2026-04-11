"""Simple linear-score challenger model built from engineered features."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.storage.contracts import FeatureSnapshot, Prediction


def _softmax(values: list[float]) -> list[float]:
    max_value = max(values)
    exp_values = [math.exp(value - max_value) for value in values]
    total = sum(exp_values)
    return [value / total for value in exp_values]


@dataclass(slots=True)
class LinearScoreConfig:
    model_version: str
    feature_set_version: str
    horizon_min: int
    weights: dict[str, float]
    bias: float = 0.0
    score_scale: float = 3.2
    flat_bias: float = 0.55


class LinearScoreDirectionModel:
    def __init__(self, config: LinearScoreConfig) -> None:
        self.config = config

    def predict(self, feature_snapshot: FeatureSnapshot, horizon_min: int, prediction_id: str) -> Prediction:
        raw_score = self.config.bias
        for name, weight in self.config.weights.items():
            raw_score += float(feature_snapshot.values.get(name, 0.0)) * weight

        scaled_score = raw_score * self.config.score_scale
        flat_logit = self.config.flat_bias - abs(raw_score)
        probability_up, probability_flat, probability_down = _softmax(
            [scaled_score, flat_logit, -scaled_score]
        )
        return Prediction(
            prediction_id=prediction_id,
            symbol=feature_snapshot.symbol,
            event_time=feature_snapshot.event_time,
            horizon_min=horizon_min,
            model_version=self.config.model_version,
            probability_up=probability_up,
            probability_flat=probability_flat,
            probability_down=probability_down,
        )

