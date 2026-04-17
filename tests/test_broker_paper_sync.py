import os
from datetime import datetime
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.brokers.kis_quote_rest import KisDailyOrderFillRecord
from app.config.settings import load_settings
from app.services.broker_paper_sync import sync_broker_paper_orders
from app.storage.contracts import BrokerOrderSubmission, OrderEvent, PaperOrder
from app.storage.runtime_writer import RuntimeWriter, get_sqlite_store


class BrokerPaperSyncTests(unittest.TestCase):
    def _prepare_runtime(self) -> tuple[Path, dict[str, str]]:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "broker-paper-sync" / str(uuid.uuid4())
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

    def test_sync_broker_paper_orders_applies_broker_fill_to_local_book(self) -> None:
        root, env = self._prepare_runtime()
        event_time = datetime.fromisoformat("2026-04-17T10:15:00+09:00")
        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            writer = RuntimeWriter.from_settings(settings)
            writer.write_paper_order(
                PaperOrder(
                    order_id="paper-order-online-000001",
                    symbol="005930",
                    event_time=event_time,
                    side="buy",
                    qty=3,
                    limit_price=70000.0,
                    status="submitted",
                )
            )
            writer.write_order_event(
                OrderEvent(
                    order_event_id="order-event-online-000001",
                    order_id="paper-order-online-000001",
                    event_time=event_time,
                    event_type="acknowledged",
                    detail="qty=3",
                )
            )
            writer.write_broker_order_submission(
                BrokerOrderSubmission(
                    submission_id="broker-paper-paper-order-online-000001",
                    local_order_id="paper-order-online-000001",
                    broker_mode="paper",
                    symbol="005930",
                    event_time=event_time,
                    side="buy",
                    qty=3,
                    limit_price=70000.0,
                    order_type="00",
                    status="submitted",
                    broker_order_no="1234567890",
                    broker_branch_no="00111",
                    detail={"message": "ok"},
                )
            )

            broker_rows = [
                KisDailyOrderFillRecord(
                    mode="paper",
                    order_date="20260417",
                    broker_branch_no="00111",
                    broker_order_no="1234567890",
                    original_order_no="",
                    symbol="005930",
                    symbol_name="삼성전자",
                    side="02",
                    side_name="매수",
                    order_type_code="00",
                    order_type_name="지정가",
                    order_time="101500",
                    order_qty=3,
                    order_price=70000.0,
                    filled_qty=3,
                    remaining_qty=0,
                    avg_fill_price=70100.0,
                    filled_amount=210300.0,
                    cancel_confirm_qty=0,
                    reject_qty=0,
                    cancel_yn=False,
                    exchange_id="KRX",
                    raw_output={"odno": "1234567890"},
                )
            ]
            with patch("app.services.broker_paper_sync.BrokerPaperMirror.fetch_recent_order_fills", return_value=broker_rows):
                result = sync_broker_paper_orders(project_root=root)

            sqlite_store = get_sqlite_store(settings)

        self.assertTrue(result.ok)
        self.assertEqual(result.applied_fill_events, 1)
        self.assertEqual(result.applied_fill_qty, 3)
        self.assertIsNotNone(sqlite_store)
        latest_position = sqlite_store.fetch_latest_row("paper_positions", "updated_at")
        latest_order = sqlite_store.fetch_latest_row_by_column("paper_orders", "order_id", "paper-order-online-000001", "event_time")
        self.assertIsNotNone(latest_position)
        self.assertIsNotNone(latest_order)
        self.assertEqual(int(latest_position["qty"]), 3)
        self.assertEqual(str(latest_order["status"]), "filled")
        self.assertEqual(sqlite_store.count_rows("broker_paper_order_status_snapshots"), 1)


if __name__ == "__main__":
    unittest.main()
