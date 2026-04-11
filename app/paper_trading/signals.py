"""Signal policy translating predictions into trade intent."""

from __future__ import annotations

from app.risk.gates import RiskDecision
from app.storage.contracts import OrderbookSnapshot, Prediction, TradeSignal


class SignalPolicy:
    def __init__(self, strategy_version: str, min_confidence: float) -> None:
        self.strategy_version = strategy_version
        self.min_confidence = min_confidence

    def evaluate(
        self,
        prediction: Prediction,
        orderbook: OrderbookSnapshot,
        time_gate: RiskDecision,
        spread_gate: RiskDecision,
        signal_id: str,
    ) -> TradeSignal:
        confidence = max(prediction.probability_up, prediction.probability_down)
        side = "buy" if prediction.probability_up >= prediction.probability_down else "sell"
        reasons = [
            f"model={prediction.model_version}",
            f"spread_bps={orderbook.spread_bps:.2f}",
            f"time_gate={time_gate.reason}",
            f"spread_gate={spread_gate.reason}",
        ]
        allowed = confidence >= self.min_confidence and time_gate.allowed and spread_gate.allowed and side == "buy"
        if confidence < self.min_confidence:
            reasons.append("confidence_below_threshold")
        if side != "buy":
            reasons.append("long_only_policy")
        return TradeSignal(
            signal_id=signal_id,
            symbol=prediction.symbol,
            event_time=prediction.event_time,
            side=side,
            confidence=confidence,
            reason=";".join(reasons),
            allowed=allowed,
        )
