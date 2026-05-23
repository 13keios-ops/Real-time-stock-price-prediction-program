import json
import subprocess
import unittest
from datetime import datetime
from pathlib import Path


class PostCloseLabelRefreshScriptTests(unittest.TestCase):
    def test_label_refresh_skips_when_today_state_is_already_ok(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "post-close-label-refresh-guard"
        state_path = runtime_root / "reports" / "ml-maintenance" / "state" / "latest-post-close-label-refresh.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "maintenance_date": datetime.now().strftime("%Y-%m-%d"),
                    "recent_days": 10,
                    "skipped_feature_label_build": False,
                    "mode": "post-close-label-refresh-live-db",
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
                "scripts/run_post_close_label_refresh.sh",
                "--recent-days",
                "10",
                "--runtime-data-dir",
                str(runtime_root),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("already ok for today; skipping", result.stderr)
        self.assertIn('"mode": "post-close-label-refresh-live-db"', result.stdout)

    def test_dry_run_lists_label_refresh_steps(self) -> None:
        root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            ["bash", "scripts/run_post_close_label_refresh.sh", "--dry-run"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        expected_steps = [
            "python -m app --build-feature-dataset",
            "python scripts/summarize_kis_live_data_quality.py --recent-days 10",
            "python scripts/summarize_feature_source_drift.py",
            "python scripts/summarize_kis_live_feature_diagnostics.py",
            "python -m app --build-runtime-report",
            "python -m app --build-dashboard",
        ]
        for step in expected_steps:
            with self.subTest(step=step):
                self.assertIn(step, result.stdout)

    def test_skip_build_omits_feature_label_rebuild(self) -> None:
        root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            ["bash", "scripts/run_post_close_label_refresh.sh", "--dry-run", "--skip-build"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertNotIn("python -m app --build-feature-dataset", result.stdout)
        self.assertIn("python -m app --build-dashboard", result.stdout)


if __name__ == "__main__":
    unittest.main()
