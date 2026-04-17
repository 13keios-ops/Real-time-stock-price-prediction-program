"""Runtime writer that fans out events to JSONL and SQLite stores."""

from __future__ import annotations

from pathlib import Path

from app.config.settings import AppSettings
from app.storage.contracts import (
    FeatureLabel,
    FeatureSnapshot,
    Fill,
    BrokerOrderSubmission,
    MarketTickEvent,
    MinuteBar,
    ModelEvaluation,
    OrderEvent,
    OrderbookSnapshot,
    PaperPosition,
    PaperOrder,
    PortfolioSnapshot,
    Prediction,
    ReconciliationRun,
    ReplayRun,
    RiskEvent,
    TargetPosition,
    TradeSignal,
    TrainingRun,
)
from app.storage.jsonl_store import JsonlArtifactStore
from app.storage.sqlite_store import SQLiteRuntimeStore, resolve_sqlite_path


class RuntimeWriter:
    def __init__(self, jsonl_store: JsonlArtifactStore, sqlite_store: SQLiteRuntimeStore | None = None) -> None:
        self.jsonl_store = jsonl_store
        self.sqlite_store = sqlite_store

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings,
        *,
        sqlite_initialize_schema: bool = True,
        sqlite_busy_timeout_ms: int = 10_000,
        sqlite_read_retry_delays: tuple[float, ...] = (0.0, 0.15, 0.35, 0.75),
        sqlite_write_retry_delays: tuple[float, ...] = (0.0, 0.2, 0.5, 1.0),
    ) -> "RuntimeWriter":
        jsonl_store = JsonlArtifactStore(settings.runtime_data_dir)
        sqlite_path = resolve_sqlite_path(settings.database_url, settings.project_root)
        sqlite_store = (
            SQLiteRuntimeStore(
                sqlite_path,
                initialize_schema=sqlite_initialize_schema,
                busy_timeout_ms=sqlite_busy_timeout_ms,
                read_retry_delays=sqlite_read_retry_delays,
                write_retry_delays=sqlite_write_retry_delays,
            )
            if sqlite_path is not None
            else None
        )
        return cls(jsonl_store=jsonl_store, sqlite_store=sqlite_store)

    def write_market_tick(self, event: MarketTickEvent) -> None:
        self.jsonl_store.append("raw", "market_ticks", event.to_record(), event.event_time)
        if self.sqlite_store:
            self.sqlite_store.insert_market_tick(event)

    def write_orderbook_snapshot(self, event: OrderbookSnapshot) -> None:
        self.jsonl_store.append("raw", "orderbook_ticks", event.to_record(), event.event_time)
        if self.sqlite_store:
            self.sqlite_store.insert_orderbook_snapshot(event)

    def write_minute_bar(self, bar: MinuteBar) -> None:
        self.jsonl_store.append("curated", "minute_bars", bar.to_record(), bar.bar_time)
        if self.sqlite_store:
            self.sqlite_store.upsert_minute_bar(bar)

    def write_feature_snapshot(self, snapshot: FeatureSnapshot) -> None:
        self.jsonl_store.append("feature", "model_inputs", snapshot.to_record(), snapshot.event_time)
        if self.sqlite_store:
            self.sqlite_store.upsert_feature_snapshot(snapshot)

    def write_feature_label(self, label: FeatureLabel) -> None:
        self.jsonl_store.append("feature", "labels", label.to_record(), label.event_time)
        if self.sqlite_store:
            self.sqlite_store.upsert_feature_label(label)

    def write_prediction(self, prediction: Prediction) -> None:
        self.jsonl_store.append("serving", "predictions", prediction.to_record(), prediction.event_time)
        if self.sqlite_store:
            self.sqlite_store.insert_prediction(prediction)

    def write_trade_signal(self, signal: TradeSignal) -> None:
        self.jsonl_store.append("serving", "trade_signals", signal.to_record(), signal.event_time)
        if self.sqlite_store:
            self.sqlite_store.insert_trade_signal(signal)

    def write_target_position(self, target: TargetPosition) -> None:
        self.jsonl_store.append("serving", "target_positions", target.to_record(), target.event_time)
        if self.sqlite_store:
            self.sqlite_store.insert_target_position(target)

    def write_paper_order(self, order: PaperOrder) -> None:
        self.jsonl_store.append("paper", "orders", order.to_record(), order.event_time)
        if self.sqlite_store:
            self.sqlite_store.insert_paper_order(order)

    def write_order_event(self, event: OrderEvent) -> None:
        self.jsonl_store.append("paper", "order_events", event.to_record(), event.event_time)
        if self.sqlite_store:
            self.sqlite_store.insert_order_event(event)

    def write_fill(self, fill: Fill) -> None:
        self.jsonl_store.append("paper", "fills", fill.to_record(), fill.event_time)
        if self.sqlite_store:
            self.sqlite_store.insert_fill(fill)

    def write_paper_position(self, position: PaperPosition) -> None:
        self.jsonl_store.append("paper", "positions", position.to_record(), position.updated_at)
        if self.sqlite_store:
            self.sqlite_store.upsert_paper_position(position)

    def write_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        self.jsonl_store.append("paper", "portfolio_snapshots", snapshot.to_record(), snapshot.event_time)
        if self.sqlite_store:
            self.sqlite_store.insert_portfolio_snapshot(snapshot)

    def write_broker_order_submission(self, submission: BrokerOrderSubmission) -> None:
        self.jsonl_store.append("broker", "paper_order_submissions", submission.to_record(), submission.event_time)
        if self.sqlite_store:
            self.sqlite_store.insert_broker_order_submission(submission)

    def write_risk_event(self, event: RiskEvent) -> None:
        self.jsonl_store.append("ops", "risk_events", event.to_record(), event.event_time)
        if self.sqlite_store:
            self.sqlite_store.insert_risk_event(event)

    def write_reconciliation_run(self, run: ReconciliationRun) -> None:
        self.jsonl_store.append("ops", "reconciliation_runs", run.to_record(), run.as_of)
        if self.sqlite_store:
            self.sqlite_store.insert_reconciliation_run(run)

    def write_replay_run(self, run: ReplayRun) -> None:
        self.jsonl_store.append("ops", "replay_runs", run.to_record(), run.as_of)
        if self.sqlite_store:
            self.sqlite_store.insert_replay_run(run)

    def write_training_run(self, run: TrainingRun) -> None:
        self.jsonl_store.append("ml", "training_runs", run.to_record(), run.completed_at)
        if self.sqlite_store:
            self.sqlite_store.insert_training_run(run)

    def write_model_evaluation(self, evaluation: ModelEvaluation) -> None:
        self.jsonl_store.append("ml", "model_evaluations", evaluation.to_record(), evaluation.evaluated_at)
        if self.sqlite_store:
            self.sqlite_store.insert_model_evaluation(evaluation)


def get_sqlite_store(
    settings: AppSettings,
    *,
    initialize_schema: bool = True,
    busy_timeout_ms: int = 10_000,
    read_retry_delays: tuple[float, ...] = (0.0, 0.15, 0.35, 0.75),
    write_retry_delays: tuple[float, ...] = (0.0, 0.2, 0.5, 1.0),
) -> SQLiteRuntimeStore | None:
    sqlite_path = resolve_sqlite_path(settings.database_url, settings.project_root)
    if sqlite_path is None:
        return None
    return SQLiteRuntimeStore(
        sqlite_path,
        initialize_schema=initialize_schema,
        busy_timeout_ms=busy_timeout_ms,
        read_retry_delays=read_retry_delays,
        write_retry_delays=write_retry_delays,
    )
