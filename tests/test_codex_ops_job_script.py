import json
import subprocess
import unittest
from pathlib import Path

from app.storage.sqlite_store import SQLiteRuntimeStore


class CodexOpsJobScriptTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _work_dir(self) -> Path:
        return self._root() / ".tmp-tests" / "codex-ops-job-script"

    def _write_json(self, path: Path, payload: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def test_premarket_readiness_dry_run_writes_report_from_fixtures(self) -> None:
        root = self._root()
        work_dir = self._work_dir() / "ok"
        report_path = root / "runtime-data" / "reports" / "codex" / "ops" / "premarket-readiness" / "test-report.json"
        live_status = self._write_json(
            work_dir / "live.json",
            {
                "status": "stopped",
                "session_status": "weekend",
                "process_running": False,
                "env_file_exists": True,
                "credentials_ready_for_quotes": True,
            },
        )
        watchdog_status = self._write_json(
            work_dir / "watchdog.json",
            {
                "status": "running",
                "process_running": True,
                "market_session_status": "weekend",
                "live_runtime_should_run": False,
                "heartbeat_stale": False,
            },
        )
        dashboard_status = self._write_json(
            work_dir / "dashboard.json",
            {"status": "running", "process_running": True},
        )
        storage_state = self._write_json(
            work_dir / "storage.json",
            {"status": "planned", "apply": False},
        )
        database_path = work_dir / "dev.db"
        SQLiteRuntimeStore(database_path)

        result = subprocess.run(
            [
                "bash",
                "scripts/run_codex_ops_job.sh",
                "--job-type",
                "premarket-readiness",
                "--report-path",
                str(report_path),
                "--live-status-path",
                str(live_status),
                "--watchdog-status-path",
                str(watchdog_status),
                "--dashboard-status-path",
                str(dashboard_status),
                "--database-path",
                str(database_path),
                "--database-timeout-seconds",
                "1.5",
                "--storage-state-path",
                str(storage_state),
                "--disk-free-bytes",
                str(20 * 1024 * 1024 * 1024),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["job_type"], "premarket-readiness")
        self.assertEqual(payload["status"], "ok")
        self.assertIn("database", [item["key"] for item in payload["checks"]])
        database_check = next(item for item in payload["checks"] if item["key"] == "database")
        self.assertEqual(database_check["details"]["timeout_seconds"], 1.5)
        self.assertTrue(payload["dry_run"])
        self.assertTrue(payload["write_report_decision"]["allowed"])
        self.assertEqual(payload["blockers"], [])
        self.assertTrue(report_path.exists())
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["schema_version"], 1)

    def test_premarket_readiness_derives_live_window_from_preopen_session(self) -> None:
        root = self._root()
        work_dir = self._work_dir() / "preopen-race"
        report_path = root / "runtime-data" / "reports" / "codex" / "ops" / "premarket-readiness" / "test-preopen-race.json"
        live_status = self._write_json(
            work_dir / "live.json",
            {
                "status": "running",
                "session_status": "pre-open",
                "process_running": True,
                "env_file_exists": True,
                "credentials_ready_for_quotes": True,
            },
        )
        watchdog_status = self._write_json(
            work_dir / "watchdog.json",
            {
                "status": "running",
                "process_running": True,
                "market_session_status": "pre-open",
                "live_runtime_should_run": False,
                "heartbeat_stale": False,
            },
        )
        dashboard_status = self._write_json(
            work_dir / "dashboard.json",
            {"status": "running", "process_running": True},
        )
        storage_state = self._write_json(
            work_dir / "storage.json",
            {"status": "planned", "apply": False},
        )
        database_path = work_dir / "dev.db"
        SQLiteRuntimeStore(database_path)

        result = subprocess.run(
            [
                "bash",
                "scripts/run_codex_ops_job.sh",
                "--job-type",
                "premarket-readiness",
                "--report-path",
                str(report_path),
                "--live-status-path",
                str(live_status),
                "--watchdog-status-path",
                str(watchdog_status),
                "--dashboard-status-path",
                str(dashboard_status),
                "--database-path",
                str(database_path),
                "--database-timeout-seconds",
                "1.5",
                "--storage-state-path",
                str(storage_state),
                "--disk-free-bytes",
                str(20 * 1024 * 1024 * 1024),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["live_runtime_should_run"])
        live_runtime_check = next(item for item in payload["checks"] if item["key"] == "live_runtime")
        self.assertEqual(live_runtime_check["status"], "ok")

    def test_execute_mode_is_rejected(self) -> None:
        root = self._root()

        result = subprocess.run(
            ["bash", "scripts/run_codex_ops_job.sh", "--execute"],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dry-run only", result.stderr)

    def test_report_path_must_stay_inside_repository(self) -> None:
        root = self._root()

        result = subprocess.run(
            [
                "bash",
                "scripts/run_codex_ops_job.sh",
                "--report-path",
                "/tmp/codex-ops-outside-root.json",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("report_path must stay inside repository root", result.stderr)


if __name__ == "__main__":
    unittest.main()
