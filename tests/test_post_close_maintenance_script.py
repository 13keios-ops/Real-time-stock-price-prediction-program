from pathlib import Path
import unittest


class PostCloseMaintenanceScriptTests(unittest.TestCase):
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
