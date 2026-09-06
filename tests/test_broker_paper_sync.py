import os
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.brokers.kis_auth import KisApiError
from app.brokers.kis_quote_rest import KisDailyOrderFillRecord
from app.config.settings import load_settings
from app.services.broker_paper import BrokerPaperMirror, ORDER_FILL_RATE_LIMIT_RETRY_DELAYS_SECONDS
from app.services.broker_paper_sync import (
    BATCH_ORDER_FILL_RATE_LIMIT_RETRY_DELAYS_SECONDS,
    BrokerPaperExecutionSync,
    BrokerPaperSyncResult,
    sync_broker_paper_orders,
)
from app.storage.contracts import BrokerOrderStatusSnapshot, BrokerOrderSubmission, OrderEvent, PaperOrder
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

    def test_order_fill_fetch_does_not_retry_rate_limit_by_default(self) -> None:
        mirror = object.__new__(BrokerPaperMirror)
        mirror.settings = SimpleNamespace(timezone="Asia/Seoul")
        mirror.client = Mock()
        mirror.client.get_daily_order_fills.side_effect = KisApiError(
            "KIS REST quote error: EGW00201 rate limit"
        )

        with patch("app.services.broker_paper.time.sleep") as mocked_sleep:
            with self.assertRaises(KisApiError):
                mirror.fetch_recent_order_fills()

        self.assertEqual(ORDER_FILL_RATE_LIMIT_RETRY_DELAYS_SECONDS, ())
        self.assertEqual(mirror.client.get_daily_order_fills.call_count, 1)
        mocked_sleep.assert_not_called()

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
            broker_rows.append(
                replace(
                    broker_rows[0],
                    broker_order_no="9999999999",
                    symbol="000660",
                    symbol_name="SK하이닉스",
                    raw_output={"odno": "9999999999"},
                )
            )
            def fetch_rows(mirror, **kwargs):
                mirror.client._last_daily_order_fill_query = {
                    "http_requests_attempted": 1,
                    "pages_fetched": 1,
                    "records_returned": 2,
                    "pagination_complete": True,
                    "page_limit_reached": False,
                    "failed_page": None,
                    "pagination_interrupted_by_rate_limit": False,
                }
                return broker_rows

            with patch.object(BrokerPaperMirror, "fetch_recent_order_fills", autospec=True, side_effect=fetch_rows):
                result = sync_broker_paper_orders(project_root=root)

            sqlite_store = get_sqlite_store(settings)

        self.assertTrue(result.ok)
        self.assertEqual(result.applied_fill_events, 1)
        self.assertEqual(result.applied_fill_qty, 3)
        self.assertEqual(result.order_fill_lookback_days, 3)
        self.assertEqual(result.broker_rows_returned, 2)
        self.assertEqual(result.broker_rows_linked_to_submissions, 1)
        self.assertEqual(result.broker_rows_unlinked_to_submissions, 1)
        self.assertEqual(result.exact_matched_orders, 1)
        self.assertEqual(result.fallback_matched_orders, 0)
        self.assertEqual(result.ambiguous_fallback_key_count, 0)
        self.assertEqual(result.order_fill_http_requests_attempted, 1)
        self.assertEqual(result.order_fill_pages_fetched, 1)
        self.assertIs(result.order_fill_pagination_complete, True)
        self.assertIs(
            result.order_fill_pagination_interrupted_by_rate_limit,
            False,
        )
        report_payload = json.loads(result.report_json_path.read_text(encoding="utf-8"))
        report_markdown = result.report_markdown_path.read_text(encoding="utf-8")
        self.assertEqual(report_payload["order_fill_http_requests_attempted"], 1)
        self.assertIn("`order_fill_pages_fetched`: 1", report_markdown)
        self.assertIsNotNone(sqlite_store)
        latest_position = sqlite_store.fetch_latest_row("paper_positions", "updated_at")
        latest_order = sqlite_store.fetch_latest_row_by_column("paper_orders", "order_id", "paper-order-online-000001", "event_time")
        latest_fill = sqlite_store.fetch_latest_row("paper_fills", "event_time")
        self.assertIsNotNone(latest_position)
        self.assertIsNotNone(latest_order)
        self.assertIsNotNone(latest_fill)
        self.assertEqual(float(latest_fill["tax"]), 0.0)
        self.assertEqual(int(latest_position["qty"]), 3)
        self.assertEqual(str(latest_order["status"]), "filled")
        self.assertEqual(sqlite_store.count_rows("broker_paper_order_status_snapshots"), 1)

    def test_sync_derives_delta_fill_price_from_cumulative_average(self) -> None:
        root, env = self._prepare_runtime()
        event_time = datetime.fromisoformat("2026-04-17T10:15:00+09:00")
        first_sync_time = datetime.fromisoformat("2026-04-17T10:20:00+09:00")
        second_sync_time = datetime.fromisoformat("2026-04-17T10:21:00+09:00")
        first_row = KisDailyOrderFillRecord(
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
            order_qty=10,
            order_price=70000.0,
            filled_qty=4,
            remaining_qty=6,
            avg_fill_price=70000.0,
            filled_amount=280000.0,
            cancel_confirm_qty=0,
            reject_qty=0,
            cancel_yn=False,
            exchange_id="KRX",
            raw_output={"odno": "1234567890"},
        )
        second_row = replace(
            first_row,
            filled_qty=7,
            remaining_qty=3,
            avg_fill_price=70010.0,
            filled_amount=490070.0,
        )
        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            writer = RuntimeWriter.from_settings(settings)
            writer.write_paper_order(
                PaperOrder(
                    order_id="paper-order-online-000001",
                    symbol="005930",
                    event_time=event_time,
                    side="buy",
                    qty=10,
                    limit_price=70000.0,
                    status="submitted",
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
                    qty=10,
                    limit_price=70000.0,
                    order_type="00",
                    status="submitted",
                    broker_order_no="1234567890",
                    broker_branch_no="00111",
                    detail={"message": "ok"},
                )
            )

            with patch("app.services.broker_paper_sync.now_local", return_value=first_sync_time):
                with patch(
                    "app.services.broker_paper_sync.BrokerPaperMirror.fetch_recent_order_fills",
                    return_value=[first_row],
                ):
                    first = sync_broker_paper_orders(project_root=root)
            with patch("app.services.broker_paper_sync.now_local", return_value=second_sync_time):
                with patch(
                    "app.services.broker_paper_sync.BrokerPaperMirror.fetch_recent_order_fills",
                    return_value=[second_row],
                ):
                    second = sync_broker_paper_orders(project_root=root)

            sqlite_store = get_sqlite_store(settings)
            fills = sqlite_store.fetch_all_rows("paper_fills", "event_time")

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual([int(row["fill_qty"]) for row in fills], [4, 3])
        self.assertAlmostEqual(float(fills[0]["fill_price"]), 70000.0)
        self.assertAlmostEqual(
            float(fills[1]["fill_price"]),
            (7 * 70010.0 - 4 * 70000.0) / 3,
        )
        self.assertAlmostEqual(
            sum(float(row["fill_price"]) * int(row["fill_qty"]) for row in fills),
            7 * 70010.0,
        )

    def test_sync_does_not_append_unchanged_broker_status_snapshot(self) -> None:
        root, env = self._prepare_runtime()
        event_time = datetime.fromisoformat("2026-04-17T10:15:00+09:00")
        broker_row = KisDailyOrderFillRecord(
            mode="paper",
            order_date="20260417",
            broker_branch_no="00111",
            broker_order_no="1234567890",
            original_order_no="",
            symbol="005930",
            symbol_name="",
            side="02",
            side_name="",
            order_type_code="00",
            order_type_name="",
            order_time="101500",
            order_qty=3,
            order_price=70000.0,
            filled_qty=0,
            remaining_qty=3,
            avg_fill_price=0.0,
            filled_amount=0.0,
            cancel_confirm_qty=0,
            reject_qty=0,
            cancel_yn=False,
            exchange_id="KRX",
            raw_output={"odno": "1234567890"},
        )
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
            with patch(
                "app.services.broker_paper_sync.BrokerPaperMirror.fetch_recent_order_fills",
                return_value=[broker_row],
            ):
                first = sync_broker_paper_orders(project_root=root)
                second = sync_broker_paper_orders(project_root=root)
            sqlite_store = get_sqlite_store(settings)

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertIsNotNone(sqlite_store)
        assert sqlite_store is not None
        self.assertEqual(sqlite_store.count_rows("broker_paper_order_status_snapshots"), 1)

    def test_sync_rate_limit_keeps_submitted_order_pending(self) -> None:
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

            def raise_rate_limit(mirror, **kwargs):
                mirror.client._last_daily_order_fill_query = {
                    "http_requests_attempted": 2,
                    "pages_fetched": 1,
                    "records_returned": 15,
                    "pagination_complete": False,
                    "page_limit_reached": False,
                    "pages_fetched_before_error": 1,
                    "failed_page": 2,
                    "pagination_interrupted_by_rate_limit": True,
                }
                raise KisApiError("KIS REST quote error: EGW00201 rate limit")

            with patch.object(
                BrokerPaperMirror,
                "fetch_recent_order_fills",
                autospec=True,
                side_effect=raise_rate_limit,
            ):
                result = sync_broker_paper_orders(project_root=root)

            sqlite_store = get_sqlite_store(settings)
            latest_order = sqlite_store.fetch_latest_row_by_column("paper_orders", "order_id", "paper-order-online-000001", "event_time")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "rate_limited")
        self.assertEqual(result.open_order_count, 1)
        self.assertEqual(result.pending_symbols, ["005930"])
        self.assertIsNotNone(result.error)
        self.assertTrue(result.cooldown_active)
        self.assertFalse(result.skipped_broker_call)
        self.assertEqual(result.retry_after_seconds, 2 * 60 * 60)
        self.assertEqual(result.order_fill_http_requests_attempted, 2)
        self.assertEqual(result.order_fill_pages_fetched, 1)
        self.assertEqual(result.order_fill_pages_fetched_before_error, 1)
        self.assertEqual(result.order_fill_failed_page, 2)
        self.assertIs(result.order_fill_pagination_complete, False)
        self.assertIs(
            result.order_fill_pagination_interrupted_by_rate_limit,
            True,
        )
        report_payload = json.loads(result.report_json_path.read_text(encoding="utf-8"))
        report_markdown = result.report_markdown_path.read_text(encoding="utf-8")
        self.assertEqual(report_payload["order_fill_failed_page"], 2)
        self.assertIn(
            "`order_fill_pagination_interrupted_by_rate_limit`: True",
            report_markdown,
        )
        self.assertIsNotNone(latest_order)
        self.assertEqual(str(latest_order["status"]), "submitted")

    def test_recent_rate_limit_report_skips_broker_call_during_cooldown(self) -> None:
        root, env = self._prepare_runtime()
        event_time = datetime.fromisoformat("2026-04-17T10:15:00+09:00")
        fixed_now = datetime.fromisoformat("2026-04-17T10:05:00+09:00")
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
            report_dir = settings.runtime_data_dir / "reports" / "broker-paper"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "latest-sync.json").write_text(
                json.dumps(
                    {
                        "ok": False,
                        "synced_at": "2026-04-17T10:00:00+09:00",
                        "status": "rate_limited",
                        "rate_limited_at": "2026-04-17T10:00:00+09:00",
                        "error": "EGW00201",
                    }
                ),
                encoding="utf-8",
            )

            with patch("app.services.broker_paper_sync.now_local", return_value=fixed_now):
                with patch(
                    "app.services.broker_paper_sync.BrokerPaperMirror.fetch_recent_order_fills",
                    side_effect=AssertionError("broker call should be skipped during cooldown"),
                ):
                    result = sync_broker_paper_orders(
                        project_root=root,
                        rate_limit_cooldown_seconds=30 * 60,
                    )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "rate_limited")
        self.assertTrue(result.cooldown_active)
        self.assertTrue(result.skipped_broker_call)
        self.assertEqual(result.retry_after_seconds, 25 * 60)
        self.assertEqual(result.open_order_count, 1)
        self.assertEqual(result.pending_symbols, ["005930"])

    def test_sync_expires_prior_day_unfilled_open_order(self) -> None:
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
                    filled_qty=0,
                    remaining_qty=3,
                    avg_fill_price=0.0,
                    filled_amount=0.0,
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
            latest_order = sqlite_store.fetch_latest_row_by_column("paper_orders", "order_id", "paper-order-online-000001", "event_time")
            latest_status = sqlite_store.fetch_latest_row("broker_paper_order_status_snapshots", "synced_at")

        self.assertTrue(result.ok)
        self.assertEqual(result.open_order_count, 0)
        self.assertEqual(result.final_order_count, 1)
        self.assertEqual(result.pending_symbols, [])
        self.assertIsNotNone(latest_order)
        self.assertIsNotNone(latest_status)
        self.assertEqual(str(latest_order["status"]), "expired")
        self.assertEqual(str(latest_status["status"]), "expired")

    def test_sync_expires_prior_day_order_missing_from_broker_lookback(self) -> None:
        root, env = self._prepare_runtime()
        event_time = datetime.fromisoformat("2026-04-17T10:15:00+09:00")
        sync_time = datetime.fromisoformat("2026-04-18T09:30:00+09:00")
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

            with patch("app.services.broker_paper_sync.now_local", return_value=sync_time):
                with patch("app.services.broker_paper_sync.BrokerPaperMirror.fetch_recent_order_fills", return_value=[]):
                    result = sync_broker_paper_orders(project_root=root)

            sqlite_store = get_sqlite_store(settings)
            latest_order = sqlite_store.fetch_latest_row_by_column("paper_orders", "order_id", "paper-order-online-000001", "event_time")
            latest_status = sqlite_store.fetch_latest_row("broker_paper_order_status_snapshots", "synced_at")

        self.assertTrue(result.ok)
        self.assertEqual(result.open_order_count, 0)
        self.assertEqual(result.final_order_count, 1)
        self.assertEqual(result.pending_symbols, [])
        self.assertIsNotNone(latest_order)
        self.assertIsNotNone(latest_status)
        self.assertEqual(str(latest_order["status"]), "expired")
        self.assertEqual(str(latest_status["status"]), "expired")
        self.assertFalse(bool(latest_status["matched"]))

    def test_sync_preserves_previous_final_status_when_broker_lookback_drops_row(self) -> None:
        root, env = self._prepare_runtime()
        event_time = datetime.fromisoformat("2026-04-17T10:15:00+09:00")
        first_sync_time = datetime.fromisoformat("2026-04-17T10:20:00+09:00")
        second_sync_time = datetime.fromisoformat("2026-04-18T09:30:00+09:00")
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
                    status="filled",
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
            writer.write_broker_order_status_snapshot(
                BrokerOrderStatusSnapshot(
                    sync_id="broker-sync-000001",
                    local_order_id="paper-order-online-000001",
                    broker_mode="paper",
                    symbol="005930",
                    synced_at=first_sync_time,
                    order_date="20260417",
                    side="buy",
                    order_qty=3,
                    filled_qty=3,
                    remaining_qty=0,
                    avg_fill_price=70100.0,
                    status="filled",
                    broker_order_no="1234567890",
                    broker_branch_no="00111",
                    reject_qty=0,
                    cancel_confirm_qty=0,
                    cancel_yn=False,
                    matched=True,
                    applied_fill_qty=3,
                    detail={"status": "filled"},
                )
            )

            with patch("app.services.broker_paper_sync.now_local", return_value=second_sync_time):
                with patch("app.services.broker_paper_sync.BrokerPaperMirror.fetch_recent_order_fills", return_value=[]):
                    result = sync_broker_paper_orders(project_root=root)

            sqlite_store = get_sqlite_store(settings)
            latest_order = sqlite_store.fetch_latest_row_by_column("paper_orders", "order_id", "paper-order-online-000001", "event_time")
            latest_status = sqlite_store.fetch_latest_row("broker_paper_order_status_snapshots", "synced_at")

        self.assertTrue(result.ok)
        self.assertEqual(result.open_order_count, 0)
        self.assertEqual(result.final_order_count, 1)
        self.assertEqual(result.applied_fill_events, 0)
        self.assertIsNotNone(latest_order)
        self.assertIsNotNone(latest_status)
        self.assertEqual(str(latest_order["status"]), "filled")
        self.assertEqual(str(latest_status["status"]), "filled")
        self.assertEqual(int(latest_status["applied_fill_qty"]), 3)

    def test_sync_preserves_previous_rejected_status_when_broker_lookback_drops_row(self) -> None:
        root, env = self._prepare_runtime()
        event_time = datetime.fromisoformat("2026-04-17T10:15:00+09:00")
        first_sync_time = datetime.fromisoformat("2026-04-17T10:20:00+09:00")
        second_sync_time = datetime.fromisoformat("2026-04-18T09:30:00+09:00")
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
                    status="rejected",
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
            writer.write_broker_order_status_snapshot(
                BrokerOrderStatusSnapshot(
                    sync_id="broker-sync-000001",
                    local_order_id="paper-order-online-000001",
                    broker_mode="paper",
                    symbol="005930",
                    synced_at=first_sync_time,
                    order_date="20260417",
                    side="buy",
                    order_qty=3,
                    filled_qty=0,
                    remaining_qty=3,
                    avg_fill_price=0.0,
                    status="rejected",
                    broker_order_no="1234567890",
                    broker_branch_no="00111",
                    reject_qty=3,
                    cancel_confirm_qty=0,
                    cancel_yn=False,
                    matched=True,
                    applied_fill_qty=0,
                    detail={"status": "rejected"},
                )
            )

            with patch("app.services.broker_paper_sync.now_local", return_value=second_sync_time):
                with patch("app.services.broker_paper_sync.BrokerPaperMirror.fetch_recent_order_fills", return_value=[]):
                    result = sync_broker_paper_orders(project_root=root)

            sqlite_store = get_sqlite_store(settings)
            latest_order = sqlite_store.fetch_latest_row_by_column("paper_orders", "order_id", "paper-order-online-000001", "event_time")
            latest_status = sqlite_store.fetch_latest_row("broker_paper_order_status_snapshots", "synced_at")

        self.assertTrue(result.ok)
        self.assertEqual(result.open_order_count, 0)
        self.assertEqual(result.final_order_count, 1)
        self.assertIsNotNone(latest_order)
        self.assertIsNotNone(latest_status)
        self.assertEqual(str(latest_order["status"]), "rejected")
        self.assertEqual(str(latest_status["status"]), "rejected")

    def test_rate_limited_sync_counts_prior_day_open_snapshot_as_final(self) -> None:
        root, env = self._prepare_runtime()
        event_time = datetime.fromisoformat("2026-04-17T10:15:00+09:00")
        snapshot_time = datetime.fromisoformat("2026-04-18T09:30:00+09:00")
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
            writer.write_broker_order_status_snapshot(
                BrokerOrderStatusSnapshot(
                    sync_id="broker-sync-000001",
                    local_order_id="paper-order-online-000001",
                    broker_mode="paper",
                    symbol="005930",
                    synced_at=snapshot_time,
                    order_date="20260417",
                    side="buy",
                    order_qty=3,
                    filled_qty=0,
                    remaining_qty=3,
                    avg_fill_price=0.0,
                    status="open",
                    broker_order_no="1234567890",
                    broker_branch_no="00111",
                    reject_qty=0,
                    cancel_confirm_qty=0,
                    cancel_yn=False,
                    matched=True,
                    applied_fill_qty=0,
                    detail={"status": "open"},
                )
            )

            with patch(
                "app.services.broker_paper_sync.BrokerPaperMirror.fetch_recent_order_fills",
                side_effect=KisApiError("KIS REST quote error: EGW00201 rate limit"),
            ):
                result = sync_broker_paper_orders(project_root=root)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "rate_limited")
        self.assertEqual(result.open_order_count, 0)
        self.assertEqual(result.final_order_count, 1)
        self.assertEqual(result.pending_symbols, [])

    def test_manual_sync_generated_ids_are_unique_across_runs(self) -> None:
        root, env = self._prepare_runtime()
        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            first = BrokerPaperExecutionSync(settings)
            second = BrokerPaperExecutionSync(settings)

        first_id = first._next_id("fill-broker-sync")
        second_id = second._next_id("fill-broker-sync")
        self.assertNotEqual(first_id, second_id)
        self.assertIn("fill-broker-sync-", first_id)
        self.assertIn("fill-broker-sync-", second_id)

    def test_app_level_sync_uses_single_attempt_and_two_hour_cooldown(self) -> None:
        root, env = self._prepare_runtime()
        dummy_result = BrokerPaperSyncResult(
            ok=True,
            synced_at="2026-04-17T10:15:00+09:00",
            status="ok",
            total_submissions=0,
            matched_orders=0,
            updated_orders=0,
            applied_fill_events=0,
            applied_fill_qty=0,
            open_order_count=0,
            final_order_count=0,
            pending_symbols=[],
            report_markdown_path=Path("latest-sync.md"),
            report_json_path=Path("latest-sync.json"),
        )
        with patch.dict(os.environ, env, clear=False):
            with patch.object(BrokerPaperExecutionSync, "sync_recent_orders", return_value=dummy_result) as mocked_sync:
                result = sync_broker_paper_orders(project_root=root)

        self.assertEqual(ORDER_FILL_RATE_LIMIT_RETRY_DELAYS_SECONDS, ())
        self.assertEqual(BATCH_ORDER_FILL_RATE_LIMIT_RETRY_DELAYS_SECONDS, ())
        self.assertIs(result, dummy_result)
        self.assertEqual(
            mocked_sync.call_args.kwargs["retry_delays_seconds"],
            BATCH_ORDER_FILL_RATE_LIMIT_RETRY_DELAYS_SECONDS,
        )
        self.assertEqual(
            mocked_sync.call_args.kwargs["rate_limit_cooldown_seconds"],
            2 * 60 * 60,
        )

    def test_sync_ignores_submissions_before_alignment_marker(self) -> None:
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
            marker_dir = settings.runtime_data_dir / "reports" / "broker-paper"
            marker_dir.mkdir(parents=True, exist_ok=True)
            (marker_dir / "latest-alignment.json").write_text(
                json.dumps(
                    {
                        "ok": True,
                        "aligned_at": "2026-04-17T10:16:00+09:00",
                        "baseline_positions": [],
                        "baseline_snapshot": {
                            "snapshot_id": "portfolio-broker-aligned-test",
                            "event_time": "2026-04-17T10:16:00+09:00",
                            "cash_balance": 1000000.0,
                            "gross_market_value": 0.0,
                            "net_liquidation_value": 1000000.0,
                            "open_positions": 0,
                            "realized_pnl": 0.0,
                            "unrealized_pnl": 0.0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            broker_rows = [
                KisDailyOrderFillRecord(
                    mode="paper",
                    order_date="20260417",
                    broker_branch_no="00111",
                    broker_order_no="1234567890",
                    original_order_no="",
                    symbol="005930",
                    symbol_name="?쇱꽦?꾩옄",
                    side="02",
                    side_name="留ㅼ닔",
                    order_type_code="00",
                    order_type_name="吏?뺢?",
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
        self.assertEqual(result.status, "no_submissions")
        self.assertEqual(result.applied_fill_events, 0)
        self.assertIsNotNone(sqlite_store)
        self.assertEqual(sqlite_store.count_rows("paper_fills"), 0)


if __name__ == "__main__":
    unittest.main()
