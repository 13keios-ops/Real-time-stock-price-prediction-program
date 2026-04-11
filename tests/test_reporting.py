import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.services.orchestrator import run_synthetic_dev_cycle
from app.services.reporting import build_runtime_report


class ReportingTests(unittest.TestCase):
    def test_build_runtime_report_after_synthetic_cycle(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "reporting" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }

        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            report = build_runtime_report(project_root=root)

            self.assertTrue(report.report_markdown_path.exists())
            self.assertTrue(report.report_json_path.exists())
            self.assertGreater(report.summary["minute_bars"], 0)
            self.assertGreater(report.summary["training_runs"], 0)
            self.assertGreater(report.summary["backtests"], 0)
            self.assertGreater(report.summary["walk_forward_runs"], 0)
            self.assertGreater(report.summary["challenger_runs"], 0)
            report_text = report.report_markdown_path.read_text(encoding="utf-8")
            self.assertIn("Latest Backtest", report_text)
            self.assertIn("Latest Walk-Forward", report_text)
            self.assertIn("Latest Challenger", report_text)


if __name__ == "__main__":
    unittest.main()
