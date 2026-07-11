"""SQLite runtime store for local development and research workflows."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Iterable
from contextlib import closing, suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from app.storage.contracts import (
    FeatureLabel,
    FeatureSnapshot,
    Fill,
    BrokerOrderStatusSnapshot,
    BrokerOrderSubmission,
    LiveAuditEvent,
    LiveFill,
    LiveOrder,
    LiveOrderEvent,
    LivePhaseApproval,
    LivePortfolioSnapshot,
    LivePosition,
    LiveReadinessRun,
    MarketStatusSnapshot,
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
    ServingDecision,
    TargetPosition,
    TradeSignal,
    TrainingRun,
)


logger = logging.getLogger(__name__)

SQLITE_JOURNAL_MODE_FALLBACKS = ("WAL", "DELETE", "MEMORY")
LIVE_OPEN_ORDER_STATUSES = (
    "intent_created",
    "submit_pending",
    "submitted",
    "accepted",
    "open",
    "partially_filled",
    "cancel_requested",
    "unknown",
    "stuck",
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


def select_sqlite_journal_mode(database_path: Path) -> str:
    return SQLITE_JOURNAL_MODE_FALLBACKS[0]


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
        self.sqlite_journal_mode: str | None = None
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
            CREATE INDEX IF NOT EXISTS idx_raw_market_ticks_symbol_time
            ON raw_market_ticks(symbol, event_time)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_raw_market_ticks_source_symbol_time
            ON raw_market_ticks(source, symbol, event_time)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_raw_orderbook_ticks_symbol_time
            ON raw_orderbook_ticks(symbol, event_time)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_raw_orderbook_ticks_source_symbol_time
            ON raw_orderbook_ticks(source, symbol, event_time)
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
                probability_down REAL NOT NULL,
                training_run_id TEXT,
                artifact_id TEXT,
                artifact_sha256 TEXT
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
            CREATE TABLE IF NOT EXISTS serving_decision_ledger (
                decision_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                horizon_min INTEGER NOT NULL,
                active_prediction_id TEXT NOT NULL,
                active_model_version TEXT NOT NULL,
                active_training_run_id TEXT,
                active_artifact_id TEXT,
                active_artifact_sha256 TEXT,
                signal_id TEXT NOT NULL,
                signal_side TEXT NOT NULL,
                signal_allowed INTEGER NOT NULL,
                signal_confidence REAL NOT NULL,
                signal_reason TEXT NOT NULL,
                time_gate_allowed INTEGER NOT NULL,
                time_gate_reason TEXT NOT NULL,
                spread_gate_allowed INTEGER NOT NULL,
                spread_gate_reason TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_qty INTEGER NOT NULL,
                target_notional REAL NOT NULL,
                cash_balance_before REAL NOT NULL,
                open_positions_before INTEGER NOT NULL,
                symbol_position_qty_before INTEGER NOT NULL,
                pending_order_before INTEGER NOT NULL,
                execution_enabled INTEGER NOT NULL,
                decision_stage TEXT NOT NULL,
                decision_reason TEXT NOT NULL,
                shadow_predictions_json TEXT NOT NULL,
                order_id TEXT,
                order_status TEXT,
                fill_id TEXT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_serving_decision_symbol_time
            ON serving_decision_ledger(symbol, event_time)
            """,
            """
            CREATE TABLE IF NOT EXISTS paper_orders (
                order_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                limit_price REAL NOT NULL,
                status TEXT NOT NULL,
                prediction_id TEXT,
                signal_id TEXT,
                target_id TEXT
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
            CREATE TABLE IF NOT EXISTS broker_paper_order_status_snapshots (
                sync_id TEXT PRIMARY KEY,
                local_order_id TEXT NOT NULL,
                broker_mode TEXT NOT NULL,
                symbol TEXT NOT NULL,
                synced_at TEXT NOT NULL,
                order_date TEXT NOT NULL,
                side TEXT NOT NULL,
                order_qty INTEGER NOT NULL,
                filled_qty INTEGER NOT NULL,
                remaining_qty INTEGER NOT NULL,
                avg_fill_price REAL NOT NULL,
                status TEXT NOT NULL,
                broker_order_no TEXT NOT NULL,
                broker_branch_no TEXT NOT NULL,
                reject_qty INTEGER NOT NULL,
                cancel_confirm_qty INTEGER NOT NULL,
                cancel_yn INTEGER NOT NULL,
                matched INTEGER NOT NULL,
                applied_fill_qty INTEGER NOT NULL,
                detail_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS market_status_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                trading_day TEXT NOT NULL,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL,
                symbol_set_hash TEXT NOT NULL,
                status_json TEXT NOT NULL,
                stale_after TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_market_status_day_hash
            ON market_status_snapshots(trading_day, symbol_set_hash)
            """,
            """
            CREATE TABLE IF NOT EXISTS live_orders (
                order_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                trading_day TEXT NOT NULL,
                phase TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                filled_qty INTEGER NOT NULL,
                remaining_qty INTEGER NOT NULL,
                order_type TEXT NOT NULL,
                limit_price REAL NOT NULL,
                avg_fill_price REAL NOT NULL,
                status TEXT NOT NULL,
                prediction_id TEXT NOT NULL,
                signal_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                gate_decision_id TEXT NOT NULL,
                market_status_snapshot_id TEXT NOT NULL,
                model_version TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                broker_order_no TEXT NOT NULL,
                broker_branch_no TEXT NOT NULL,
                reject_reason TEXT,
                cancel_reason TEXT,
                parent_order_id TEXT,
                created_at TEXT NOT NULL,
                submitted_at TEXT,
                last_synced_at TEXT,
                detail_json TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_orders_status_symbol_day
            ON live_orders(status, symbol, trading_day)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_orders_broker
            ON live_orders(broker_branch_no, broker_order_no)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_orders_parent
            ON live_orders(parent_order_id)
            """,
            """
            CREATE TABLE IF NOT EXISTS live_order_events (
                order_event_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                event_time TEXT NOT NULL,
                from_status TEXT NOT NULL,
                to_status TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                detail_json TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_order_events_order_time
            ON live_order_events(order_id, event_time)
            """,
            """
            CREATE TABLE IF NOT EXISTS live_fills (
                fill_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                broker_order_no TEXT NOT NULL,
                broker_branch_no TEXT NOT NULL,
                symbol TEXT NOT NULL,
                trading_day TEXT NOT NULL,
                event_time TEXT NOT NULL,
                side TEXT NOT NULL,
                fill_qty INTEGER NOT NULL,
                fill_price REAL NOT NULL,
                commission REAL NOT NULL,
                tax REAL NOT NULL,
                fee REAL NOT NULL,
                settlement_day TEXT NOT NULL,
                detail_json TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_fills_order_time
            ON live_fills(order_id, event_time)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_fills_broker
            ON live_fills(broker_branch_no, broker_order_no)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_fills_symbol_day
            ON live_fills(symbol, trading_day)
            """,
            """
            CREATE TABLE IF NOT EXISTS live_positions (
                symbol TEXT PRIMARY KEY,
                trading_day TEXT NOT NULL,
                opened_at TEXT,
                updated_at TEXT NOT NULL,
                qty INTEGER NOT NULL,
                avg_price REAL NOT NULL,
                last_price REAL NOT NULL,
                market_value REAL NOT NULL,
                cost_basis REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                day_realized_pnl REAL NOT NULL,
                broker_qty INTEGER NOT NULL,
                detail_json TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_positions_updated_at
            ON live_positions(updated_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS live_portfolio_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                trading_day TEXT NOT NULL,
                event_time TEXT NOT NULL,
                cash_balance REAL NOT NULL,
                available_cash REAL NOT NULL,
                unsettled_cash REAL NOT NULL,
                gross_market_value REAL NOT NULL,
                net_liquidation_value REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                daily_pnl REAL NOT NULL,
                open_positions INTEGER NOT NULL,
                margin_requirement REAL NOT NULL,
                detail_json TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_portfolio_snapshots_time
            ON live_portfolio_snapshots(event_time)
            """,
            """
            CREATE TABLE IF NOT EXISTS ops_live_audit_events (
                audit_event_id TEXT PRIMARY KEY,
                event_time TEXT NOT NULL,
                trading_day TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                symbol TEXT NOT NULL,
                order_id TEXT NOT NULL,
                prediction_id TEXT NOT NULL,
                signal_id TEXT NOT NULL,
                gate_decision_id TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                model_version TEXT NOT NULL,
                data_snapshot_id TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE,
                detail_json TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ops_live_audit_order_time
            ON ops_live_audit_events(order_id, event_time)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ops_live_audit_hash
            ON ops_live_audit_events(event_hash)
            """,
            """
            CREATE TABLE IF NOT EXISTS live_phase_approvals (
                approval_id TEXT PRIMARY KEY,
                phase TEXT NOT NULL,
                trading_day TEXT NOT NULL,
                approved_at TEXT NOT NULL,
                approved_by TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                scope TEXT NOT NULL,
                max_symbols INTEGER NOT NULL,
                max_parent_orders INTEGER NOT NULL,
                max_notional REAL NOT NULL,
                daily_loss_limit_pct REAL NOT NULL,
                per_symbol_loss_limit_pct REAL NOT NULL,
                slippage_budget_bps REAL NOT NULL,
                approval_hash TEXT NOT NULL UNIQUE,
                detail_json TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_phase_approvals_day_phase
            ON live_phase_approvals(trading_day, phase)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_phase_approvals_expires
            ON live_phase_approvals(expires_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS live_readiness_runs (
                readiness_id TEXT PRIMARY KEY,
                trading_day TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                phase TEXT NOT NULL,
                status TEXT NOT NULL,
                passed INTEGER NOT NULL,
                token_refresh_ok INTEGER NOT NULL,
                ws_recovery_ok INTEGER NOT NULL,
                account_snapshot_ok INTEGER NOT NULL,
                market_status_ok INTEGER NOT NULL,
                kill_switch_ok INTEGER NOT NULL,
                database_ok INTEGER NOT NULL,
                checks_json TEXT NOT NULL,
                report_path TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_live_readiness_runs_day_phase
            ON live_readiness_runs(trading_day, phase)
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
        preferred_mode = select_sqlite_journal_mode(self.database_path)
        fallback_modes = (
            preferred_mode,
            *[mode for mode in SQLITE_JOURNAL_MODE_FALLBACKS if mode != preferred_mode],
        )
        last_error: sqlite3.OperationalError | None = None
        for index, journal_mode in enumerate(fallback_modes):
            try:
                active_mode = self._initialize_schema_with_journal_mode(statements, journal_mode)
            except sqlite3.OperationalError as exc:
                last_error = exc
                next_mode = fallback_modes[index + 1] if index + 1 < len(fallback_modes) else None
                if next_mode is None:
                    logger.error(
                        "SQLite startup failed with all journal modes for database=%s last_mode=%s error=%s",
                        self.database_path,
                        journal_mode,
                        exc,
                    )
                    raise
                logger.warning(
                    "SQLite startup journal_mode=%s failed for database=%s error=%s; falling back to %s",
                    journal_mode,
                    self.database_path,
                    exc,
                    next_mode,
                )
                continue

            self.sqlite_journal_mode = active_mode
            logger.info(
                "SQLite startup using journal_mode=%s for database=%s",
                active_mode,
                self.database_path,
            )
            return

        if last_error is not None:
            raise last_error

    def _initialize_schema_with_journal_mode(self, statements: list[str], journal_mode: str) -> str:
        connection = self._connect()
        try:
            active_mode = self._apply_journal_mode(connection, journal_mode)
            connection.execute("PRAGMA synchronous=NORMAL")
            for statement in statements:
                connection.execute(statement)
            self._ensure_column(connection, "paper_positions", "opened_at", "TEXT")
            self._ensure_column(connection, "paper_orders", "prediction_id", "TEXT")
            self._ensure_column(connection, "paper_orders", "signal_id", "TEXT")
            self._ensure_column(connection, "paper_orders", "target_id", "TEXT")
            self._ensure_column(connection, "serving_predictions", "training_run_id", "TEXT")
            self._ensure_column(connection, "serving_predictions", "artifact_id", "TEXT")
            self._ensure_column(connection, "serving_predictions", "artifact_sha256", "TEXT")
            connection.commit()
            return active_mode
        except sqlite3.OperationalError:
            with suppress(sqlite3.Error):
                connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _apply_journal_mode(connection: sqlite3.Connection, journal_mode: str) -> str:
        normalized_mode = journal_mode.strip().upper()
        if normalized_mode not in set(SQLITE_JOURNAL_MODE_FALLBACKS):
            raise ValueError(f"Unsupported sqlite journal mode: {journal_mode}")
        row = connection.execute(f"PRAGMA journal_mode={normalized_mode}").fetchone()
        active_mode = str(row[0]).upper() if row else normalized_mode
        if active_mode != normalized_mode:
            raise sqlite3.OperationalError(
                f"requested journal_mode={normalized_mode} but sqlite activated {active_mode}"
            )
        return active_mode

    def checkpoint_wal(self, mode: str = "PASSIVE") -> None:
        normalized_mode = mode.strip().upper()
        if normalized_mode not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
            raise ValueError(f"Unsupported wal_checkpoint mode: {mode}")
        with closing(self._connect()) as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
            current_mode = str(row[0]).lower() if row else ""
            if current_mode != "wal":
                return
            connection.execute(f"PRAGMA wal_checkpoint({normalized_mode})")

    def backup_database(self, backup_path: Path) -> Path:
        """Create a consistent SQLite backup, including committed WAL pages."""
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path.exists():
            backup_path.unlink()
        with closing(self._connect()) as source, closing(sqlite3.connect(backup_path)) as target:
            source.backup(target)
        return backup_path


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
                with closing(self._connect()) as connection:
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
                with closing(self._connect()) as connection:
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

    def _run_write_query_rowcount(self, query: str, params: tuple[Any, ...] = ()) -> int:
        last_error: sqlite3.OperationalError | None = None
        for attempt, delay_seconds in enumerate(self.write_retry_delays):
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            try:
                with closing(self._connect()) as connection:
                    cursor = connection.execute(query, params)
                    connection.commit()
                    return int(cursor.rowcount or 0)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                last_error = exc
                if attempt == len(self.write_retry_delays) - 1:
                    raise
        if last_error is not None:
            raise last_error
        return 0

    @staticmethod
    def _is_missing_table_error(exc: sqlite3.OperationalError, table_name: str) -> bool:
        return f"no such table: {table_name.lower()}" in str(exc).lower()

    def _run_safe_read_query(
        self,
        query: str,
        params: tuple[Any, ...] = (),
        *,
        single: bool = False,
        missing_tables: tuple[str, ...] = (),
    ) -> sqlite3.Row | list[sqlite3.Row] | None:
        try:
            return self._run_read_query(query, params, single=single)
        except sqlite3.OperationalError as exc:
            if missing_tables and any(self._is_missing_table_error(exc, table_name) for table_name in missing_tables):
                return None if single else []
            raise

    def insert_market_tick(self, event: MarketTickEvent) -> None:
        self._run_write_query(
            "INSERT INTO raw_market_ticks(symbol, event_time, price, volume, source) VALUES (?, ?, ?, ?, ?)",
            (event.symbol, self._dt(event.event_time), event.price, event.volume, event.source),
        )

    def insert_market_ticks_many(self, events: list[MarketTickEvent]) -> None:
        if not events:
            return
        self._run_write_many(
            "INSERT INTO raw_market_ticks(symbol, event_time, price, volume, source) VALUES (?, ?, ?, ?, ?)",
            [
                (event.symbol, self._dt(event.event_time), event.price, event.volume, event.source)
                for event in events
            ],
        )

    def insert_orderbook_snapshot(self, event: OrderbookSnapshot) -> None:
        self._run_write_query(
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

    def insert_orderbook_snapshots_many(self, events: list[OrderbookSnapshot]) -> None:
        self._run_write_many(
            """
            INSERT INTO raw_orderbook_ticks(symbol, event_time, bid_price, ask_price, bid_size, ask_size, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    event.symbol,
                    self._dt(event.event_time),
                    event.bid_price,
                    event.ask_price,
                    event.bid_size,
                    event.ask_size,
                    event.source,
                )
                for event in events
            ],
        )

    def upsert_minute_bar(self, bar: MinuteBar) -> None:
        self._run_write_query(
            """
            INSERT OR REPLACE INTO curated_minute_bars(symbol, bar_time, open, high, low, close, volume, trade_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (bar.symbol, self._dt(bar.bar_time), bar.open, bar.high, bar.low, bar.close, bar.volume, bar.trade_count),
        )

    def upsert_minute_bars_many(self, bars: list[MinuteBar]) -> None:
        self._run_write_many(
            """
            INSERT OR REPLACE INTO curated_minute_bars(symbol, bar_time, open, high, low, close, volume, trade_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    bar.symbol,
                    self._dt(bar.bar_time),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.trade_count,
                )
                for bar in bars
            ],
        )

    def delete_raw_source_rows(
        self,
        table_name: str,
        *,
        source: str,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        if table_name not in {"raw_market_ticks", "raw_orderbook_ticks"}:
            raise ValueError(f"Unsupported raw table for source cleanup: {table_name}")
        self._run_write_query(
            f"""
            DELETE FROM {table_name}
            WHERE source = ?
              AND symbol = ?
              AND event_time >= ?
              AND event_time <= ?
            """,
            (source, symbol, self._dt(start_time), self._dt(end_time)),
        )

    def upsert_feature_snapshot(self, snapshot: FeatureSnapshot) -> None:
        self._run_write_query(
            """
            INSERT OR REPLACE INTO feature_model_inputs(symbol, event_time, feature_set_version, values_json)
            VALUES (?, ?, ?, ?)
            """,
            (snapshot.symbol, self._dt(snapshot.event_time), snapshot.feature_set_version, self._json(snapshot.values)),
        )

    def upsert_feature_snapshots_many(self, snapshots: list[FeatureSnapshot]) -> None:
        self._run_write_many(
            """
            INSERT OR REPLACE INTO feature_model_inputs(symbol, event_time, feature_set_version, values_json)
            VALUES (?, ?, ?, ?)
            """,
            [
                (snapshot.symbol, self._dt(snapshot.event_time), snapshot.feature_set_version, self._json(snapshot.values))
                for snapshot in snapshots
            ],
        )

    def upsert_feature_label(self, label: FeatureLabel) -> None:
        self._run_write_query(
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

    def upsert_feature_labels_many(self, labels: list[FeatureLabel]) -> None:
        self._run_write_many(
            """
            INSERT OR REPLACE INTO feature_labels(symbol, event_time, horizon_min, label, threshold_pct, future_return_pct)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    label.symbol,
                    self._dt(label.event_time),
                    label.horizon_min,
                    label.label,
                    label.threshold_pct,
                    label.future_return_pct,
                )
                for label in labels
            ],
        )

    def insert_prediction(self, prediction: Prediction) -> None:
        self._run_write_query(
            """
            INSERT OR REPLACE INTO serving_predictions(
                prediction_id, symbol, event_time, horizon_min, model_version,
                probability_up, probability_flat, probability_down,
                training_run_id, artifact_id, artifact_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                prediction.training_run_id,
                prediction.artifact_id,
                prediction.artifact_sha256,
            ),
        )

    def insert_trade_signal(self, signal: TradeSignal) -> None:
        self._run_write_query(
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

    def insert_target_position(self, target: TargetPosition) -> None:
        self._run_write_query(
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

    def insert_serving_decision(self, decision: ServingDecision) -> None:
        self._run_write_query(
            """
            INSERT OR REPLACE INTO serving_decision_ledger(
                decision_id, symbol, event_time, horizon_min,
                active_prediction_id, active_model_version,
                active_training_run_id, active_artifact_id, active_artifact_sha256,
                signal_id, signal_side, signal_allowed, signal_confidence, signal_reason,
                time_gate_allowed, time_gate_reason, spread_gate_allowed, spread_gate_reason,
                target_id, target_qty, target_notional,
                cash_balance_before, open_positions_before, symbol_position_qty_before,
                pending_order_before, execution_enabled, decision_stage, decision_reason,
                shadow_predictions_json, order_id, order_status, fill_id
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                decision.decision_id,
                decision.symbol,
                self._dt(decision.event_time),
                decision.horizon_min,
                decision.active_prediction_id,
                decision.active_model_version,
                decision.active_training_run_id,
                decision.active_artifact_id,
                decision.active_artifact_sha256,
                decision.signal_id,
                decision.signal_side,
                int(decision.signal_allowed),
                decision.signal_confidence,
                decision.signal_reason,
                int(decision.time_gate_allowed),
                decision.time_gate_reason,
                int(decision.spread_gate_allowed),
                decision.spread_gate_reason,
                decision.target_id,
                decision.target_qty,
                decision.target_notional,
                decision.cash_balance_before,
                decision.open_positions_before,
                decision.symbol_position_qty_before,
                int(decision.pending_order_before),
                int(decision.execution_enabled),
                decision.decision_stage,
                decision.decision_reason,
                json.dumps(decision.shadow_predictions, ensure_ascii=False, sort_keys=True),
                decision.order_id,
                decision.order_status,
                decision.fill_id,
            ),
        )

    def insert_paper_order(self, order: PaperOrder) -> None:
        self._run_write_query(
            """
            INSERT OR REPLACE INTO paper_orders(
                order_id, symbol, event_time, side, qty, limit_price, status,
                prediction_id, signal_id, target_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.order_id,
                order.symbol,
                self._dt(order.event_time),
                order.side,
                order.qty,
                order.limit_price,
                order.status,
                order.prediction_id,
                order.signal_id,
                order.target_id,
            ),
        )

    def insert_order_event(self, event: OrderEvent) -> None:
        self._run_write_query(
            "INSERT OR REPLACE INTO paper_order_events(order_event_id, order_id, event_time, event_type, detail) VALUES (?, ?, ?, ?, ?)",
            (event.order_event_id, event.order_id, self._dt(event.event_time), event.event_type, event.detail),
        )

    def insert_fill(self, fill: Fill) -> None:
        self._run_write_query(
            """
            INSERT OR REPLACE INTO paper_fills(fill_id, order_id, event_time, fill_price, fill_qty, commission, tax)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (fill.fill_id, fill.order_id, self._dt(fill.event_time), fill.fill_price, fill.fill_qty, fill.commission, fill.tax),
        )

    def upsert_paper_position(self, position: PaperPosition) -> None:
        self._run_write_query(
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

    def insert_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        self._run_write_query(
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

    def insert_broker_order_submission(self, submission: BrokerOrderSubmission) -> None:
        self._run_write_query(
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


    def insert_broker_order_status_snapshot(self, snapshot: BrokerOrderStatusSnapshot) -> None:
        self._run_write_query(
            """
            INSERT OR REPLACE INTO broker_paper_order_status_snapshots(
                sync_id, local_order_id, broker_mode, symbol, synced_at, order_date, side, order_qty,
                filled_qty, remaining_qty, avg_fill_price, status, broker_order_no, broker_branch_no,
                reject_qty, cancel_confirm_qty, cancel_yn, matched, applied_fill_qty, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.sync_id,
                snapshot.local_order_id,
                snapshot.broker_mode,
                snapshot.symbol,
                self._dt(snapshot.synced_at),
                snapshot.order_date,
                snapshot.side,
                snapshot.order_qty,
                snapshot.filled_qty,
                snapshot.remaining_qty,
                snapshot.avg_fill_price,
                snapshot.status,
                snapshot.broker_order_no,
                snapshot.broker_branch_no,
                snapshot.reject_qty,
                snapshot.cancel_confirm_qty,
                int(snapshot.cancel_yn),
                int(snapshot.matched),
                snapshot.applied_fill_qty,
                self._json(snapshot.detail),
            ),
        )

    def insert_market_status_snapshot(self, snapshot: MarketStatusSnapshot) -> None:
        self._run_write_query(
            """
            INSERT INTO market_status_snapshots(
                snapshot_id, trading_day, created_at, source, symbol_set_hash, status_json, stale_after
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.trading_day,
                self._dt(snapshot.created_at),
                snapshot.source,
                snapshot.symbol_set_hash,
                self._json(snapshot.status_json),
                self._dt(snapshot.stale_after),
            ),
        )

    def insert_live_order(self, order: LiveOrder) -> None:
        self._run_write_query(
            """
            INSERT INTO live_orders(
                order_id, idempotency_key, trading_day, phase, symbol, side, qty, filled_qty,
                remaining_qty, order_type, limit_price, avg_fill_price, status, prediction_id, signal_id,
                target_id, gate_decision_id, market_status_snapshot_id, model_version, rule_version,
                broker_order_no, broker_branch_no, reject_reason, cancel_reason, parent_order_id,
                created_at, submitted_at, last_synced_at, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.order_id,
                order.idempotency_key,
                order.trading_day,
                order.phase,
                order.symbol,
                order.side,
                order.qty,
                order.filled_qty,
                order.remaining_qty,
                order.order_type,
                order.limit_price,
                order.avg_fill_price,
                order.status,
                order.prediction_id,
                order.signal_id,
                order.target_id,
                order.gate_decision_id,
                order.market_status_snapshot_id,
                order.model_version,
                order.rule_version,
                order.broker_order_no,
                order.broker_branch_no,
                order.reject_reason,
                order.cancel_reason,
                order.parent_order_id,
                self._dt(order.created_at),
                self._dt(order.submitted_at) if order.submitted_at else None,
                self._dt(order.last_synced_at) if order.last_synced_at else None,
                self._json(order.detail_json),
            ),
        )

    def insert_live_order_event(self, event: LiveOrderEvent) -> None:
        self._run_write_query(
            """
            INSERT INTO live_order_events(
                order_event_id, order_id, event_time, from_status, to_status, event_type, actor, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.order_event_id,
                event.order_id,
                self._dt(event.event_time),
                event.from_status,
                event.to_status,
                event.event_type,
                event.actor,
                self._json(event.detail_json),
            ),
        )

    def fetch_live_order(self, order_id: str) -> sqlite3.Row | None:
        row = self._run_safe_read_query(
            "SELECT * FROM live_orders WHERE order_id = ?",
            (order_id,),
            single=True,
            missing_tables=("live_orders",),
        )
        return row if isinstance(row, sqlite3.Row) else None

    def fetch_live_order_by_idempotency_key(self, idempotency_key: str) -> sqlite3.Row | None:
        row = self._run_safe_read_query(
            "SELECT * FROM live_orders WHERE idempotency_key = ?",
            (idempotency_key,),
            single=True,
            missing_tables=("live_orders",),
        )
        return row if isinstance(row, sqlite3.Row) else None

    def update_live_order_transition(
        self,
        *,
        order_id: str,
        status: str,
        filled_qty: int | None = None,
        remaining_qty: int | None = None,
        avg_fill_price: float | None = None,
        broker_order_no: str,
        broker_branch_no: str,
        reject_reason: str | None,
        cancel_reason: str | None,
        submitted_at: datetime | None,
        last_synced_at: datetime | None,
        detail_json: dict[str, Any],
    ) -> None:
        self._run_write_query(
            """
            UPDATE live_orders
            SET status = ?,
                filled_qty = COALESCE(?, filled_qty),
                remaining_qty = COALESCE(?, remaining_qty),
                avg_fill_price = COALESCE(?, avg_fill_price),
                broker_order_no = ?,
                broker_branch_no = ?,
                reject_reason = ?,
                cancel_reason = ?,
                submitted_at = ?,
                last_synced_at = ?,
                detail_json = ?
            WHERE order_id = ?
            """,
            (
                status,
                filled_qty,
                remaining_qty,
                avg_fill_price,
                broker_order_no,
                broker_branch_no,
                reject_reason,
                cancel_reason,
                self._dt(submitted_at) if submitted_at else None,
                self._dt(last_synced_at) if last_synced_at else None,
                self._json(detail_json),
                order_id,
            ),
        )

    def insert_live_fill(self, fill: LiveFill) -> None:
        self._run_write_query(
            """
            INSERT INTO live_fills(
                fill_id, order_id, broker_order_no, broker_branch_no, symbol, trading_day,
                event_time, side, fill_qty, fill_price, commission, tax, fee, settlement_day, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._live_fill_values(fill),
        )

    def insert_live_fill_if_absent(self, fill: LiveFill) -> bool:
        rowcount = self._run_write_query_rowcount(
            """
            INSERT OR IGNORE INTO live_fills(
                fill_id, order_id, broker_order_no, broker_branch_no, symbol, trading_day,
                event_time, side, fill_qty, fill_price, commission, tax, fee, settlement_day, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._live_fill_values(fill),
        )
        return rowcount > 0

    def fetch_live_fill(self, fill_id: str) -> sqlite3.Row | None:
        row = self._run_safe_read_query(
            "SELECT * FROM live_fills WHERE fill_id = ?",
            (fill_id,),
            single=True,
            missing_tables=("live_fills",),
        )
        return row if isinstance(row, sqlite3.Row) else None

    def fetch_live_fill_totals(self, order_id: str) -> tuple[int, float]:
        row = self._run_safe_read_query(
            """
            SELECT
                COALESCE(SUM(fill_qty), 0) AS total_qty,
                COALESCE(SUM(fill_qty * fill_price), 0.0) AS total_notional
            FROM live_fills
            WHERE order_id = ?
            """,
            (order_id,),
            single=True,
            missing_tables=("live_fills",),
        )
        if not isinstance(row, sqlite3.Row):
            return 0, 0.0
        return int(row["total_qty"] or 0), float(row["total_notional"] or 0.0)

    def sum_live_fill_qty(self, order_id: str) -> int:
        total_qty, _ = self.fetch_live_fill_totals(order_id)
        return total_qty

    def fetch_live_fills_for_trading_day(self, trading_day: str) -> list[sqlite3.Row]:
        rows = self._run_safe_read_query(
            """
            SELECT *
            FROM live_fills
            WHERE trading_day = ?
            ORDER BY event_time ASC, fill_id ASC
            """,
            (trading_day,),
            missing_tables=("live_fills",),
        )
        return list(rows) if isinstance(rows, list) else []

    @staticmethod
    def _live_fill_values(fill: LiveFill) -> tuple[Any, ...]:
        return (
            fill.fill_id,
            fill.order_id,
            fill.broker_order_no,
            fill.broker_branch_no,
            fill.symbol,
            fill.trading_day,
            SQLiteRuntimeStore._dt(fill.event_time),
            fill.side,
            fill.fill_qty,
            fill.fill_price,
            fill.commission,
            fill.tax,
            fill.fee,
            fill.settlement_day,
            SQLiteRuntimeStore._json(fill.detail_json),
        )

    def upsert_live_position(self, position: LivePosition) -> None:
        self._run_write_query(
            """
            INSERT OR REPLACE INTO live_positions(
                symbol, trading_day, opened_at, updated_at, qty, avg_price, last_price, market_value,
                cost_basis, realized_pnl, unrealized_pnl, day_realized_pnl, broker_qty, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position.symbol,
                position.trading_day,
                self._dt(position.opened_at) if position.opened_at else None,
                self._dt(position.updated_at),
                position.qty,
                position.avg_price,
                position.last_price,
                position.market_value,
                position.cost_basis,
                position.realized_pnl,
                position.unrealized_pnl,
                position.day_realized_pnl,
                position.broker_qty,
                self._json(position.detail_json),
            ),
        )

    def insert_live_portfolio_snapshot(self, snapshot: LivePortfolioSnapshot) -> None:
        self._run_write_query(
            """
            INSERT INTO live_portfolio_snapshots(
                snapshot_id, trading_day, event_time, cash_balance, available_cash, unsettled_cash,
                gross_market_value, net_liquidation_value, realized_pnl, unrealized_pnl, daily_pnl,
                open_positions, margin_requirement, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.trading_day,
                self._dt(snapshot.event_time),
                snapshot.cash_balance,
                snapshot.available_cash,
                snapshot.unsettled_cash,
                snapshot.gross_market_value,
                snapshot.net_liquidation_value,
                snapshot.realized_pnl,
                snapshot.unrealized_pnl,
                snapshot.daily_pnl,
                snapshot.open_positions,
                snapshot.margin_requirement,
                self._json(snapshot.detail_json),
            ),
        )

    def insert_live_audit_event(self, event: LiveAuditEvent) -> None:
        self._run_write_query(
            """
            INSERT INTO ops_live_audit_events(
                audit_event_id, event_time, trading_day, event_type, actor, symbol, order_id,
                prediction_id, signal_id, gate_decision_id, rule_version, model_version, data_snapshot_id,
                previous_hash, event_hash, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.audit_event_id,
                self._dt(event.event_time),
                event.trading_day,
                event.event_type,
                event.actor,
                event.symbol,
                event.order_id,
                event.prediction_id,
                event.signal_id,
                event.gate_decision_id,
                event.rule_version,
                event.model_version,
                event.data_snapshot_id,
                event.previous_hash,
                event.event_hash,
                self._json(event.detail_json),
            ),
        )

    def fetch_live_audit_events(self, trading_day: str | None = None) -> list[sqlite3.Row]:
        query = """
            SELECT *
            FROM ops_live_audit_events
        """
        params: tuple[Any, ...] = ()
        if trading_day:
            query += " WHERE trading_day = ?"
            params = (trading_day,)
        query += " ORDER BY event_time ASC, audit_event_id ASC"
        rows = self._run_safe_read_query(query, params, missing_tables=("ops_live_audit_events",))
        return list(rows) if isinstance(rows, list) else []

    def insert_live_phase_approval(self, approval: LivePhaseApproval) -> None:
        self._run_write_query(
            """
            INSERT INTO live_phase_approvals(
                approval_id, phase, trading_day, approved_at, approved_by, expires_at, scope,
                max_symbols, max_parent_orders, max_notional, daily_loss_limit_pct,
                per_symbol_loss_limit_pct, slippage_budget_bps, approval_hash, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval.approval_id,
                approval.phase,
                approval.trading_day,
                self._dt(approval.approved_at),
                approval.approved_by,
                self._dt(approval.expires_at),
                approval.scope,
                approval.max_symbols,
                approval.max_parent_orders,
                approval.max_notional,
                approval.daily_loss_limit_pct,
                approval.per_symbol_loss_limit_pct,
                approval.slippage_budget_bps,
                approval.approval_hash,
                self._json(approval.detail_json),
            ),
        )

    def fetch_active_live_phase_approvals(
        self,
        *,
        phase: str,
        trading_day: str,
        as_of: datetime,
    ) -> list[sqlite3.Row]:
        rows = self._run_safe_read_query(
            """
            SELECT *
            FROM live_phase_approvals
            WHERE phase = ?
              AND trading_day = ?
              AND approved_at <= ?
              AND expires_at >= ?
            ORDER BY approved_at DESC
            """,
            (phase, trading_day, self._dt(as_of), self._dt(as_of)),
            missing_tables=("live_phase_approvals",),
        )
        return list(rows) if isinstance(rows, list) else []

    def insert_live_readiness_run(self, run: LiveReadinessRun) -> None:
        self._run_write_query(
            """
            INSERT INTO live_readiness_runs(
                readiness_id, trading_day, checked_at, phase, status, passed, token_refresh_ok,
                ws_recovery_ok, account_snapshot_ok, market_status_ok, kill_switch_ok, database_ok,
                checks_json, report_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.readiness_id,
                run.trading_day,
                self._dt(run.checked_at),
                run.phase,
                run.status,
                int(run.passed),
                int(run.token_refresh_ok),
                int(run.ws_recovery_ok),
                int(run.account_snapshot_ok),
                int(run.market_status_ok),
                int(run.kill_switch_ok),
                int(run.database_ok),
                self._json(run.checks_json),
                run.report_path,
            ),
        )

    def fetch_open_live_orders(
        self,
        trading_day: str | None = None,
        statuses: tuple[str, ...] = LIVE_OPEN_ORDER_STATUSES,
    ) -> list[sqlite3.Row]:
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        query = f"""
            SELECT *
            FROM live_orders
            WHERE status IN ({placeholders})
        """
        params: tuple[Any, ...] = tuple(statuses)
        if trading_day:
            query += " AND trading_day = ?"
            params = (*params, trading_day)
        query += " ORDER BY created_at ASC"
        rows = self._run_safe_read_query(query, params, missing_tables=("live_orders",))
        return list(rows) if isinstance(rows, list) else []

    def fetch_live_orders_for_trading_day(self, trading_day: str) -> list[sqlite3.Row]:
        rows = self._run_safe_read_query(
            """
            SELECT *
            FROM live_orders
            WHERE trading_day = ?
            ORDER BY created_at ASC
            """,
            (trading_day,),
            missing_tables=("live_orders",),
        )
        return list(rows) if isinstance(rows, list) else []

    def update_paper_order_status(self, order_id: str, status: str) -> None:
        self._run_write_query(
            "UPDATE paper_orders SET status = ? WHERE order_id = ?",
            (status, order_id),
        )
    def insert_risk_event(self, event: RiskEvent) -> None:
        self._run_write_query(
            "INSERT OR REPLACE INTO ops_risk_events(risk_event_id, symbol, event_time, gate, detail) VALUES (?, ?, ?, ?, ?)",
            (event.risk_event_id, event.symbol, self._dt(event.event_time), event.gate, event.detail),
        )

    def insert_reconciliation_run(self, run: ReconciliationRun) -> None:
        self._run_write_query(
            "INSERT OR REPLACE INTO ops_reconciliation_runs(reconciliation_id, as_of, status, mismatch_count) VALUES (?, ?, ?, ?)",
            (run.reconciliation_id, self._dt(run.as_of), run.status, run.mismatch_count),
        )

    def insert_replay_run(self, run: ReplayRun) -> None:
        self._run_write_query(
            "INSERT OR REPLACE INTO ops_replay_runs(replay_id, as_of, status, drift_count) VALUES (?, ?, ?, ?)",
            (run.replay_id, self._dt(run.as_of), run.status, run.drift_count),
        )

    def insert_training_run(self, run: TrainingRun) -> None:
        self._run_write_query(
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

    def insert_model_evaluation(self, evaluation: ModelEvaluation) -> None:
        self._run_write_query(
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

    def fetch_market_ticks(self, symbol: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT symbol, event_time, price, volume, source FROM raw_market_ticks"
        params: tuple[Any, ...] = ()
        if symbol:
            query += " WHERE symbol = ?"
            params = (symbol,)
        query += " ORDER BY symbol, event_time"
        rows = self._run_safe_read_query(query, params, missing_tables=("raw_market_ticks",))
        return list(rows) if isinstance(rows, list) else []

    def fetch_orderbook_snapshots(
        self,
        symbol: str | None = None,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[sqlite3.Row]:
        query = "SELECT symbol, event_time, bid_price, ask_price, bid_size, ask_size, source FROM raw_orderbook_ticks"
        conditions: list[str] = []
        params: list[Any] = []
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if start_time is not None:
            conditions.append("event_time >= ?")
            params.append(self._dt(start_time))
        if end_time is not None:
            conditions.append("event_time <= ?")
            params.append(self._dt(end_time))
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY symbol, event_time"
        rows = self._run_safe_read_query(query, tuple(params), missing_tables=("raw_orderbook_ticks",))
        return list(rows) if isinstance(rows, list) else []

    def fetch_minute_bars(
        self,
        symbol: str | None = None,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[sqlite3.Row]:
        query = "SELECT symbol, bar_time, open, high, low, close, volume, trade_count FROM curated_minute_bars"
        conditions: list[str] = []
        params: list[Any] = []
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if start_time is not None:
            conditions.append("bar_time >= ?")
            params.append(self._dt(start_time))
        if end_time is not None:
            conditions.append("bar_time <= ?")
            params.append(self._dt(end_time))
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY symbol, bar_time"
        rows = self._run_safe_read_query(query, tuple(params), missing_tables=("curated_minute_bars",))
        return list(rows) if isinstance(rows, list) else []

    def fetch_minute_bars_with_market_sources(
        self,
        symbol: str | None = None,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[sqlite3.Row]:
        query = """
            SELECT
                bars.symbol,
                bars.bar_time,
                bars.open,
                bars.high,
                bars.low,
                bars.close,
                bars.volume,
                bars.trade_count,
                GROUP_CONCAT(DISTINCT lower(ticks.source)) AS market_sources
            FROM curated_minute_bars AS bars
            LEFT JOIN raw_market_ticks AS ticks
                ON ticks.symbol = bars.symbol
               AND ticks.event_time = bars.bar_time
        """
        conditions: list[str] = []
        params: list[Any] = []
        if symbol:
            conditions.append("bars.symbol = ?")
            params.append(symbol)
        if start_time is not None:
            conditions.append("bars.bar_time >= ?")
            params.append(self._dt(start_time))
        if end_time is not None:
            conditions.append("bars.bar_time <= ?")
            params.append(self._dt(end_time))
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += """
            GROUP BY
                bars.symbol,
                bars.bar_time,
                bars.open,
                bars.high,
                bars.low,
                bars.close,
                bars.volume,
                bars.trade_count
            ORDER BY bars.symbol, bars.bar_time
        """
        rows = self._run_safe_read_query(
            query,
            tuple(params),
            missing_tables=("curated_minute_bars", "raw_market_ticks"),
        )
        return list(rows) if isinstance(rows, list) else []

    def fetch_market_source_symbols(self, source: str) -> list[str]:
        query = """
            SELECT DISTINCT symbol
            FROM raw_market_ticks
            WHERE lower(source) = lower(?)
            ORDER BY symbol
        """
        rows = self._run_safe_read_query(query, (source,), missing_tables=("raw_market_ticks",))
        if not isinstance(rows, list):
            return []
        return [str(row["symbol"]) for row in rows]

    def fetch_market_source_trade_dates(self, source: str) -> list[str]:
        query = """
            SELECT DISTINCT substr(event_time, 1, 10) AS trade_date
            FROM raw_market_ticks
            WHERE lower(source) = lower(?)
            ORDER BY trade_date
        """
        rows = self._run_safe_read_query(query, (source,), missing_tables=("raw_market_ticks",))
        if not isinstance(rows, list):
            return []
        return [str(row["trade_date"]) for row in rows if row["trade_date"]]

    def fetch_minute_bars_for_market_source(self, source: str, symbol: str | None = None) -> list[sqlite3.Row]:
        query = """
            SELECT
                bars.symbol,
                bars.bar_time,
                bars.open,
                bars.high,
                bars.low,
                bars.close,
                bars.volume,
                bars.trade_count
            FROM curated_minute_bars AS bars
            WHERE EXISTS (
                SELECT 1
                FROM raw_market_ticks AS ticks
                WHERE ticks.symbol = bars.symbol
                  AND ticks.event_time = bars.bar_time
                  AND lower(ticks.source) = lower(?)
            )
        """
        params: tuple[Any, ...]
        if symbol:
            query += " AND bars.symbol = ?"
            params = (source, symbol)
        else:
            params = (source,)
        query += " ORDER BY bars.symbol, bars.bar_time"
        rows = self._run_safe_read_query(
            query,
            params,
            missing_tables=("curated_minute_bars", "raw_market_ticks"),
        )
        return list(rows) if isinstance(rows, list) else []

    def fetch_feature_rows(
        self,
        horizon_min: int,
        market_source: str | None = None,
        max_rows: int | None = None,
    ) -> list[sqlite3.Row]:
        query = """
            WITH orderbook_source_lookup AS (
                SELECT
                    symbol,
                    event_time,
                    GROUP_CONCAT(DISTINCT lower(source)) AS orderbook_sources
                FROM raw_orderbook_ticks
                GROUP BY symbol, event_time
            ),
            market_source_lookup AS (
                SELECT
                    symbol,
                    event_time,
                    GROUP_CONCAT(DISTINCT lower(source)) AS market_sources
                FROM raw_market_ticks
                GROUP BY symbol, event_time
            )
            SELECT
                inputs.symbol,
                inputs.event_time,
                inputs.feature_set_version,
                inputs.values_json,
                orderbook_source_lookup.orderbook_sources,
                market_source_lookup.market_sources,
                labels.horizon_min,
                labels.label,
                labels.threshold_pct,
                labels.future_return_pct
            FROM feature_model_inputs AS inputs
            INNER JOIN feature_labels AS labels
                ON inputs.symbol = labels.symbol
               AND inputs.event_time = labels.event_time
            LEFT JOIN orderbook_source_lookup
                ON orderbook_source_lookup.symbol = inputs.symbol
               AND orderbook_source_lookup.event_time = inputs.event_time
            LEFT JOIN market_source_lookup
                ON market_source_lookup.symbol = inputs.symbol
               AND market_source_lookup.event_time = inputs.event_time
            WHERE labels.horizon_min = ?
        """
        params: tuple[Any, ...] = (horizon_min,)
        if market_source:
            query += """
                AND EXISTS (
                    SELECT 1
                    FROM raw_market_ticks AS source_filter_ticks
                    WHERE source_filter_ticks.symbol = inputs.symbol
                      AND source_filter_ticks.event_time = inputs.event_time
                      AND lower(source_filter_ticks.source) = lower(?)
                )
            """
            params = (horizon_min, market_source)
        if max_rows is not None and max_rows > 0:
            query += " ORDER BY inputs.event_time DESC, inputs.symbol DESC LIMIT ?"
            params = (*params, int(max_rows))
        else:
            query += " ORDER BY inputs.symbol, inputs.event_time"
        rows = self._run_safe_read_query(
            query,
            params,
            missing_tables=("feature_model_inputs", "feature_labels"),
        )
        return list(rows) if isinstance(rows, list) else []

    def fetch_latest_row(self, table_name: str, order_by_column: str) -> sqlite3.Row | None:
        query = f"SELECT * FROM {table_name} ORDER BY {order_by_column} DESC, rowid DESC LIMIT 1"
        row = self._run_safe_read_query(query, single=True, missing_tables=(table_name,))
        return row if isinstance(row, sqlite3.Row) or row is None else None

    def fetch_all_rows(self, table_name: str, order_by_column: str) -> list[sqlite3.Row]:
        query = f"SELECT * FROM {table_name} ORDER BY {order_by_column}"
        rows = self._run_safe_read_query(query, missing_tables=(table_name,))
        return list(rows) if isinstance(rows, list) else []

    def fetch_rows_between(
        self,
        table_name: str,
        time_column: str,
        start_at: str,
        end_at: str,
        order_by_column: str,
    ) -> list[sqlite3.Row]:
        query = f"""
            SELECT *
            FROM {table_name}
            WHERE {time_column} >= ? AND {time_column} < ?
            ORDER BY {order_by_column}
        """
        rows = self._run_safe_read_query(query, (start_at, end_at), missing_tables=(table_name,))
        return list(rows) if isinstance(rows, list) else []

    def fetch_raw_symbol_minute_source_counts(
        self,
        table_name: str,
        *,
        sources: Iterable[str] | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
    ) -> list[sqlite3.Row]:
        if table_name not in {"raw_market_ticks", "raw_orderbook_ticks"}:
            raise ValueError(f"Unsupported raw table for minute counts: {table_name}")
        conditions: list[str] = []
        params_list: list[Any] = []
        if sources:
            normalized_sources = tuple(str(source).lower() for source in sources)
            placeholders = ", ".join("?" for _ in normalized_sources)
            conditions.append(f"source IN ({placeholders})")
            params_list.extend(normalized_sources)
        if start_at is not None:
            conditions.append("event_time >= ?")
            params_list.append(start_at)
        if end_at is not None:
            conditions.append("event_time < ?")
            params_list.append(end_at)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT
                symbol,
                substr(event_time, 1, 16) AS minute_key,
                source,
                MIN(event_time) AS sample_time,
                COUNT(*) AS row_count
            FROM {table_name}
            {where_clause}
            GROUP BY symbol, minute_key, source
            ORDER BY symbol, minute_key
        """
        rows = self._run_safe_read_query(query, tuple(params_list), missing_tables=(table_name,))
        return list(rows) if isinstance(rows, list) else []

    def fetch_recent_rows(self, table_name: str, order_by_column: str, limit: int = 10) -> list[sqlite3.Row]:
        query = f"SELECT * FROM {table_name} ORDER BY {order_by_column} DESC, rowid DESC LIMIT ?"
        rows = self._run_safe_read_query(query, (limit,), missing_tables=(table_name,))
        return list(rows) if isinstance(rows, list) else []


    def fetch_rows_by_column(self, table_name: str, column_name: str, value: Any, order_by_column: str) -> list[sqlite3.Row]:
        query = f"SELECT * FROM {table_name} WHERE {column_name} = ? ORDER BY {order_by_column}"
        rows = self._run_safe_read_query(query, (value,), missing_tables=(table_name,))
        return list(rows) if isinstance(rows, list) else []

    def fetch_latest_row_by_column(
        self,
        table_name: str,
        column_name: str,
        value: Any,
        order_by_column: str,
    ) -> sqlite3.Row | None:
        query = f"SELECT * FROM {table_name} WHERE {column_name} = ? ORDER BY {order_by_column} DESC, rowid DESC LIMIT 1"
        row = self._run_safe_read_query(query, (value,), single=True, missing_tables=(table_name,))
        return row if isinstance(row, sqlite3.Row) or row is None else None
    def count_rows(self, table_name: str) -> int:
        row = self._run_safe_read_query(
            f"SELECT COUNT(*) AS count FROM {table_name}",
            single=True,
            missing_tables=(table_name,),
        )
        if row is None:
            return 0
        return int(row["count"])

    def clear_tables(self, table_names: Iterable[str]) -> None:
        table_name_list = list(table_names)
        last_error: sqlite3.OperationalError | None = None
        for attempt, delay_seconds in enumerate(self.write_retry_delays):
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            try:
                with closing(self._connect()) as connection:
                    for table_name in table_name_list:
                        connection.execute(f"DELETE FROM {table_name}")
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

    def _run_write_many(self, query: str, params_list: list[tuple[Any, ...]]) -> None:
        if not params_list:
            return
        last_error: sqlite3.OperationalError | None = None
        for attempt, delay_seconds in enumerate(self.write_retry_delays):
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            try:
                with closing(self._connect()) as connection:
                    connection.executemany(query, params_list)
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
