import json
import sqlite3
import subprocess
import unittest
from pathlib import Path


class StorageMigrationApplyScriptTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _work_dir(self) -> Path:
        return self._root() / ".tmp-tests" / "storage-migration-apply-test"

    def _create_existing_database(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database_path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS sentinel (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT OR REPLACE INTO sentinel(id, value) VALUES ('keep', 'yes')")
            connection.commit()

    def test_plan_mode_does_not_mutate_database(self) -> None:
        root = self._root()
        work_dir = self._work_dir() / "plan"
        database_path = work_dir / "dev.sqlite3"
        report_path = work_dir / "report.json"
        self._create_existing_database(database_path)

        result = subprocess.run(
            [
                "bash",
                "scripts/apply_storage_migration.sh",
                "--database-path",
                str(database_path),
                "--report-path",
                str(report_path),
                "--skip-service-check",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "planned")
        with sqlite3.connect(database_path) as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'live_orders'"
            ).fetchall()
        self.assertEqual(rows, [])
        self.assertTrue(report_path.exists())

    def test_apply_migrates_existing_database_and_creates_backup(self) -> None:
        root = self._root()
        work_dir = self._work_dir() / "apply"
        database_path = work_dir / "dev.sqlite3"
        backup_dir = work_dir / "backups"
        report_path = work_dir / "report.json"
        self._create_existing_database(database_path)

        result = subprocess.run(
            [
                "bash",
                "scripts/apply_storage_migration.sh",
                "--database-path",
                str(database_path),
                "--backup-dir",
                str(backup_dir),
                "--report-path",
                str(report_path),
                "--skip-service-check",
                "--apply",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["missing_tables"], [])
        self.assertEqual(payload["missing_indexes"], [])
        self.assertEqual(payload["smoke_errors"], [])
        self.assertTrue(Path(payload["backup_path"]).exists())
        with sqlite3.connect(database_path) as connection:
            sentinel = connection.execute("SELECT value FROM sentinel WHERE id = 'keep'").fetchone()
            live_orders = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'live_orders'"
            ).fetchone()
            smoke_rows = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM market_status_snapshots WHERE snapshot_id = '__storage_migration_smoke__'),
                    (SELECT COUNT(*) FROM live_orders WHERE order_id = '__storage_migration_smoke__'),
                    (SELECT COUNT(*) FROM live_order_events WHERE order_id = '__storage_migration_smoke__'),
                    (SELECT COUNT(*) FROM live_fills WHERE order_id = '__storage_migration_smoke__'),
                    (SELECT COUNT(*) FROM live_positions WHERE symbol = '__SMOKE__'),
                    (SELECT COUNT(*) FROM live_portfolio_snapshots WHERE snapshot_id = '__storage_migration_smoke__'),
                    (SELECT COUNT(*) FROM ops_live_audit_events WHERE audit_event_id = '__storage_migration_smoke__'),
                    (SELECT COUNT(*) FROM live_phase_approvals WHERE approval_id = '__storage_migration_smoke__'),
                    (SELECT COUNT(*) FROM live_readiness_runs WHERE readiness_id = '__storage_migration_smoke__')
                """
            ).fetchone()
        self.assertEqual(sentinel[0], "yes")
        self.assertEqual(live_orders[0], "live_orders")
        self.assertEqual(smoke_rows, (0, 0, 0, 0, 0, 0, 0, 0, 0))

    def test_database_path_must_stay_inside_repository(self) -> None:
        root = self._root()

        result = subprocess.run(
            [
                "bash",
                "scripts/apply_storage_migration.sh",
                "--database-path",
                "/tmp/outside-storage-migration.sqlite3",
                "--skip-service-check",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("database_path must stay inside repository root", result.stderr)

    def test_runtime_database_cannot_skip_service_check(self) -> None:
        root = self._root()

        result = subprocess.run(
            [
                "bash",
                "scripts/apply_storage_migration.sh",
                "--skip-service-check",
                "--apply",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("skip_service_check is not allowed for runtime-data/dev.db", result.stderr)


if __name__ == "__main__":
    unittest.main()
