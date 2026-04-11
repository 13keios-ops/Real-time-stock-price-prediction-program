"""Storage contracts used across the foundation runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: _serialize(inner) for key, inner in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _serialize(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(inner) for inner in value]
    return value


@dataclass(slots=True)
class RecordMixin:
    def to_record(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class MarketTickEvent(RecordMixin):
    symbol: str
    event_time: datetime
    price: float
    volume: int
    source: str


@dataclass(slots=True)
class OrderbookSnapshot(RecordMixin):
    symbol: str
    event_time: datetime
    bid_price: float
    ask_price: float
    bid_size: int
    ask_size: int
    source: str

    @property
    def spread(self) -> float:
        return self.ask_price - self.bid_price

    @property
    def spread_bps(self) -> float:
        midpoint = (self.ask_price + self.bid_price) / 2
        if midpoint == 0:
            return 0.0
        return (self.spread / midpoint) * 10_000


@dataclass(slots=True)
class MinuteBar(RecordMixin):
    symbol: str
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    trade_count: int


@dataclass(slots=True)
class FeatureSnapshot(RecordMixin):
    symbol: str
    event_time: datetime
    feature_set_version: str
    values: dict[str, float]


@dataclass(slots=True)
class FeatureLabel(RecordMixin):
    symbol: str
    event_time: datetime
    horizon_min: int
    label: str
    threshold_pct: float
    future_return_pct: float


@dataclass(slots=True)
class Prediction(RecordMixin):
    prediction_id: str
    symbol: str
    event_time: datetime
    horizon_min: int
    model_version: str
    probability_up: float
    probability_flat: float
    probability_down: float


@dataclass(slots=True)
class TradeSignal(RecordMixin):
    signal_id: str
    symbol: str
    event_time: datetime
    side: str
    confidence: float
    reason: str
    allowed: bool


@dataclass(slots=True)
class TargetPosition(RecordMixin):
    target_id: str
    symbol: str
    event_time: datetime
    side: str
    target_qty: int
    target_notional: float
    portfolio_version: str


@dataclass(slots=True)
class PaperOrder(RecordMixin):
    order_id: str
    symbol: str
    event_time: datetime
    side: str
    qty: int
    limit_price: float
    status: str


@dataclass(slots=True)
class OrderEvent(RecordMixin):
    order_event_id: str
    order_id: str
    event_time: datetime
    event_type: str
    detail: str


@dataclass(slots=True)
class Fill(RecordMixin):
    fill_id: str
    order_id: str
    event_time: datetime
    fill_price: float
    fill_qty: int
    commission: float
    tax: float


@dataclass(slots=True)
class PaperPosition(RecordMixin):
    symbol: str
    opened_at: datetime | None
    updated_at: datetime
    qty: int
    avg_price: float
    last_price: float
    market_value: float
    cost_basis: float
    realized_pnl: float
    unrealized_pnl: float


@dataclass(slots=True)
class PortfolioSnapshot(RecordMixin):
    snapshot_id: str
    event_time: datetime
    cash_balance: float
    gross_market_value: float
    net_liquidation_value: float
    open_positions: int
    realized_pnl: float
    unrealized_pnl: float


@dataclass(slots=True)
class RiskEvent(RecordMixin):
    risk_event_id: str
    symbol: str
    event_time: datetime
    gate: str
    detail: str


@dataclass(slots=True)
class ReconciliationRun(RecordMixin):
    reconciliation_id: str
    as_of: datetime
    status: str
    mismatch_count: int


@dataclass(slots=True)
class ReplayRun(RecordMixin):
    replay_id: str
    as_of: datetime
    status: str
    drift_count: int


@dataclass(slots=True)
class TrainingRun(RecordMixin):
    training_run_id: str
    started_at: datetime
    completed_at: datetime
    model_version: str
    feature_set_version: str
    horizon_min: int
    train_rows: int
    validation_rows: int
    training_summary: dict[str, Any]


@dataclass(slots=True)
class ModelEvaluation(RecordMixin):
    evaluation_id: str
    training_run_id: str
    evaluated_at: datetime
    split_name: str
    accuracy: float
    total_rows: int
    metrics: dict[str, Any]
