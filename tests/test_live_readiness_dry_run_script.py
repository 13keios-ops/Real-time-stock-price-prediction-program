import json
import sqlite3
import subprocess
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

from app.storage.sqlite_store import SQLiteRuntimeStore


class LiveReadinessDryRunScriptTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _work_dir(self) -> Path:
        return self._root() / ".tmp-tests" / "live-readiness-dry-run-script"

    def _write_json(self, path: Path, payload: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _premarket_report(self, path: Path) -> Path:
        return self._write_json(
            path,
            {
                "status": "ok",
                "report_path": "runtime-data/reports/codex/ops/premarket-readiness/latest.json",
                "warnings": [],
                "blockers": [],
                "checks": [
                    {"key": "kis_credentials", "status": "ok"},
                    {"key": "database", "status": "ok"},
                    {"key": "dashboard", "status": "ok"},
                    {"key": "storage_migration_state", "status": "ok"},
                    {"key": "disk_space", "status": "ok"},
                ],
            },
        )

    def test_dry_run_writes_live_readiness_report_from_fixtures(self) -> None:
        root = self._root()
        work_dir = self._work_dir() / "ok"
        premarket_path = self._premarket_report(work_dir / "premarket.json")
        fixture_path = self._write_json(
            work_dir / "fixture.json",
            {
                "token_refresh": "ok",
                "ws_recovery": "ok",
                "account_snapshot": "ok",
                "market_status": "ok",
                "system_clock": "ok",
                "kill_switch": "ok",
                "database": "ok",
                "disk_space": "ok",
                "dashboard": "ok",
                "storage_migration_state": "ok",
            },
        )
        report_path = work_dir / "readiness.json"

        result = subprocess.run(
            [
                "bash",
                "scripts/run_live_readiness_dry_run.sh",
                "--phase",
                "phase1_readonly",
                "--trading-day",
                "2026-05-16",
                "--premarket-report-path",
                str(premarket_path),
                "--fixture-path",
                str(fixture_path),
                "--report-path",
                str(report_path),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["job_type"], "live-readiness-fault-dry-run")
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["dry_run"])
        self.assertTrue(payload["readiness_run"]["passed"])
        self.assertTrue(report_path.exists())

    def test_missing_fixture_keeps_readiness_blocked(self) -> None:
        root = self._root()
        work_dir = self._work_dir() / "missing-fixture"
        premarket_path = self._premarket_report(work_dir / "premarket.json")
        report_path = work_dir / "readiness.json"

        result = subprocess.run(
            [
                "bash",
                "scripts/run_live_readiness_dry_run.sh",
                "--premarket-report-path",
                str(premarket_path),
                "--report-path",
                str(report_path),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["readiness_run"]["passed"])
        self.assertIn("ws_recovery_not_verified_by_fault_dry_run", payload["blocking_reasons"])
        self.assertIn("token_refresh_not_verified_by_fault_dry_run", payload["blocking_reasons"])
        self.assertIn("system_clock_not_verified_by_fault_dry_run", payload["blocking_reasons"])

    def test_system_clock_fixture_accepts_http_date_header_shape(self) -> None:
        root = self._root()
        work_dir = self._work_dir() / "system-clock-http-date"
        premarket_path = self._premarket_report(work_dir / "premarket.json")
        local_time = datetime.now(timezone.utc)
        reference_time = local_time - timedelta(seconds=1)
        fixture_path = self._write_json(
            work_dir / "fixture.json",
            {
                "token_refresh": "ok",
                "ws_recovery": "ok",
                "account_snapshot": "ok",
                "market_status": "ok",
                "system_clock": {
                    "local_time": local_time.isoformat(),
                    "http_date": format_datetime(reference_time, usegmt=True),
                    "reference_source": "kis_rest_http_date",
                },
                "kill_switch": "ok",
                "database": "ok",
                "disk_space": "ok",
                "dashboard": "ok",
                "storage_migration_state": "ok",
            },
        )
        report_path = work_dir / "readiness.json"

        result = subprocess.run(
            [
                "bash",
                "scripts/run_live_readiness_dry_run.sh",
                "--phase",
                "phase1_readonly",
                "--trading-day",
                "2026-05-16",
                "--premarket-report-path",
                str(premarket_path),
                "--fixture-path",
                str(fixture_path),
                "--report-path",
                str(report_path),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        system_clock = next(item for item in payload["fixture_checks"] if item["key"] == "system_clock")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(system_clock["status"], "ok")
        self.assertEqual(system_clock["details"]["source"], "kis_rest_http_date")
        self.assertGreaterEqual(system_clock["details"]["skew_seconds"], 1.0)
        self.assertLess(system_clock["details"]["skew_seconds"], 2.0)

    def test_system_clock_check_path_overrides_fixture_system_clock(self) -> None:
        root = self._root()
        work_dir = self._work_dir() / "system-clock-check-path"
        premarket_path = self._premarket_report(work_dir / "premarket.json")
        fixture_path = self._write_json(
            work_dir / "fixture.json",
            {
                "token_refresh": "ok",
                "ws_recovery": "ok",
                "account_snapshot": "ok",
                "market_status": "ok",
                "system_clock": "failed",
                "kill_switch": "ok",
                "database": "ok",
                "disk_space": "ok",
                "dashboard": "ok",
                "storage_migration_state": "ok",
            },
        )
        system_clock_check_path = self._write_json(
            work_dir / "system-clock-check.json",
            {
                "key": "system_clock",
                "status": "ok",
                "passed": True,
                "summary": "system clock evaluated from HTTP Date header",
                "details": {
                    "source": "kis_rest_http_date",
                    "skew_seconds": 1.0,
                    "max_skew_seconds": 2.0,
                    "local_time": datetime.now(timezone.utc).isoformat(),
                    "reference_time": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                    "blocking_reasons": [],
                },
            },
        )
        report_path = work_dir / "readiness.json"

        result = subprocess.run(
            [
                "bash",
                "scripts/run_live_readiness_dry_run.sh",
                "--phase",
                "phase1_readonly",
                "--trading-day",
                "2026-05-16",
                "--premarket-report-path",
                str(premarket_path),
                "--fixture-path",
                str(fixture_path),
                "--system-clock-check-path",
                str(system_clock_check_path),
                "--report-path",
                str(report_path),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        system_clock = next(item for item in payload["fixture_checks"] if item["key"] == "system_clock")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["system_clock_check_path"], str(system_clock_check_path.resolve()))
        self.assertEqual(system_clock["status"], "ok")
        self.assertEqual(system_clock["details"]["source"], "kis_rest_http_date")

    def test_system_clock_check_path_must_stay_inside_repository(self) -> None:
        root = self._root()

        result = subprocess.run(
            [
                "bash",
                "scripts/run_live_readiness_dry_run.sh",
                "--system-clock-check-path",
                "/tmp/system-clock-check.json",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("system_clock_check_path must stay inside repository root", result.stderr)

    def test_execute_mode_is_rejected(self) -> None:
        root = self._root()

        result = subprocess.run(
            ["bash", "scripts/run_live_readiness_dry_run.sh", "--execute"],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dry-run only", result.stderr)

    def test_paths_must_stay_inside_repository(self) -> None:
        root = self._root()

        result = subprocess.run(
            [
                "bash",
                "scripts/run_live_readiness_dry_run.sh",
                "--report-path",
                "/tmp/live-readiness-outside-root.json",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("report_path must stay inside repository root", result.stderr)

    def test_record_requires_explicit_database_path(self) -> None:
        root = self._root()

        result = subprocess.run(
            ["bash", "scripts/run_live_readiness_dry_run.sh", "--record"],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--record requires --database-path", result.stderr)

    def test_record_database_path_must_stay_inside_repository(self) -> None:
        root = self._root()

        result = subprocess.run(
            [
                "bash",
                "scripts/run_live_readiness_dry_run.sh",
                "--record",
                "--database-path",
                "/tmp/live-readiness-record.db",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("database_path must stay inside repository root", result.stderr)

    def test_record_database_path_must_already_exist(self) -> None:
        root = self._root()
        database_path = self._work_dir() / "missing-db" / str(uuid.uuid4()) / "dev.db"

        result = subprocess.run(
            [
                "bash",
                "scripts/run_live_readiness_dry_run.sh",
                "--record",
                "--database-path",
                str(database_path),
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("database_path must already exist for --record", result.stderr)

    def test_record_writes_readiness_run_to_existing_sqlite_db(self) -> None:
        root = self._root()
        work_dir = self._work_dir() / "record" / str(uuid.uuid4())
        premarket_path = self._premarket_report(work_dir / "premarket.json")
        fixture_path = self._write_json(
            work_dir / "fixture.json",
            {
                "token_refresh": "ok",
                "ws_recovery": "ok",
                "account_snapshot": "ok",
                "market_status": "ok",
                "system_clock": "ok",
                "kill_switch": "ok",
                "database": "ok",
                "disk_space": "ok",
                "dashboard": "ok",
                "storage_migration_state": "ok",
            },
        )
        report_path = work_dir / "readiness.json"
        database_path = work_dir / "dev.db"
        SQLiteRuntimeStore(database_path)

        result = subprocess.run(
            [
                "bash",
                "scripts/run_live_readiness_dry_run.sh",
                "--phase",
                "phase1_readonly",
                "--trading-day",
                "2026-05-16",
                "--premarket-report-path",
                str(premarket_path),
                "--fixture-path",
                str(fixture_path),
                "--report-path",
                str(report_path),
                "--record",
                "--database-path",
                str(database_path),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertTrue(payload["recorded"])
        self.assertTrue(payload["readiness_run"]["passed"])
        with sqlite3.connect(database_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM live_readiness_runs").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["phase"], "phase1_readonly")
        checks_json = json.loads(rows[0]["checks_json"])
        self.assertTrue(checks_json["checks"]["dashboard"])
        self.assertTrue(checks_json["checks"]["storage_migration_state"])
        self.assertTrue(checks_json["checks"]["system_clock"])


if __name__ == "__main__":
    unittest.main()
