import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import MagicMock, patch

from app.services.orchestrator import run_synthetic_dev_cycle
from app.services.paper_reconciliation import reconcile_paper_accounts
from app.services.reporting import build_runtime_report


class ReportingTests(unittest.TestCase):
    def _mock_account_report(self) -> MagicMock:
        report = MagicMock()
        report.to_dict.return_value = {
            "ok": True,
            "trading_mode": "paper",
            "fetched_at": "2026-04-17T09:31:00+09:00",
            "cache_used": False,
            "cache_age_seconds": 0,
            "error": None,
            "source": "kis-broker",
            "account_snapshot": {
                "account_no_masked": "1234****",
                "product_code": "01",
                "cash_balance": 1000000,
                "stock_evaluation_amount": 0,
                "total_evaluation_amount": 1000000,
                "total_purchase_amount": 0,
                "total_profit_loss_amount": 0,
                "total_asset_amount": 1000000,
                "positions": [],
            },
        }
        return report

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
            with patch("app.services.paper_reconciliation.refresh_kis_account_report", return_value=self._mock_account_report()):
                reconcile_paper_accounts(project_root=root)
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
            self.assertIn("Latest Paper Reconciliation", report_text)


if __name__ == "__main__":
    unittest.main()
