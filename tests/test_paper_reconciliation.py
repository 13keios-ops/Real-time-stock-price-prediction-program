import os
from datetime import datetime
from pathlib import Path
import unittest
import uuid
from unittest.mock import MagicMock, patch

from app.config.settings import load_settings
from app.services.paper_reconciliation import reconcile_paper_accounts
from app.storage.contracts import BrokerOrderSubmission, PaperPosition, PortfolioSnapshot
from app.storage.runtime_writer import RuntimeWriter


class PaperReconciliationTests(unittest.TestCase):
    def _prepare_runtime(self) -> tuple[Path, dict[str, str]]:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "paper-reconciliation" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
            "ENABLE_BROKER_PAPER_MIRRORING": "true",
            "KIS_APP_KEY_PAPER": "paper-key",
            "KIS_APP_SECRET_PAPER": "paper-secret",
            "KIS_ACCOUNT_NO_PAPER": "12345678",
            "KIS_PRODUCT_CODE_PAPER": "01",
        }
        return root, env

    def _seed_local_state(self, root: Path) -> None:
        settings = load_settings(project_root=root)
        writer = RuntimeWriter.from_settings(settings)
        event_time = datetime.fromisoformat("2026-04-17T09:30:00+09:00")
        writer.write_paper_position(
            PaperPosition(
                symbol="005930",
                opened_at=event_time,
                updated_at=event_time,
                qty=3,
                avg_price=70000.0,
                last_price=71500.0,
                market_value=214500.0,
                cost_basis=210000.0,
                realized_pnl=0.0,
                unrealized_pnl=4500.0,
            )
        )
        writer.write_portfolio_snapshot(
            PortfolioSnapshot(
                snapshot_id="portfolio-test-001",
                event_time=event_time,
                cash_balance=1000000.0,
                gross_market_value=214500.0,
                net_liquidation_value=1214500.0,
                open_positions=1,
                realized_pnl=0.0,
                unrealized_pnl=4500.0,
            )
        )
        writer.write_broker_order_submission(
            BrokerOrderSubmission(
                submission_id="broker-paper-paper-order-test-001",
                local_order_id="paper-order-test-001",
                broker_mode="paper",
                symbol="005930",
                event_time=event_time,
                side="buy",
                qty=3,
                limit_price=70000.0,
                order_type="00",
                status="submitted",
                broker_order_no="100001",
                broker_branch_no="001",
                detail={"message": "ok"},
            )
        )

    def _mock_report(self, *, broker_qty: int) -> MagicMock:
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
                "stock_evaluation_amount": 214500,
                "total_evaluation_amount": 1214500,
                "total_purchase_amount": 210000,
                "total_profit_loss_amount": 4500,
                "total_asset_amount": 1214500,
                "positions": [
                    {
                        "symbol": "005930",
                        "name": "삼성전자",
                        "holding_qty": broker_qty,
                        "orderable_qty": broker_qty,
                        "average_buy_price": 70000.0,
                        "current_price": 71500.0,
                        "evaluation_amount": 214500.0,
                        "evaluation_profit_loss_amount": 4500.0,
                        "evaluation_profit_loss_pct": 2.1428,
                    }
                ],
            },
        }
        return report

    def test_reconcile_paper_accounts_reports_aligned_state(self) -> None:
        root, env = self._prepare_runtime()
        with patch.dict(os.environ, env, clear=False):
            self._seed_local_state(root)
            with patch("app.services.paper_reconciliation.refresh_kis_account_report", return_value=self._mock_report(broker_qty=3)):
                result = reconcile_paper_accounts(project_root=root)

        self.assertTrue(result.report_json_path.exists())
        self.assertEqual(result.status, "aligned")
        self.assertEqual(result.mismatch_count, 0)
        self.assertTrue(result.comparison["positions_match"])
        self.assertTrue(result.comparison["balance_match"])

    def test_reconcile_paper_accounts_reports_qty_mismatch(self) -> None:
        root, env = self._prepare_runtime()
        with patch.dict(os.environ, env, clear=False):
            self._seed_local_state(root)
            with patch("app.services.paper_reconciliation.refresh_kis_account_report", return_value=self._mock_report(broker_qty=4)):
                result = reconcile_paper_accounts(project_root=root)

        self.assertEqual(result.status, "needs_review")
        self.assertEqual(result.mismatch_count, 1)
        self.assertEqual(result.comparison["mismatch_rows"][0]["qty_gap"], -1)


if __name__ == "__main__":
    unittest.main()
