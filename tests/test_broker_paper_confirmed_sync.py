import json
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.brokers.kis_quote_rest import KisDailyOrderFillRecord
from app.config.settings import load_settings
from app.services.broker_paper_sync import BrokerPaperExecutionSync
from app.storage.contracts import BrokerOrderSubmission, Fill, PaperOrder
from app.storage.runtime_writer import RuntimeWriter


class ConfirmedBrokerSyncTests(unittest.TestCase):
    def fixture(self):
        root = Path(__file__).resolve().parents[1]
        runtime = root / ".tmp-tests" / "confirmed-sync" / str(uuid.uuid4())
        runtime.mkdir(parents=True)
        env = {"RUNTIME_DATA_DIR": str(runtime), "DATABASE_URL": f"sqlite:///{runtime / 'test.db'}",
               "ENABLE_BROKER_PAPER_MIRRORING": "true", "KIS_APP_KEY_PAPER": "test-key",
               "KIS_APP_SECRET_PAPER": "test-secret", "KIS_ACCOUNT_NO_PAPER": "12345678",
               "KIS_PRODUCT_CODE_PAPER": "01", "TRADING_MODE": "paper"}
        with patch.dict(os.environ, env):
            settings = load_settings(project_root=root)
        writer = RuntimeWriter.from_settings(settings)
        when = datetime.fromisoformat("2026-09-28T09:20:00+09:00")
        writer.write_paper_order(PaperOrder(order_id="test-order", symbol="005930", event_time=when,
                                           side="buy", qty=3, limit_price=70000.0, status="submitted"))
        writer.write_broker_order_submission(BrokerOrderSubmission(
            submission_id="test-submission", local_order_id="test-order", broker_mode="paper",
            symbol="005930", event_time=when, side="buy", qty=3, limit_price=70000.0,
            order_type="00", status="submitted", broker_order_no="test-1", broker_branch_no="test-branch", detail={}))
        service = BrokerPaperExecutionSync(settings, writer=writer)
        row = KisDailyOrderFillRecord(mode="paper", order_date="20260928", broker_branch_no="test-branch",
            broker_order_no="test-1", original_order_no="", symbol="005930", symbol_name="test",
            side="02", side_name="buy", order_type_code="00", order_type_name="limit", order_time="092000",
            order_qty=3, order_price=70000.0, filled_qty=3, remaining_qty=0, avg_fill_price=70000.0,
            filled_amount=210000.0, cancel_confirm_qty=0, reject_qty=0, cancel_yn=False,
            exchange_id="KRX", raw_output={})
        return service, writer, row

    def sync(self, service, rows, *, complete=True):
        service.broker_mirror.client._last_daily_order_fill_query = {
            "http_requests_attempted": 1, "pages_fetched": 1, "pagination_complete": complete}
        with patch.object(service.broker_mirror, "fetch_recent_order_fills", return_value=rows):
            return service.sync_recent_orders(require_confirmed_evidence=True)

    def test_exact_complete_fill_applies_once(self):
        service, writer, row = self.fixture()
        first = self.sync(service, [row])
        cash = service.portfolio_book.cash_balance
        second = self.sync(service, [row])
        self.assertTrue(first.ok)
        self.assertEqual(first.applied_fill_qty, 3)
        self.assertEqual(second.applied_fill_qty, 0)
        self.assertEqual(writer.sqlite_store.count_rows("paper_fills"), 1)
        self.assertEqual(service.portfolio_book.positions["005930"].qty, 3)
        self.assertEqual(service.portfolio_book.cash_balance, cash)

    def test_ambiguous_incomplete_or_conflicting_evidence_cannot_change_book(self):
        cases = ("incomplete", "duplicate", "symbol", "side", "missing_side", "unmapped_side", "qty", "date", "price", "mode")
        for case in cases:
            with self.subTest(case=case):
                service, writer, row = self.fixture()
                changes = {"symbol": {"symbol": "000660"}, "side": {"side": "01"},
                           "missing_side": {"side": ""},
                           "unmapped_side": {"side": "2"},
                           "qty": {"order_qty": 4}, "date": {"order_date": "20260927"},
                           "price": {"avg_fill_price": float("nan"), "filled_amount": float("nan")},
                           "mode": {"mode": "live"}}
                row = replace(row, **changes.get(case, {}))
                rows = [row, row] if case == "duplicate" else [row]
                result = self.sync(service, rows, complete=case != "incomplete")
                self.assertFalse(result.ok)
                self.assertEqual(result.status, "evidence_blocked")
                self.assertTrue(result.evidence_blocking_reasons)
                self.assertEqual(result.applied_fill_qty, 0)
                self.assertEqual(writer.sqlite_store.count_rows("paper_fills"), 0)
                self.assertEqual(writer.sqlite_store.count_rows("broker_paper_order_status_snapshots"), 0)
                order = writer.sqlite_store.fetch_latest_row("paper_orders", "event_time")
                self.assertEqual(order["status"], "submitted")
                self.assertEqual(service.portfolio_book.positions, {})
                self.assertNotIn("test-branch", result.report_json_path.read_text())

    def test_missing_lookback_row_preserves_order_without_inferred_expiry(self):
        service, writer, row = self.fixture()
        result = self.sync(service, [])
        self.assertTrue(result.ok)
        self.assertEqual(result.unmatched_orders_preserved, 1)
        self.assertEqual(result.pending_symbols, ["005930"])
        self.assertEqual(writer.sqlite_store.count_rows("broker_paper_order_status_snapshots"), 0)
        self.assertEqual(writer.sqlite_store.fetch_latest_row("paper_orders", "event_time")["status"], "submitted")

    def test_local_fill_and_applied_quantity_conflict_blocks_recovery(self):
        service, writer, row = self.fixture()
        writer.write_fill(Fill(fill_id="prior-fill", order_id="test-order",
                              event_time=datetime.fromisoformat("2026-09-28T09:21:00+09:00"),
                              fill_price=70000.0, fill_qty=1, commission=10.5, tax=0.0))
        result = self.sync(service, [row])
        self.assertEqual(result.status, "evidence_blocked")
        self.assertIn("applied_fill_ledger_conflict", result.evidence_blocking_reasons)
        self.assertEqual(writer.sqlite_store.count_rows("paper_fills"), 1)

    def test_unknown_submission_is_not_inferred_from_matching_shape(self):
        service, writer, row = self.fixture()
        writer.write_paper_order(PaperOrder(order_id="unknown-order", symbol="373220",
            event_time=datetime.fromisoformat("2026-09-28T09:22:00+09:00"),
            side="sell", qty=1, limit_price=349500.0, status="submission_unknown"))
        result = self.sync(service, [row])
        self.assertEqual(result.status, "evidence_blocked")
        self.assertIn("unknown_local_submission", result.evidence_blocking_reasons)
        self.assertEqual(writer.sqlite_store.count_rows("paper_fills"), 0)

    def test_confirmed_fill_transaction_rolls_back_on_write_failure(self):
        service, writer, row = self.fixture()
        cash_before = service.portfolio_book.cash_balance
        with patch.object(writer, "write_portfolio_snapshot", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                self.sync(service, [row])
        self.assertEqual(writer.sqlite_store.count_rows("paper_fills"), 0)
        self.assertEqual(writer.sqlite_store.count_rows("paper_order_events"), 0)
        self.assertEqual(writer.sqlite_store.fetch_latest_row("paper_orders", "event_time")["status"], "submitted")
        self.assertEqual(service.portfolio_book.positions, {})
        self.assertEqual(service.portfolio_book.cash_balance, cash_before)

    def test_duplicate_local_order_identity_blocks_different_broker_orders(self):
        service, writer, row = self.fixture()
        writer.write_broker_order_submission(BrokerOrderSubmission(
            submission_id="second-submission", local_order_id="test-order", broker_mode="paper",
            symbol="005930", event_time=datetime.fromisoformat("2026-09-28T09:20:00+09:00"),
            side="buy", qty=3, limit_price=70000.0, order_type="00", status="submitted",
            broker_order_no="test-2", broker_branch_no="test-branch", detail={}))
        result = self.sync(service, [row, replace(row, broker_order_no="test-2")])
        self.assertEqual(result.status, "evidence_blocked")
        self.assertIn("ambiguous_local_order_identity", result.evidence_blocking_reasons)
        self.assertEqual(writer.sqlite_store.count_rows("paper_fills"), 0)

    def test_cumulative_fill_regression_does_not_rewrite_prior_fill(self):
        service, writer, row = self.fixture()
        self.assertTrue(self.sync(service, [row]).ok)
        cash_before = service.portfolio_book.cash_balance
        result = self.sync(service, [replace(row, filled_qty=2, remaining_qty=1, filled_amount=140000.0)])
        self.assertEqual(result.status, "evidence_blocked")
        self.assertIn("invalid_cumulative_fill_quantity", result.evidence_blocking_reasons)
        self.assertEqual(writer.sqlite_store.count_rows("paper_fills"), 1)
        self.assertEqual(service.portfolio_book.cash_balance, cash_before)

    def test_same_fill_quantity_with_conflicting_amount_blocks_accounting(self):
        service, writer, row = self.fixture()
        self.assertTrue(self.sync(service, [row]).ok)
        result = self.sync(service, [replace(row, avg_fill_price=71000.0, filled_amount=213000.0)])
        self.assertEqual(result.status, "evidence_blocked")
        self.assertIn("applied_fill_amount_conflict", result.evidence_blocking_reasons)
        self.assertEqual(writer.sqlite_store.count_rows("paper_fills"), 1)

    def test_recognized_side_alias_uses_same_normalization_as_accounting(self):
        service, writer, row = self.fixture()
        result = self.sync(service, [replace(row, side="B")])
        self.assertTrue(result.ok)
        self.assertEqual(result.applied_fill_qty, 3)
        self.assertEqual(service.portfolio_book.positions["005930"].qty, 3)

    def test_partial_transaction_failure_preserves_committed_fill_report(self):
        service, writer, row = self.fixture()
        when = datetime.fromisoformat("2026-09-28T09:22:00+09:00")
        writer.write_paper_order(PaperOrder(order_id="second-order", symbol="005930", event_time=when,
                                           side="buy", qty=3, limit_price=70000.0, status="submitted"))
        writer.write_broker_order_submission(BrokerOrderSubmission(
            submission_id="second-submission", local_order_id="second-order", broker_mode="paper",
            symbol="005930", event_time=when, side="buy", qty=3, limit_price=70000.0,
            order_type="00", status="submitted", broker_order_no="test-2", broker_branch_no="test-branch", detail={}))
        original = writer.write_portfolio_snapshot
        calls = []
        def fail_second(snapshot):
            calls.append(snapshot)
            if len(calls) == 2:
                raise RuntimeError("SECRET-ERROR")
            return original(snapshot)
        with patch.object(writer, "write_portfolio_snapshot", side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                self.sync(service, [row, replace(row, broker_order_no="test-2")])
        payload = json.loads((service.settings.runtime_data_dir / "reports/broker-paper/latest-sync.json").read_text())
        self.assertEqual(payload["status"], "accounting_sync_failed")
        self.assertEqual(payload["applied_fill_events"], 1)
        self.assertEqual(payload["applied_fill_qty"], 3)
        self.assertEqual(writer.sqlite_store.count_rows("paper_fills"), 1)
        self.assertEqual(service.portfolio_book.positions["005930"].qty, 3)
        self.assertNotIn("SECRET-ERROR", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
