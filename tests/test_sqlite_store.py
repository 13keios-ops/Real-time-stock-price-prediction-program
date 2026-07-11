from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid
import unittest
from unittest.mock import patch

from app.storage.contracts import PaperOrder, ServingDecision
from app.storage.sqlite_store import (
    SQLITE_JOURNAL_MODE_FALLBACKS,
    SQLiteRuntimeStore,
    select_sqlite_journal_mode,
)


class SQLiteRuntimeStoreTests(unittest.TestCase):
    def test_initialize_schema_can_be_skipped(self) -> None:
        root = Path(__file__).resolve().parents[1]
        database_path = root / ".tmp-tests" / "sqlite-store" / str(uuid.uuid4()) / "dev.db"

        with patch.object(SQLiteRuntimeStore, "_initialize_schema") as mocked_initialize:
            SQLiteRuntimeStore(database_path, initialize_schema=False)

        mocked_initialize.assert_not_called()

    def test_initialize_schema_runs_by_default(self) -> None:
        root = Path(__file__).resolve().parents[1]
        database_path = root / ".tmp-tests" / "sqlite-store" / str(uuid.uuid4()) / "dev.db"

        with patch.object(SQLiteRuntimeStore, "_initialize_schema") as mocked_initialize:
            SQLiteRuntimeStore(database_path)

        mocked_initialize.assert_called_once()

    def test_custom_retry_settings_are_applied(self) -> None:
        root = Path(__file__).resolve().parents[1]
        database_path = root / ".tmp-tests" / "sqlite-store" / str(uuid.uuid4()) / "dev.db"

        store = SQLiteRuntimeStore(
            database_path,
            initialize_schema=False,
            busy_timeout_ms=2000,
            read_retry_delays=(0.0, 0.05),
            write_retry_delays=(0.0, 0.1, 0.2),
        )

        self.assertEqual(store.busy_timeout_ms, 2000)
        self.assertEqual(store.read_retry_delays, (0.0, 0.05))
        self.assertEqual(store.write_retry_delays, (0.0, 0.1, 0.2))

    def test_journal_mode_fallback_order_matches_startup_priority(self) -> None:
        self.assertEqual(SQLITE_JOURNAL_MODE_FALLBACKS, ("WAL", "DELETE", "MEMORY"))

    def test_select_journal_mode_defaults_to_wal(self) -> None:
        self.assertEqual(select_sqlite_journal_mode(Path("dev.db")), "WAL")

    def test_initialize_schema_falls_back_to_memory_when_wal_and_delete_fail(self) -> None:
        root = Path(__file__).resolve().parents[1]
        database_path = root / ".tmp-tests" / "sqlite-store" / str(uuid.uuid4()) / "dev.db"

        with (
            patch.object(
                SQLiteRuntimeStore,
                "_initialize_schema_with_journal_mode",
                side_effect=[
                    sqlite3.OperationalError("wal failed"),
                    sqlite3.OperationalError("delete failed"),
                    "MEMORY",
                ],
            ) as mocked_initialize,
            self.assertLogs("app.storage.sqlite_store", level="INFO") as logs,
        ):
            store = SQLiteRuntimeStore(database_path)

        self.assertEqual(
            [call.args[1] for call in mocked_initialize.call_args_list],
            ["WAL", "DELETE", "MEMORY"],
        )
        self.assertEqual(store.sqlite_journal_mode, "MEMORY")
        self.assertTrue(any("journal_mode=MEMORY" in message for message in logs.output))

    def test_apply_journal_mode_returns_active_mode(self) -> None:
        class AppliedJournalConnection:
            def __init__(self) -> None:
                self.queries: list[str] = []

            def execute(self, query: str) -> object:
                self.queries.append(query)

                class Cursor:
                    @staticmethod
                    def fetchone() -> tuple[str]:
                        return ("memory",)

                return Cursor()

        connection = AppliedJournalConnection()

        active_mode = SQLiteRuntimeStore._apply_journal_mode(connection, "MEMORY")  # type: ignore[arg-type]

        self.assertEqual(active_mode, "MEMORY")
        self.assertEqual(connection.queries, ["PRAGMA journal_mode=MEMORY"])

    def test_backup_database_creates_a_copy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        tmp_root = root / ".tmp-tests" / "sqlite-store" / str(uuid.uuid4())
        database_path = tmp_root / "dev.db"
        backup_path = tmp_root / "backups" / "dev-backup.sqlite3"

        store = SQLiteRuntimeStore(database_path)
        store._run_write_query(
            "INSERT INTO paper_orders(order_id, symbol, event_time, side, qty, limit_price, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("order-1", "005930", "2026-04-17T09:00:00+09:00", "buy", 1, 70000.0, "submitted"),
        )

        created_path = store.backup_database(backup_path)
        backup_store = SQLiteRuntimeStore(created_path, initialize_schema=False)

        self.assertTrue(created_path.exists())
        self.assertEqual(backup_store.count_rows("paper_orders"), 1)

    def test_serving_decision_ledger_persists_context_and_shadow_lineage(self) -> None:
        root = Path(__file__).resolve().parents[1]
        database_path = root / ".tmp-tests" / "sqlite-store" / str(uuid.uuid4()) / "dev.db"
        store = SQLiteRuntimeStore(database_path)
        decision = ServingDecision(
            decision_id="decision-1",
            symbol="005930",
            event_time=datetime(2026, 7, 10, 9, 15, tzinfo=timezone.utc),
            horizon_min=15,
            active_prediction_id="pred-active",
            active_model_version="baseline-h15-v1",
            active_training_run_id="run-active",
            active_artifact_id="artifact-active",
            active_artifact_sha256="sha-active",
            signal_id="signal-1",
            signal_side="sell",
            signal_allowed=False,
            signal_confidence=0.6,
            signal_reason="long_only_policy",
            time_gate_allowed=True,
            time_gate_reason="within_window",
            spread_gate_allowed=True,
            spread_gate_reason="spread_ok",
            target_id="target-1",
            target_qty=0,
            target_notional=0.0,
            cash_balance_before=1_000_000.0,
            open_positions_before=1,
            symbol_position_qty_before=0,
            pending_order_before=False,
            execution_enabled=True,
            decision_stage="signal_blocked",
            decision_reason="long_only_policy",
            shadow_predictions=[
                {
                    "prediction_id": "pred-shadow",
                    "model_version": "lightgbm-h15-v1",
                    "training_run_id": "run-shadow",
                    "artifact_id": "artifact-shadow",
                    "artifact_sha256": "sha-shadow",
                }
            ],
        )

        store.insert_serving_decision(decision)
        row = store.fetch_latest_row("serving_decision_ledger", "event_time")

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["decision_id"], "decision-1")
        self.assertEqual(row["decision_stage"], "signal_blocked")
        self.assertEqual(int(row["time_gate_allowed"]), 1)
        self.assertIn("artifact-shadow", row["shadow_predictions_json"])
    def test_paper_order_lineage_ids_are_persisted(self) -> None:
        root = Path(__file__).resolve().parents[1]
        database_path = root / ".tmp-tests" / "sqlite-store" / str(uuid.uuid4()) / "dev.db"
        store = SQLiteRuntimeStore(database_path)

        store.insert_paper_order(
            PaperOrder(
                order_id="order-lineage-1",
                symbol="005930",
                event_time=datetime(2026, 6, 10, 9, 1, tzinfo=timezone.utc),
                side="buy",
                qty=1,
                limit_price=70000.0,
                status="submitted",
                prediction_id="pred-1",
                signal_id="signal-1",
                target_id="target-1",
            )
        )

        row = store.fetch_latest_row_by_column("paper_orders", "order_id", "order-lineage-1", "event_time")

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["prediction_id"], "pred-1")
        self.assertEqual(row["signal_id"], "signal-1")
        self.assertEqual(row["target_id"], "target-1")

    def test_fetch_latest_row_breaks_timestamp_ties_by_insert_order(self) -> None:
        root = Path(__file__).resolve().parents[1]
        database_path = root / ".tmp-tests" / "sqlite-store" / str(uuid.uuid4()) / "dev.db"
        store = SQLiteRuntimeStore(database_path)
        event_time = "2026-05-29T15:01:58+09:00"
        for index, cash_balance in enumerate((100.0, 200.0, 300.0), start=1):
            store._run_write_query(
                """
                INSERT INTO paper_portfolio_snapshots(
                    snapshot_id, event_time, cash_balance, gross_market_value,
                    net_liquidation_value, open_positions, realized_pnl, unrealized_pnl
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"snapshot-{index}",
                    event_time,
                    cash_balance,
                    0.0,
                    cash_balance,
                    index,
                    0.0,
                    0.0,
                ),
            )

        latest = store.fetch_latest_row("paper_portfolio_snapshots", "event_time")

        self.assertIsNotNone(latest)
        self.assertEqual(float(latest["cash_balance"]), 300.0)
        self.assertEqual(int(latest["open_positions"]), 3)

    def test_backup_database_uses_consistent_sqlite_snapshot_with_wal(self) -> None:
        root = Path(__file__).resolve().parents[1]
        tmp_root = root / ".tmp-tests" / "sqlite-store" / str(uuid.uuid4())
        database_path = tmp_root / "dev.db"
        backup_path = tmp_root / "backups" / "dev-backup.sqlite3"

        store = SQLiteRuntimeStore(database_path)
        with sqlite3.connect(database_path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE wal_marker (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO wal_marker(id, value) VALUES ('committed', 'yes')")
            connection.commit()

        created_path = store.backup_database(backup_path)
        with sqlite3.connect(created_path) as backup_connection:
            row = backup_connection.execute("SELECT value FROM wal_marker WHERE id = 'committed'").fetchone()

        self.assertEqual(row, ("yes",))


if __name__ == "__main__":
    unittest.main()
