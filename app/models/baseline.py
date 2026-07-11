"""Baseline heuristic model used before training real ML artifacts."""

from __future__ import annotations

import math

from app.models.lineage import deterministic_model_lineage
from app.storage.contracts import FeatureSnapshot, Prediction


def _softmax(values: list[float]) -> list[float]:
    exp_values = [math.exp(value) for value in values]
    total = sum(exp_values)
    return [value / total for value in exp_values]


class BaselineDirectionModel:
    def __init__(self, model_version_h15: str, model_version_h60: str) -> None:
        self.model_version_h15 = model_version_h15
        self.model_version_h60 = model_version_h60

    def predict(self, feature_snapshot: FeatureSnapshot, horizon_min: int, prediction_id: str) -> Prediction:
        signal_strength = (
            feature_snapshot.values.get("return_1m_pct", 0.0) * 0.55
            + feature_snapshot.values.get("bid_ask_imbalance", 0.0) * 15
            - feature_snapshot.values.get("spread_bps", 0.0) * 0.03
        )
        if horizon_min >= 60:
            signal_strength *= 0.85

        logits = [signal_strength, 0.0, -signal_strength]
        probability_up, probability_flat, probability_down = _softmax(logits)
        model_version = self.model_version_h60 if horizon_min >= 60 else self.model_version_h15
        training_run_id, artifact_id, artifact_sha256 = deterministic_model_lineage(
            model_kind="baseline",
            model_version=model_version,
            payload={
                "horizon_min": horizon_min,
                "return_1m_pct_weight": 0.55,
                "bid_ask_imbalance_weight": 15.0,
                "spread_bps_weight": -0.03,
                "h60_scale": 0.85,
            },
        )
        return Prediction(
            prediction_id=prediction_id,
            symbol=feature_snapshot.symbol,
            event_time=feature_snapshot.event_time,
            horizon_min=horizon_min,
            model_version=model_version,
            probability_up=probability_up,
            probability_flat=probability_flat,
            probability_down=probability_down,
            training_run_id=training_run_id,
            artifact_id=artifact_id,
            artifact_sha256=artifact_sha256,
        )
