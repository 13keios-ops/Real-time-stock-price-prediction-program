import json
import subprocess
import unittest
from pathlib import Path


class StorageMigrationDryRunScriptTests(unittest.TestCase):
    def test_dry_run_initializes_live_tables_on_temp_copy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        work_dir = root / ".tmp-tests" / "storage-migration-dry-run-test"
        report_path = work_dir / "report.json"

        result = subprocess.run(
            [
                "bash",
                "scripts/run_storage_migration_dry_run.sh",
                "--source-db",
                str(work_dir / "missing-source.sqlite3"),
                "--work-dir",
                str(work_dir),
                "--report-path",
                str(report_path),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["source_db_exists"])
        self.assertEqual(payload["missing_tables"], [])
        self.assertEqual(payload["missing_indexes"], [])
        self.assertIn("live_fills", payload["required_tables"])
        self.assertIn("idx_live_readiness_runs_day_phase", payload["required_indexes"])
        self.assertTrue(report_path.exists())

        saved_payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(saved_payload["dry_run_db"], payload["dry_run_db"])

    def test_work_dir_must_stay_inside_repository(self) -> None:
        root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [
                "bash",
                "scripts/run_storage_migration_dry_run.sh",
                "--work-dir",
                "/tmp/storage-migration-dry-run-outside-root",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("work_dir must stay inside repository root", result.stderr)


if __name__ == "__main__":
    unittest.main()
