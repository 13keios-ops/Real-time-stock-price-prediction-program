import os
from datetime import datetime
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.services.kis_account import KisAccountReportResult
from app.services.paper_alignment import align_local_paper_to_broker
from app.services.paper_reconciliation import load_local_paper_account_state
from app.storage.contracts import BrokerOrderSubmission, Fill, PaperOrder, PaperPosition, PortfolioSnapshot
from app.storage.runtime_writer import RuntimeWriter, get_sqlite_store


class PaperAlignmentTests(unittest.TestCase):
    def _prepare_runtime(self) -> tuple[Path, dict[str, str], Path]:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "paper-alignment" / str(uuid.uuid4())
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
        return root, env, runtime_root

    def test_align_local_paper_to_broker_writes_marker_and_hides_stale_local_state(self) -> None:
        root, env, runtime_root = self._prepare_runtime()
        event_time = datetime.fromisoformat("2026-04-17T09:15:00+09:00")
        markdown_path = runtime_root / "reports" / "kis-account" / "latest-account-paper.md"
        json_path = runtime_root / "reports" / "kis-account" / "latest-account-paper.json"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            writer = RuntimeWriter.from_settings(settings)
            writer.write_paper_position(
                PaperPosition(
                    symbol="005930",
                    opened_at=event_time,
                    updated_at=event_time,
                    qty=5,
                    avg_price=70000.0,
                    last_price=70100.0,
                    market_value=350500.0,
                    cost_basis=350000.0,
                    realized_pnl=0.0,
                    unrealized_pnl=500.0,
                )
            )
            writer.write_portfolio_snapshot(
                PortfolioSnapshot(
                    snapshot_id="snapshot-local-before-align",
                    event_time=event_time,
                    cash_balance=24000000.0,
                    gross_market_value=350500.0,
                    net_liquidation_value=24350500.0,
                    open_positions=1,
                    realized_pnl=0.0,
                    unrealized_pnl=500.0,
                )
            )
            writer.write_paper_order(
                PaperOrder(
                    order_id="paper-order-before-align-001",
                    symbol="005930",
                    event_time=event_time,
                    side="buy",
                    qty=5,
                    limit_price=70000.0,
                    status="filled",
                )
            )
            writer.write_fill(
                Fill(
                    fill_id="fill-before-align-001",
                    order_id="paper-order-before-align-001",
                    event_time=event_time,
                    fill_price=70000.0,
                    fill_qty=5,
                    commission=0.0,
                    tax=0.0,
                )
            )
            writer.write_broker_order_submission(
                BrokerOrderSubmission(
                    submission_id="broker-paper-before-align-001",
                    local_order_id="paper-order-before-align-001",
                    broker_mode="paper",
                    symbol="005930",
                    event_time=event_time,
                    side="buy",
                    qty=5,
                    limit_price=70000.0,
                    order_type="00",
                    status="submitted",
                    broker_order_no="100001",
                    broker_branch_no="001",
                    detail={"message": "ok"},
                )
            )

            fake_report = KisAccountReportResult(
                ok=True,
                trading_mode="paper",
                fetched_at="2026-04-17T16:40:00+09:00",
                cache_used=False,
                cache_age_seconds=0,
                error=None,
                source="kis-broker",
                account_snapshot={
                    "cash_balance": 10000000.0,
                    "stock_evaluation_amount": 0.0,
                    "total_evaluation_amount": 10000000.0,
                    "total_purchase_amount": 0.0,
                    "total_profit_loss_amount": 0.0,
                    "total_asset_amount": 10000000.0,
                    "position_row_count": 0,
                    "positions": [],
                },
                report_markdown_path=markdown_path,
                report_json_path=json_path,
            )

            with patch("app.services.paper_alignment.refresh_kis_account_report", return_value=fake_report):
                result = align_local_paper_to_broker(project_root=root)

            sqlite_store = get_sqlite_store(settings)
            local_state = load_local_paper_account_state(settings)

        self.assertTrue(result.ok)
        self.assertTrue(result.report_json_path.exists())
        self.assertIsNotNone(sqlite_store)
        self.assertEqual(sqlite_store.count_rows("paper_positions"), 1)
        self.assertEqual(local_state["cash_balance"], 10000000.0)
        self.assertEqual(local_state["net_liquidation_value"], 10000000.0)
        self.assertEqual(local_state["positions"], [])
        self.assertEqual(local_state["orders_total"], 0)
        self.assertEqual(local_state["fills_total"], 0)
        self.assertEqual(local_state["broker_order_submissions"], 0)


if __name__ == "__main__":
    unittest.main()
