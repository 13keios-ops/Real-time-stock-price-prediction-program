import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
import unittest


class PostCloseMaintenanceScriptTests(unittest.TestCase):
    def test_quick_maintenance_skips_when_today_state_is_already_ok(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "post-close-maintenance-guard"
        state_path = runtime_root / "reports" / "ml-maintenance" / "state" / "latest-post-close-ml.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "maintenance_date": datetime.now().strftime("%Y-%m-%d"),
                    "horizon_min": 15,
                    "maintenance_scope": "quick",
                    "mode": "quick-live-train",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                "bash",
                "scripts/run_post_close_ml_maintenance.sh",
                "--quick",
                "--horizon-min",
                "15",
                "--runtime-data-dir",
                str(runtime_root),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("already ok for today; skipping", result.stderr)
        self.assertIn('"mode": "quick-live-train"', result.stdout)

    def test_quick_maintenance_skips_on_configured_holiday(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workspace = root / ".tmp-tests" / "post-close-maintenance-holiday-workspace"
        runtime_root = root / ".tmp-tests" / "post-close-maintenance-holiday-runtime"
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(runtime_root, ignore_errors=True)
        (workspace / "config").mkdir(parents=True, exist_ok=True)
        (workspace / "config" / "market_calendar.toml").write_text(
            "session_open = '09:00'\n"
            "session_close = '15:30'\n"
            f"holidays = ['{datetime.now().strftime('%Y-%m-%d')}']\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                "bash",
                "scripts/run_post_close_ml_maintenance.sh",
                "--quick",
                "--horizon-min",
                "15",
                "--workspace-root",
                str(workspace),
                "--runtime-data-dir",
                str(runtime_root),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(payload["skip_reason"], "market_session_holiday_no_post_close_maintenance")
        self.assertEqual(payload["tasks"], [])

    def test_quick_maintenance_refreshes_data_quality_diagnostics(self) -> None:
        script = Path("scripts/script_dispatch.sh").read_text(encoding="utf-8")

        expected_steps = [
            "check_local_setup.sh",
            "summarize_kis_live_data_quality.py --recent-days 10",
            "summarize_feature_source_drift.py",
            "summarize_kis_live_feature_diagnostics.py",
        ]
        expected_tasks = [
            "check-local-setup",
            "summarize-kis-live-data-quality",
            "summarize-feature-source-drift",
            "summarize-kis-live-feature-diagnostics",
        ]

        for step in expected_steps:
            with self.subTest(step=step):
                self.assertIn(step, script)
        for task in expected_tasks:
            with self.subTest(task=task):
                self.assertIn(f'"{task}"', script)

        self.assertIn("warning: local setup readiness check failed", script)
        self.assertIn("warning: KIS live data quality summary failed", script)
        self.assertIn("warning: feature source drift summary failed", script)
        self.assertIn("warning: KIS live feature diagnostics summary failed", script)


if __name__ == "__main__":
    unittest.main()
