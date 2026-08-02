"""Risk gates for trading windows and market quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.storage.contracts import OrderbookSnapshot
from app.utils.time import parse_hhmm


@dataclass(slots=True)
class RiskDecision:
    allowed: bool
    reason: str


class TradingWindowGate:
    def __init__(self, new_entry_start: str, new_entry_end: str) -> None:
        self.new_entry_start = parse_hhmm(new_entry_start)
        self.new_entry_end = parse_hhmm(new_entry_end)

    def evaluate(self, timestamp: datetime) -> RiskDecision:
        current_time = timestamp.timetz().replace(tzinfo=None)
        if current_time < self.new_entry_start:
            return RiskDecision(allowed=False, reason="before_new_entry_window")
        if current_time > self.new_entry_end:
            return RiskDecision(allowed=False, reason="after_new_entry_window")
        return RiskDecision(allowed=True, reason="within_window")


class SpreadRiskGate:
    def __init__(self, max_spread_bps: float) -> None:
        self.max_spread_bps = max_spread_bps

    def evaluate(self, orderbook: OrderbookSnapshot) -> RiskDecision:
        if not orderbook.is_valid_for_trading:
            return RiskDecision(
                allowed=False,
                reason=orderbook.trading_validity_reason or "invalid_orderbook",
            )
        if orderbook.spread_bps > self.max_spread_bps:
            return RiskDecision(allowed=False, reason="spread_too_wide")
        return RiskDecision(allowed=True, reason="spread_ok")
