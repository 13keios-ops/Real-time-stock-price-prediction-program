from pathlib import Path
import uuid
import unittest
from unittest.mock import patch

from app.storage.sqlite_store import SQLiteRuntimeStore


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


if __name__ == "__main__":
    unittest.main()
