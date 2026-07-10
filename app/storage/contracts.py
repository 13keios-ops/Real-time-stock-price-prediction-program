"""Storage contracts used across the foundation runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


LIVE_ORDER_EVENT_ACTORS = {"system", "account_owner", "recovery", "kill_switch", "test"}


def _require_keys(value: dict[str, Any], required_keys: set[str], field_name: str) -> None:
    missing_keys = sorted(required_keys - set(value))
    if missing_keys:
        raise ValueError(f"{field_name} missing required keys: {', '.join(missing_keys)}")


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _require_type(value: Any, expected_type: type, field_name: str) -> None:
    if not isinstance(value, expected_type):
        raise ValueError(f"{field_name} must be {expected_type.__name__}")


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
    training_run_id: str | None = None
    artifact_id: str | None = None
    artifact_sha256: str | None = None


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
    prediction_id: str | None = None
    signal_id: str | None = None
    target_id: str | None = None


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
class BrokerOrderSubmission(RecordMixin):
    submission_id: str
    local_order_id: str
    broker_mode: str
    symbol: str
    event_time: datetime
    side: str
    qty: int
    limit_price: float
    order_type: str
    status: str
    broker_order_no: str
    broker_branch_no: str
    detail: dict[str, Any]


@dataclass(slots=True)
class BrokerOrderStatusSnapshot(RecordMixin):
    sync_id: str
    local_order_id: str
    broker_mode: str
    symbol: str
    synced_at: datetime
    order_date: str
    side: str
    order_qty: int
    filled_qty: int
    remaining_qty: int
    avg_fill_price: float
    status: str
    broker_order_no: str
    broker_branch_no: str
    reject_qty: int
    cancel_confirm_qty: int
    cancel_yn: bool
    matched: bool
    applied_fill_qty: int
    detail: dict[str, Any]


@dataclass(slots=True)
class MarketStatusSnapshot(RecordMixin):
    snapshot_id: str
    trading_day: str
    created_at: datetime
    source: str
    symbol_set_hash: str
    status_json: dict[str, Any]
    stale_after: datetime

    def __post_init__(self) -> None:
        _require_keys(
            self.status_json,
            {"symbols", "market_session", "source_generated_at"},
            "status_json",
        )
        _require_type(self.status_json["symbols"], dict, "status_json.symbols")
        _require_type(self.status_json["market_session"], str, "status_json.market_session")
        _require_non_empty(self.status_json["market_session"], "status_json.market_session")
        _require_type(self.status_json["source_generated_at"], str, "status_json.source_generated_at")
        _require_non_empty(self.status_json["source_generated_at"], "status_json.source_generated_at")


@dataclass(slots=True)
class LiveOrder(RecordMixin):
    order_id: str
    idempotency_key: str
    trading_day: str
    phase: str
    symbol: str
    side: str
    qty: int
    filled_qty: int
    remaining_qty: int
    order_type: str
    limit_price: float
    avg_fill_price: float
    status: str
    prediction_id: str
    signal_id: str
    target_id: str
    gate_decision_id: str
    market_status_snapshot_id: str
    model_version: str
    rule_version: str
    broker_order_no: str
    broker_branch_no: str
    reject_reason: str | None
    cancel_reason: str | None
    parent_order_id: str | None
    created_at: datetime
    submitted_at: datetime | None
    last_synced_at: datetime | None
    detail_json: dict[str, Any]

    def __post_init__(self) -> None:
        for field_name in (
            "order_id",
            "idempotency_key",
            "trading_day",
            "phase",
            "symbol",
            "side",
            "order_type",
            "status",
            "prediction_id",
            "signal_id",
            "target_id",
            "gate_decision_id",
            "market_status_snapshot_id",
            "model_version",
            "rule_version",
        ):
            _require_non_empty(getattr(self, field_name), field_name)
        _require_keys(
            self.detail_json,
            {"order_policy", "blocking_reasons", "raw_broker_response"},
            "detail_json",
        )
        _require_type(self.detail_json["order_policy"], dict, "detail_json.order_policy")
        _require_type(self.detail_json["blocking_reasons"], list, "detail_json.blocking_reasons")
        _require_type(self.detail_json["raw_broker_response"], dict, "detail_json.raw_broker_response")


@dataclass(slots=True)
class LiveOrderEvent(RecordMixin):
    order_event_id: str
    order_id: str
    event_time: datetime
    from_status: str
    to_status: str
    event_type: str
    actor: str
    detail_json: dict[str, Any]

    def __post_init__(self) -> None:
        if self.actor not in LIVE_ORDER_EVENT_ACTORS:
            allowed = ", ".join(sorted(LIVE_ORDER_EVENT_ACTORS))
            raise ValueError(f"actor must be one of: {allowed}")
        _require_keys(
            self.detail_json,
            {"reason", "source", "raw_broker_response"},
            "detail_json",
        )
        _require_type(self.detail_json["reason"], str, "detail_json.reason")
        _require_type(self.detail_json["source"], str, "detail_json.source")
        _require_type(self.detail_json["raw_broker_response"], dict, "detail_json.raw_broker_response")


@dataclass(slots=True)
class LiveFill(RecordMixin):
    fill_id: str
    order_id: str
    broker_order_no: str
    broker_branch_no: str
    symbol: str
    trading_day: str
    event_time: datetime
    side: str
    fill_qty: int
    fill_price: float
    commission: float
    tax: float
    fee: float
    settlement_day: str
    detail_json: dict[str, Any]

    def __post_init__(self) -> None:
        for field_name in (
            "fill_id",
            "order_id",
            "symbol",
            "trading_day",
            "side",
            "settlement_day",
        ):
            _require_non_empty(getattr(self, field_name), field_name)
        _require_keys(self.detail_json, {"raw_broker_fill", "fees", "settlement"}, "detail_json")
        _require_type(self.detail_json["raw_broker_fill"], dict, "detail_json.raw_broker_fill")
        _require_type(self.detail_json["fees"], dict, "detail_json.fees")
        _require_type(self.detail_json["settlement"], dict, "detail_json.settlement")


@dataclass(slots=True)
class LivePosition(RecordMixin):
    symbol: str
    trading_day: str
    opened_at: datetime | None
    updated_at: datetime
    qty: int
    avg_price: float
    last_price: float
    market_value: float
    cost_basis: float
    realized_pnl: float
    unrealized_pnl: float
    day_realized_pnl: float
    broker_qty: int
    detail_json: dict[str, Any]

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        _require_non_empty(self.trading_day, "trading_day")
        _require_keys(self.detail_json, {"source", "raw_broker_position"}, "detail_json")
        _require_type(self.detail_json["source"], str, "detail_json.source")
        _require_type(self.detail_json["raw_broker_position"], dict, "detail_json.raw_broker_position")


@dataclass(slots=True)
class LivePortfolioSnapshot(RecordMixin):
    snapshot_id: str
    trading_day: str
    event_time: datetime
    cash_balance: float
    available_cash: float
    unsettled_cash: float
    gross_market_value: float
    net_liquidation_value: float
    realized_pnl: float
    unrealized_pnl: float
    daily_pnl: float
    open_positions: int
    margin_requirement: float
    detail_json: dict[str, Any]

    def __post_init__(self) -> None:
        _require_non_empty(self.snapshot_id, "snapshot_id")
        _require_non_empty(self.trading_day, "trading_day")
        _require_keys(self.detail_json, {"source", "raw_broker_account"}, "detail_json")
        _require_type(self.detail_json["source"], str, "detail_json.source")
        _require_type(self.detail_json["raw_broker_account"], dict, "detail_json.raw_broker_account")


@dataclass(slots=True)
class LiveAuditEvent(RecordMixin):
    audit_event_id: str
    event_time: datetime
    trading_day: str
    event_type: str
    actor: str
    symbol: str
    order_id: str
    prediction_id: str
    signal_id: str
    gate_decision_id: str
    rule_version: str
    model_version: str
    data_snapshot_id: str
    previous_hash: str
    event_hash: str
    detail_json: dict[str, Any]

    def __post_init__(self) -> None:
        if self.actor not in LIVE_ORDER_EVENT_ACTORS:
            allowed = ", ".join(sorted(LIVE_ORDER_EVENT_ACTORS))
            raise ValueError(f"actor must be one of: {allowed}")
        for field_name in (
            "audit_event_id",
            "trading_day",
            "event_type",
            "symbol",
            "order_id",
            "rule_version",
            "model_version",
            "data_snapshot_id",
            "event_hash",
        ):
            _require_non_empty(getattr(self, field_name), field_name)
        _require_keys(self.detail_json, {"reason", "source", "gate_decision"}, "detail_json")
        _require_type(self.detail_json["reason"], str, "detail_json.reason")
        _require_type(self.detail_json["source"], str, "detail_json.source")
        _require_type(self.detail_json["gate_decision"], dict, "detail_json.gate_decision")


@dataclass(slots=True)
class LivePhaseApproval(RecordMixin):
    approval_id: str
    phase: str
    trading_day: str
    approved_at: datetime
    approved_by: str
    expires_at: datetime
    scope: str
    max_symbols: int
    max_parent_orders: int
    max_notional: float
    daily_loss_limit_pct: float
    per_symbol_loss_limit_pct: float
    slippage_budget_bps: float
    approval_hash: str
    detail_json: dict[str, Any]

    def __post_init__(self) -> None:
        for field_name in (
            "approval_id",
            "phase",
            "trading_day",
            "approved_by",
            "scope",
            "approval_hash",
        ):
            _require_non_empty(getattr(self, field_name), field_name)
        _require_keys(self.detail_json, {"approval_basis", "limits", "operator_decision_ref"}, "detail_json")
        _require_type(self.detail_json["approval_basis"], str, "detail_json.approval_basis")
        _require_type(self.detail_json["limits"], dict, "detail_json.limits")
        _require_type(self.detail_json["operator_decision_ref"], str, "detail_json.operator_decision_ref")


@dataclass(slots=True)
class LiveReadinessRun(RecordMixin):
    readiness_id: str
    trading_day: str
    checked_at: datetime
    phase: str
    status: str
    passed: bool
    token_refresh_ok: bool
    ws_recovery_ok: bool
    account_snapshot_ok: bool
    market_status_ok: bool
    kill_switch_ok: bool
    database_ok: bool
    checks_json: dict[str, Any]
    report_path: str

    def __post_init__(self) -> None:
        for field_name in ("readiness_id", "trading_day", "phase", "status", "report_path"):
            _require_non_empty(getattr(self, field_name), field_name)
        _require_keys(self.checks_json, {"checks", "blocking_reasons"}, "checks_json")
        _require_type(self.checks_json["checks"], dict, "checks_json.checks")
        _require_type(self.checks_json["blocking_reasons"], list, "checks_json.blocking_reasons")


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
