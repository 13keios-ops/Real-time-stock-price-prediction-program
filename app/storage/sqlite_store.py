"""SQLite runtime store for local development and research workflows."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

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


def resolve_sqlite_path(database_url: str, project_root: Path) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    relative = database_url[len(prefix) :]
    path = Path(relative)
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


class SQLiteRuntimeStore:
    def __init__(
        self,
        database_path: Path,
        *,
        initialize_schema: bool = True,
        busy_timeout_ms: int = 10_000,
        read_retry_delays: tuple[float, ...] = (0.0, 0.15, 0.35, 0.75),
        write_retry_delays: tuple[float, ...] = (0.0, 0.2, 0.5, 1.0),
    ) -> None:
        self.database_path = database_path
        self.busy_timeout_ms = max(int(busy_timeout_ms), 1_000)
        self.read_retry_delays = tuple(read_retry_delays)
        self.write_retry_delays = tuple(write_retry_delays)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if initialize_schema:
            self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=self.busy_timeout_ms / 1_000.0)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    def _initialize_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS raw_market_ticks (
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                price REAL NOT NULL,
                volume INTEGER NOT NULL,
                source TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS raw_orderbook_ticks (
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                bid_price REAL NOT NULL,
                ask_price REAL NOT NULL,
                bid_size INTEGER NOT NULL,
                ask_size INTEGER NOT NULL,
                source TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS curated_minute_bars (
                symbol TEXT NOT NULL,
                bar_time TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                trade_count INTEGER NOT NULL,
                PRIMARY KEY (symbol, bar_time)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS feature_model_inputs (
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                feature_set_version TEXT NOT NULL,
                values_json TEXT NOT NULL,
                PRIMARY KEY (symbol, event_time, feature_set_version)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS feature_labels (
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                horizon_min INTEGER NOT NULL,
                label TEXT NOT NULL,
                threshold_pct REAL NOT NULL,
                future_return_pct REAL NOT NULL,
                PRIMARY KEY (symbol, event_time, horizon_min)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS serving_predictions (
                prediction_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                horizon_min INTEGER NOT NULL,
                model_version TEXT NOT NULL,
                probability_up REAL NOT NULL,
                probability_flat REAL NOT NULL,
                probability_down REAL NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS serving_trade_signals (
                signal_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                side TEXT NOT NULL,
                confidence REAL NOT NULL,
                reason TEXT NOT NULL,
                allowed INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS serving_target_positions (
                target_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                side TEXT NOT NULL,
                target_qty INTEGER NOT NULL,
                target_notional REAL NOT NULL,
                portfolio_version TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS paper_orders (
                order_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                limit_price REAL NOT NULL,
                status TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS paper_order_events (
                order_event_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                event_time TEXT NOT NULL,
                event_type TEXT NOT NULL,
                detail TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS paper_fills (
                fill_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                event_time TEXT NOT NULL,
                fill_price REAL NOT NULL,
                fill_qty INTEGER NOT NULL,
                commission REAL NOT NULL,
                tax REAL NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS paper_positions (
                symbol TEXT PRIMARY KEY,
                opened_at TEXT,
                updated_at TEXT NOT NULL,
                qty INTEGER NOT NULL,
                avg_price REAL NOT NULL,
                last_price REAL NOT NULL,
                market_value REAL NOT NULL,
                cost_basis REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS paper_portfolio_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                event_time TEXT NOT NULL,
                cash_balance REAL NOT NULL,
                gross_market_value REAL NOT NULL,
                net_liquidation_value REAL NOT NULL,
                open_positions INTEGER NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS broker_paper_order_submissions (
                submission_id TEXT PRIMARY KEY,
                local_order_id TEXT NOT NULL,
                broker_mode TEXT NOT NULL,
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                limit_price REAL NOT NULL,
                order_type TEXT NOT NULL,
                status TEXT NOT NULL,
                broker_order_no TEXT NOT NULL,
                broker_branch_no TEXT NOT NULL,
                detail_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ops_risk_events (
                risk_event_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                gate TEXT NOT NULL,
                detail TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ops_reconciliation_runs (
                reconciliation_id TEXT PRIMARY KEY,
                as_of TEXT NOT NULL,
                status TEXT NOT NULL,
                mismatch_count INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ops_replay_runs (
                replay_id TEXT PRIMARY KEY,
                as_of TEXT NOT NULL,
                status TEXT NOT NULL,
                drift_count INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ml_training_runs (
                training_run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                model_version TEXT NOT NULL,
                feature_set_version TEXT NOT NULL,
                horizon_min INTEGER NOT NULL,
                train_rows INTEGER NOT NULL,
                validation_rows INTEGER NOT NULL,
                training_summary_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ml_model_evaluations (
                evaluation_id TEXT PRIMARY KEY,
                training_run_id TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                split_name TEXT NOT NULL,
                accuracy REAL NOT NULL,
                total_rows INTEGER NOT NULL,
                metrics_json TEXT NOT NULL
            )
            """,
        ]
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            for statement in statements:
                connection.execute(statement)
            self._ensure_column(connection, "paper_positions", "opened_at", "TEXT")
            connection.commit()

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in columns:
            return
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _dt(value: datetime) -> str:
        return value.isoformat()

    def _run_read_query(
        self,
        query: str,
        params: tuple[Any, ...] = (),
        *,
        single: bool = False,
    ) -> sqlite3.Row | list[sqlite3.Row] | None:
        last_error: sqlite3.OperationalError | None = None
        for attempt, delay_seconds in enumerate(self.read_retry_delays):
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            try:
                with self._connect() as connection:
                    cursor = connection.execute(query, params)
                    return cursor.fetchone() if single else list(cursor)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                last_error = exc
                if attempt == len(self.read_retry_delays) - 1:
                    raise
        if last_error is not None:
            raise last_error
        return None

    def _run_write_query(self, query: str, params: tuple[Any, ...] = ()) -> None:
        last_error: sqlite3.OperationalError | None = None
        for attempt, delay_seconds in enumerate(self.write_retry_delays):
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            try:
                with self._connect() as connection:
                    connection.execute(query, params)
                    connection.commit()
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                last_error = exc
                if attempt == len(self.write_retry_delays) - 1:
                    raise
        if last_error is not None:
            raise last_error

    def insert_market_tick(self, event: MarketTickEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO raw_market_ticks(symbol, event_time, price, volume, source) VALUES (?, ?, ?, ?, ?)",
                (event.symbol, self._dt(event.event_time), event.price, event.volume, event.source),
            )
            connection.commit()

    def insert_orderbook_snapshot(self, event: OrderbookSnapshot) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO raw_orderbook_ticks(symbol, event_time, bid_price, ask_price, bid_size, ask_size, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.symbol,
                    self._dt(event.event_time),
                    event.bid_price,
                    event.ask_price,
                    event.bid_size,
                    event.ask_size,
                    event.source,
                ),
            )
            connection.commit()

    def upsert_minute_bar(self, bar: MinuteBar) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO curated_minute_bars(symbol, bar_time, open, high, low, close, volume, trade_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (bar.symbol, self._dt(bar.bar_time), bar.open, bar.high, bar.low, bar.close, bar.volume, bar.trade_count),
            )
            connection.commit()

    def upsert_feature_snapshot(self, snapshot: FeatureSnapshot) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO feature_model_inputs(symbol, event_time, feature_set_version, values_json)
                VALUES (?, ?, ?, ?)
                """,
                (snapshot.symbol, self._dt(snapshot.event_time), snapshot.feature_set_version, self._json(snapshot.values)),
            )
            connection.commit()

    def upsert_feature_label(self, label: FeatureLabel) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO feature_labels(symbol, event_time, horizon_min, label, threshold_pct, future_return_pct)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    label.symbol,
                    self._dt(label.event_time),
                    label.horizon_min,
                    label.label,
                    label.threshold_pct,
                    label.future_return_pct,
                ),
            )
            connection.commit()

    def insert_prediction(self, prediction: Prediction) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO serving_predictions(
                    prediction_id, symbol, event_time, horizon_min, model_version, probability_up, probability_flat, probability_down
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prediction.prediction_id,
                    prediction.symbol,
                    self._dt(prediction.event_time),
                    prediction.horizon_min,
                    prediction.model_version,
                    prediction.probability_up,
                    prediction.probability_flat,
                    prediction.probability_down,
                ),
            )
            connection.commit()

    def insert_trade_signal(self, signal: TradeSignal) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO serving_trade_signals(signal_id, symbol, event_time, side, confidence, reason, allowed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.signal_id,
                    signal.symbol,
                    self._dt(signal.event_time),
                    signal.side,
                    signal.confidence,
                    signal.reason,
                    int(signal.allowed),
                ),
            )
            connection.commit()

    def insert_target_position(self, target: TargetPosition) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO serving_target_positions(
                    target_id, symbol, event_time, side, target_qty, target_notional, portfolio_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target.target_id,
                    target.symbol,
                    self._dt(target.event_time),
                    target.side,
                    target.target_qty,
                    target.target_notional,
                    target.portfolio_version,
                ),
            )
            connection.commit()

    def insert_paper_order(self, order: PaperOrder) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO paper_orders(order_id, symbol, event_time, side, qty, limit_price, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (order.order_id, order.symbol, self._dt(order.event_time), order.side, order.qty, order.limit_price, order.status),
            )
            connection.commit()

    def insert_order_event(self, event: OrderEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO paper_order_events(order_event_id, order_id, event_time, event_type, detail) VALUES (?, ?, ?, ?, ?)",
                (event.order_event_id, event.order_id, self._dt(event.event_time), event.event_type, event.detail),
            )
            connection.commit()

    def insert_fill(self, fill: Fill) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO paper_fills(fill_id, order_id, event_time, fill_price, fill_qty, commission, tax)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (fill.fill_id, fill.order_id, self._dt(fill.event_time), fill.fill_price, fill.fill_qty, fill.commission, fill.tax),
            )
            connection.commit()

    def upsert_paper_position(self, position: PaperPosition) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO paper_positions(
                    symbol, opened_at, updated_at, qty, avg_price, last_price, market_value, cost_basis, realized_pnl, unrealized_pnl
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position.symbol,
                    self._dt(position.opened_at) if position.opened_at else None,
                    self._dt(position.updated_at),
                    position.qty,
                    position.avg_price,
                    position.last_price,
                    position.market_value,
                    position.cost_basis,
                    position.realized_pnl,
                    position.unrealized_pnl,
                ),
            )
            connection.commit()

    def insert_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO paper_portfolio_snapshots(
                    snapshot_id, event_time, cash_balance, gross_market_value, net_liquidation_value,
                    open_positions, realized_pnl, unrealized_pnl
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    self._dt(snapshot.event_time),
                    snapshot.cash_balance,
                    snapshot.gross_market_value,
                    snapshot.net_liquidation_value,
                    snapshot.open_positions,
                    snapshot.realized_pnl,
                    snapshot.unrealized_pnl,
                ),
            )
            connection.commit()

    def insert_broker_order_submission(self, submission: BrokerOrderSubmission) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO broker_paper_order_submissions(
                    submission_id, local_order_id, broker_mode, symbol, event_time, side, qty, limit_price,
                    order_type, status, broker_order_no, broker_branch_no, detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission.submission_id,
                    submission.local_order_id,
                    submission.broker_mode,
                    submission.symbol,
                    self._dt(submission.event_time),
                    submission.side,
                    submission.qty,
                    submission.limit_price,
                    submission.order_type,
                    submission.status,
                    submission.broker_order_no,
                    submission.broker_branch_no,
                    self._json(submission.detail),
                ),
            )
            connection.commit()

    def insert_risk_event(self, event: RiskEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO ops_risk_events(risk_event_id, symbol, event_time, gate, detail) VALUES (?, ?, ?, ?, ?)",
                (event.risk_event_id, event.symbol, self._dt(event.event_time), event.gate, event.detail),
            )
            connection.commit()

    def insert_reconciliation_run(self, run: ReconciliationRun) -> None:
        self._run_write_query(
            "INSERT OR REPLACE INTO ops_reconciliation_runs(reconciliation_id, as_of, status, mismatch_count) VALUES (?, ?, ?, ?)",
            (run.reconciliation_id, self._dt(run.as_of), run.status, run.mismatch_count),
        )

    def insert_replay_run(self, run: ReplayRun) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO ops_replay_runs(replay_id, as_of, status, drift_count) VALUES (?, ?, ?, ?)",
                (run.replay_id, self._dt(run.as_of), run.status, run.drift_count),
            )
            connection.commit()

    def insert_training_run(self, run: TrainingRun) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO ml_training_runs(
                    training_run_id, started_at, completed_at, model_version, feature_set_version, horizon_min,
                    train_rows, validation_rows, training_summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.training_run_id,
                    self._dt(run.started_at),
                    self._dt(run.completed_at),
                    run.model_version,
                    run.feature_set_version,
                    run.horizon_min,
                    run.train_rows,
                    run.validation_rows,
                    self._json(run.training_summary),
                ),
            )
            connection.commit()

    def insert_model_evaluation(self, evaluation: ModelEvaluation) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO ml_model_evaluations(
                    evaluation_id, training_run_id, evaluated_at, split_name, accuracy, total_rows, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation.evaluation_id,
                    evaluation.training_run_id,
                    self._dt(evaluation.evaluated_at),
                    evaluation.split_name,
                    evaluation.accuracy,
                    evaluation.total_rows,
                    self._json(evaluation.metrics),
                ),
            )
            connection.commit()

    def fetch_market_ticks(self, symbol: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT symbol, event_time, price, volume, source FROM raw_market_ticks"
        params: tuple[Any, ...] = ()
        if symbol:
            query += " WHERE symbol = ?"
            params = (symbol,)
        query += " ORDER BY symbol, event_time"
        rows = self._run_read_query(query, params)
        return list(rows) if isinstance(rows, list) else []

    def fetch_orderbook_snapshots(self, symbol: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT symbol, event_time, bid_price, ask_price, bid_size, ask_size, source FROM raw_orderbook_ticks"
        params: tuple[Any, ...] = ()
        if symbol:
            query += " WHERE symbol = ?"
            params = (symbol,)
        query += " ORDER BY symbol, event_time"
        rows = self._run_read_query(query, params)
        return list(rows) if isinstance(rows, list) else []

    def fetch_minute_bars(self, symbol: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT symbol, bar_time, open, high, low, close, volume, trade_count FROM curated_minute_bars"
        params: tuple[Any, ...] = ()
        if symbol:
            query += " WHERE symbol = ?"
            params = (symbol,)
        query += " ORDER BY symbol, bar_time"
        rows = self._run_read_query(query, params)
        return list(rows) if isinstance(rows, list) else []

    def fetch_feature_rows(self, horizon_min: int) -> list[sqlite3.Row]:
        query = """
            SELECT
                inputs.symbol,
                inputs.event_time,
                inputs.feature_set_version,
                inputs.values_json,
                labels.horizon_min,
                labels.label,
                labels.threshold_pct,
                labels.future_return_pct
            FROM feature_model_inputs AS inputs
            INNER JOIN feature_labels AS labels
                ON inputs.symbol = labels.symbol
               AND inputs.event_time = labels.event_time
            WHERE labels.horizon_min = ?
            ORDER BY inputs.symbol, inputs.event_time
        """
        rows = self._run_read_query(query, (horizon_min,))
        return list(rows) if isinstance(rows, list) else []

    def fetch_latest_row(self, table_name: str, order_by_column: str) -> sqlite3.Row | None:
        query = f"SELECT * FROM {table_name} ORDER BY {order_by_column} DESC LIMIT 1"
        row = self._run_read_query(query, single=True)
        return row if isinstance(row, sqlite3.Row) or row is None else None

    def fetch_all_rows(self, table_name: str, order_by_column: str) -> list[sqlite3.Row]:
        query = f"SELECT * FROM {table_name} ORDER BY {order_by_column}"
        rows = self._run_read_query(query)
        return list(rows) if isinstance(rows, list) else []

    def fetch_recent_rows(self, table_name: str, order_by_column: str, limit: int = 10) -> list[sqlite3.Row]:
        query = f"SELECT * FROM {table_name} ORDER BY {order_by_column} DESC LIMIT ?"
        rows = self._run_read_query(query, (limit,))
        return list(rows) if isinstance(rows, list) else []

    def count_rows(self, table_name: str) -> int:
        row = self._run_read_query(f"SELECT COUNT(*) AS count FROM {table_name}", single=True)
        if row is None:
            return 0
        return int(row["count"])

    def clear_tables(self, table_names: Iterable[str]) -> None:
        with self._connect() as connection:
            for table_name in table_names:
                connection.execute(f"DELETE FROM {table_name}")
            connection.commit()
