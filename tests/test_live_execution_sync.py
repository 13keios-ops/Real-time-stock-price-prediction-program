import json
import unittest
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.brokers.kis_quote_rest import KisDailyOrderFillRecord
from app.services.live_kill_switch import LiveKillSwitch
from app.services.live_order_manager import BrokerSubmitResult, LiveOrderIntentRequest, LiveOrderManager
from app.services.live_execution_sync import (
    LiveExecutionSync,
    LiveRecoveryIncompleteError,
    build_live_order_sync_decision,
    derive_live_order_status,
    snapshot_from_kis_daily_order_fill,
)
from app.services.market_status import evaluate_market_status
from app.storage.contracts import MarketStatusSnapshot
from app.storage.jsonl_store import JsonlArtifactStore
from app.storage.runtime_writer import RuntimeWriter
from app.storage.sqlite_store import SQLiteRuntimeStore


@dataclass(slots=True)
class FakeSettings:
    trading_mode: str = "live"
    allow_live_orders: bool = True


class FakeSubmitBroker:
    def submit_cash_order(self, **kwargs):
        return BrokerSubmitResult(
            accepted=True,
            status="submitted",
            broker_order_no="broker-1",
            broker_branch_no="01",
            raw_response={"rt_cd": "0"},
        )


@dataclass(slots=True)
class FakeProfile:
    mode: str = "live"


class FakeOrderHistoryBroker:
    def __init__(self, records, *, pagination_complete: bool = True, mode: str = "live") -> None:
        self.records = list(records)
        self.profile = FakeProfile(mode=mode)
        self.last_daily_order_fill_query = {"pagination_complete": pagination_complete}
        self.calls = []

    def get_daily_order_fills(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.records)


class LiveExecutionSyncTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1] / ".tmp-tests" / "live-execution-sync" / str(uuid.uuid4())

    def _now(self) -> datetime:
        return datetime(2026, 5, 18, 0, 30, tzinfo=timezone.utc)

    def _record(self, **overrides) -> KisDailyOrderFillRecord:
        values = {
            "mode": "live",
            "order_date": "20260518",
            "broker_branch_no": "01",
            "broker_order_no": "broker-1",
            "original_order_no": "",
            "symbol": "005930",
            "symbol_name": "삼성전자",
            "side": "02",
            "side_name": "매수",
            "order_type_code": "00",
            "order_type_name": "지정가",
            "order_time": "090501",
            "order_qty": 10,
            "order_price": 70000.0,
            "filled_qty": 0,
            "remaining_qty": 10,
            "avg_fill_price": 0.0,
            "filled_amount": 0.0,
            "cancel_confirm_qty": 0,
            "reject_qty": 0,
            "cancel_yn": False,
            "exchange_id": "KRX",
            "raw_output": {},
        }
        values.update(overrides)
        return KisDailyOrderFillRecord(**values)

    def _writer(self) -> RuntimeWriter:
        root = self._root()
        return RuntimeWriter(
            jsonl_store=JsonlArtifactStore(root / "runtime-data"),
            sqlite_store=SQLiteRuntimeStore(root / "dev.db"),
        )

    def _redacted_runtime_fixture_record(self) -> KisDailyOrderFillRecord:
        raw_output = {
            "ord_dt": "20260515",
            "ord_gno_brno": "00950",
            "ord_orgno": "",
            "odno": "0000025448",
            "orgn_odno": "0000000000",
            "pdno": "373220",
            "sll_buy_dvsn_cd": "01",
            "sll_buy_dvsn_cd_name": "매도",
            "ord_qty": "1",
            "tot_ccld_qty": "1",
            "rmn_qty": "0",
            "avg_prvs": "432500",
            "cncl_cfrm_qty": "0",
            "rjct_qty": "0",
            "cncl_yn": "N",
            "excg_id_dvsn_cd": "KRX",
        }
        return KisDailyOrderFillRecord(
            mode="paper",
            order_date="20260515",
            broker_branch_no="00950",
            broker_order_no="0000025448",
            original_order_no="0000000000",
            symbol="373220",
            symbol_name="",
            side="01",
            side_name="매도",
            order_type_code="00",
            order_type_name="지정가",
            order_time="115605",
            order_qty=1,
            order_price=432500.0,
            filled_qty=1,
            remaining_qty=0,
            avg_fill_price=432500.0,
            filled_amount=432500.0,
            cancel_confirm_qty=0,
            reject_qty=0,
            cancel_yn=False,
            exchange_id="KRX",
            raw_output=raw_output,
        )

    def _request(self) -> LiveOrderIntentRequest:
        return LiveOrderIntentRequest(
            order_id="order-sync",
            trading_day="2026-05-18",
            phase="phase2_conservative",
            symbol="005930",
            side="buy",
            qty=10,
            order_type="limit",
            limit_price=70000.0,
            prediction_id="prediction-1",
            signal_id="signal-1",
            target_id="target-1",
            gate_decision_id="gate-1",
            market_status_snapshot_id="market-status-1",
            model_version="model-1",
            rule_version="rule-1",
            created_at=self._now(),
            order_policy={"type": "phase2_limit_only", "max_order_notional": 1_000_000, "max_order_qty": 10},
        )

    def _submitted_order(self, writer: RuntimeWriter):
        manager = LiveOrderManager(writer)
        intent = manager.create_intent(self._request())
        manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(writer),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=FakeSubmitBroker(),
            submitted_at=self._now(),
            ws_recovery_evidence_type="real_kis_ws_observed",
        )
        return intent

    def _unknown_order(self, writer: RuntimeWriter):
        intent = self._submitted_order(writer)
        manager = LiveOrderManager(writer)
        manager.store.update_live_order_transition(
            order_id=intent.order_id,
            status="unknown",
            broker_order_no="broker-1",
            broker_branch_no="01",
            reject_reason=None,
            cancel_reason=None,
            submitted_at=self._now(),
            last_synced_at=self._now(),
            detail_json={"order_policy": {}, "blocking_reasons": [], "raw_broker_response": {}},
        )
        return intent

    def test_snapshot_from_kis_daily_order_fill_matches_redacted_runtime_fixture(self) -> None:
        snapshot = snapshot_from_kis_daily_order_fill(self._redacted_runtime_fixture_record())

        self.assertTrue(snapshot.matched)
        self.assertEqual(snapshot.order_date, "20260515")
        self.assertEqual(snapshot.broker_branch_no, "00950")
        self.assertEqual(snapshot.broker_order_no, "0000025448")
        self.assertEqual(snapshot.symbol, "373220")
        self.assertEqual(snapshot.side, "sell")
        self.assertEqual(snapshot.order_qty, 1)
        self.assertEqual(snapshot.filled_qty, 1)
        self.assertEqual(snapshot.remaining_qty, 0)
        self.assertEqual(snapshot.avg_fill_price, 432500.0)
        self.assertEqual(snapshot.reject_qty, 0)
        self.assertEqual(snapshot.cancel_confirm_qty, 0)
        self.assertFalse(snapshot.cancel_yn)
        self.assertEqual(derive_live_order_status(snapshot), "filled")

    def _kill_switch_state(self, writer: RuntimeWriter):
        path = writer.sqlite_store.database_path.parent / "runtime-data" / "reports" / "live-risk" / "kill-switch.json"
        return LiveKillSwitch(path).write_state(
            enabled=False,
            reason="fixture",
            actor="test",
            now=self._now(),
            stale_after=self._now() + timedelta(hours=1),
        )

    def _market_decision(self):
        snapshot = MarketStatusSnapshot(
            snapshot_id="market-status-1",
            trading_day="2026-05-18",
            created_at=self._now(),
            source="manual_fixture",
            symbol_set_hash="hash-1",
            status_json={
                "symbols": {"005930": {"tradable": True}},
                "market_session": "regular",
                "source_generated_at": self._now().isoformat(),
            },
            stale_after=self._now() + timedelta(minutes=5),
        )
        return evaluate_market_status(snapshot, "005930", now=self._now())

    def test_snapshot_normalizes_kis_record_fields(self) -> None:
        snapshot = snapshot_from_kis_daily_order_fill(self._record(side="01", raw_output={"expire_yn": "Y"}))

        self.assertEqual(snapshot.side, "sell")
        self.assertTrue(snapshot.expired)
        self.assertEqual(snapshot.broker_order_no, "broker-1")

    def test_status_mapping_for_live_order_outcomes(self) -> None:
        cases = [
            (self._record(), True, "open"),
            (self._record(filled_qty=3, remaining_qty=7, avg_fill_price=70010.0), True, "partially_filled"),
            (self._record(filled_qty=10, remaining_qty=0, avg_fill_price=70010.0), True, "filled"),
            (self._record(cancel_yn=True, cancel_confirm_qty=10, remaining_qty=0), True, "cancelled"),
            (
                self._record(filled_qty=3, remaining_qty=0, cancel_yn=True, cancel_confirm_qty=7, avg_fill_price=70010.0),
                True,
                "cancelled_partial",
            ),
            (self._record(reject_qty=10, remaining_qty=0), True, "rejected"),
            (self._record(remaining_qty=0, raw_output={"expired": True}), True, "expired"),
            (self._record(remaining_qty=0), True, "accepted"),
            (self._record(), False, "unknown"),
        ]

        for record, matched, expected in cases:
            with self.subTest(expected=expected):
                snapshot = snapshot_from_kis_daily_order_fill(record, matched=matched)
                self.assertEqual(derive_live_order_status(snapshot), expected)

    def test_delta_fill_only_applies_new_quantity(self) -> None:
        snapshot = snapshot_from_kis_daily_order_fill(
            self._record(filled_qty=7, remaining_qty=3, avg_fill_price=70005.0)
        )

        decision = build_live_order_sync_decision(snapshot, previous_applied_fill_qty=4)

        self.assertEqual(decision.status, "partially_filled")
        self.assertEqual(decision.delta_fill_qty, 3)
        self.assertEqual(decision.applied_fill_qty, 7)
        self.assertTrue(decision.inflight)
        self.assertFalse(decision.final)

    def test_delta_fill_never_goes_negative(self) -> None:
        snapshot = snapshot_from_kis_daily_order_fill(self._record(filled_qty=2, remaining_qty=8))

        decision = build_live_order_sync_decision(snapshot, previous_applied_fill_qty=5)

        self.assertEqual(decision.delta_fill_qty, 0)
        self.assertEqual(decision.applied_fill_qty, 5)

    def test_apply_order_snapshot_updates_order_status_and_quantities(self) -> None:
        writer = self._writer()
        manager = LiveOrderManager(writer)
        intent = manager.create_intent(self._request())
        manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(writer),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=FakeSubmitBroker(),
            submitted_at=self._now(),
            ws_recovery_evidence_type="real_kis_ws_observed",
        )
        snapshot = snapshot_from_kis_daily_order_fill(
            self._record(filled_qty=10, remaining_qty=0, avg_fill_price=70010.0)
        )

        decision = LiveExecutionSync(writer).apply_order_snapshot(
            order_id=intent.order_id,
            snapshot=snapshot,
            synced_at=self._now(),
            previous_applied_fill_qty=0,
        )

        row = writer.sqlite_store.fetch_live_order(intent.order_id)
        self.assertEqual(decision.status, "filled")
        self.assertEqual(decision.delta_fill_qty, 10)
        self.assertEqual(row["status"], "filled")
        self.assertEqual(row["filled_qty"], 10)
        self.assertEqual(row["remaining_qty"], 0)
        self.assertEqual(row["avg_fill_price"], 70010.0)

    def test_apply_order_snapshot_and_fill_delta_is_idempotent(self) -> None:
        writer = self._writer()
        manager = LiveOrderManager(writer)
        intent = manager.create_intent(self._request())
        manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(writer),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=FakeSubmitBroker(),
            submitted_at=self._now(),
            ws_recovery_evidence_type="real_kis_ws_observed",
        )
        sync = LiveExecutionSync(writer)
        first_snapshot = snapshot_from_kis_daily_order_fill(
            self._record(filled_qty=4, remaining_qty=6, avg_fill_price=70000.0)
        )

        first = sync.apply_order_snapshot_and_fill_delta(
            order_id=intent.order_id,
            snapshot=first_snapshot,
            synced_at=self._now(),
            settlement_day="2026-05-20",
        )
        repeated = sync.apply_order_snapshot_and_fill_delta(
            order_id=intent.order_id,
            snapshot=first_snapshot,
            synced_at=self._now(),
            settlement_day="2026-05-20",
        )
        second = sync.apply_order_snapshot_and_fill_delta(
            order_id=intent.order_id,
            snapshot=snapshot_from_kis_daily_order_fill(
                self._record(filled_qty=7, remaining_qty=3, avg_fill_price=70000.0)
            ),
            synced_at=self._now() + timedelta(minutes=1),
            settlement_day="2026-05-20",
        )

        self.assertTrue(first.fill_inserted)
        self.assertEqual(first.delta_fill_qty, 4)
        self.assertFalse(repeated.fill_inserted)
        self.assertEqual(repeated.delta_fill_qty, 0)
        self.assertTrue(second.fill_inserted)
        self.assertEqual(second.delta_fill_qty, 3)
        self.assertEqual(writer.sqlite_store.count_rows("live_fills"), 2)
        self.assertEqual(writer.sqlite_store.sum_live_fill_qty(intent.order_id), 7)
        self.assertTrue(sync.validate_live_order_fill_qty(intent.order_id).consistent)
        self.assertEqual(sync.scan_live_order_fill_consistency(trading_day="2026-05-18"), [])
        summary = sync.build_live_order_fill_consistency_summary(trading_day="2026-05-18")
        self.assertTrue(summary.ok)
        self.assertEqual(summary.checked_order_count, 1)

    def test_apply_order_snapshot_redacts_sensitive_raw_output_before_persisting(self) -> None:
        writer = self._writer()
        manager = LiveOrderManager(writer)
        intent = manager.create_intent(self._request())
        manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(writer),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=FakeSubmitBroker(),
            submitted_at=self._now(),
            ws_recovery_evidence_type="real_kis_ws_observed",
        )
        sync = LiveExecutionSync(writer)

        result = sync.apply_order_snapshot_and_fill_delta(
            order_id=intent.order_id,
            snapshot=snapshot_from_kis_daily_order_fill(
                self._record(
                    filled_qty=4,
                    remaining_qty=6,
                    avg_fill_price=70000.0,
                    raw_output={
                        "rt_cd": "0",
                        "account_number": "1234567890",
                        "app_secret": "secret-value",
                        "pdno": "005930",
                    },
                )
            ),
            synced_at=self._now(),
            settlement_day="2026-05-20",
        )

        order_detail = json.loads(writer.sqlite_store.fetch_live_order(intent.order_id)["detail_json"])
        raw_order = order_detail["raw_broker_response"]
        self.assertEqual(raw_order["account_number"], "<REDACTED>")
        self.assertEqual(raw_order["app_secret"], "<REDACTED>")
        self.assertEqual(raw_order["pdno"], "005930")
        fill_detail = json.loads(writer.sqlite_store.fetch_live_fill(result.fill_id)["detail_json"])
        raw_fill = fill_detail["raw_broker_fill"]
        self.assertEqual(raw_fill["account_number"], "<REDACTED>")
        self.assertEqual(raw_fill["app_secret"], "<REDACTED>")
        events = writer.sqlite_store.fetch_all_rows("live_order_events", "event_time")
        raw_event = json.loads(events[-1]["detail_json"])["raw_broker_response"]
        self.assertEqual(raw_event["account_number"], "<REDACTED>")
        self.assertEqual(raw_event["app_secret"], "<REDACTED>")

    def test_apply_order_snapshot_and_fill_delta_derives_delta_price_from_cumulative_average(self) -> None:
        writer = self._writer()
        manager = LiveOrderManager(writer)
        intent = manager.create_intent(self._request())
        manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(writer),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=FakeSubmitBroker(),
            submitted_at=self._now(),
            ws_recovery_evidence_type="real_kis_ws_observed",
        )
        sync = LiveExecutionSync(writer)

        sync.apply_order_snapshot_and_fill_delta(
            order_id=intent.order_id,
            snapshot=snapshot_from_kis_daily_order_fill(
                self._record(filled_qty=4, remaining_qty=6, avg_fill_price=70000.0)
            ),
            synced_at=self._now(),
            settlement_day="2026-05-20",
        )
        result = sync.apply_order_snapshot_and_fill_delta(
            order_id=intent.order_id,
            snapshot=snapshot_from_kis_daily_order_fill(
                self._record(filled_qty=7, remaining_qty=3, avg_fill_price=70010.0)
            ),
            synced_at=self._now() + timedelta(minutes=1),
            settlement_day="2026-05-20",
        )

        fill = writer.sqlite_store.fetch_live_fill(result.fill_id)
        self.assertIsNotNone(fill)
        self.assertAlmostEqual(fill["fill_price"], (7 * 70010.0 - 4 * 70000.0) / 3)

    def test_live_order_fill_consistency_detects_missing_fill_delta(self) -> None:
        writer = self._writer()
        manager = LiveOrderManager(writer)
        intent = manager.create_intent(self._request())
        manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(writer),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=FakeSubmitBroker(),
            submitted_at=self._now(),
            ws_recovery_evidence_type="real_kis_ws_observed",
        )
        sync = LiveExecutionSync(writer)

        sync.apply_order_snapshot(
            order_id=intent.order_id,
            snapshot=snapshot_from_kis_daily_order_fill(
                self._record(filled_qty=3, remaining_qty=7, avg_fill_price=70000.0)
            ),
            synced_at=self._now(),
            previous_applied_fill_qty=0,
        )

        consistency = sync.validate_live_order_fill_qty(intent.order_id)
        mismatches = sync.scan_live_order_fill_consistency(trading_day="2026-05-18")
        self.assertFalse(consistency.consistent)
        self.assertEqual(consistency.order_filled_qty, 3)
        self.assertEqual(consistency.live_fill_qty_sum, 0)
        self.assertEqual([(item.order_id, item.order_filled_qty, item.live_fill_qty_sum) for item in mismatches], [(intent.order_id, 3, 0)])
        summary = sync.build_live_order_fill_consistency_summary(trading_day="2026-05-18")
        self.assertFalse(summary.ok)
        self.assertEqual(summary.mismatch_count, 1)

    def test_unmatched_snapshot_does_not_create_live_fill(self) -> None:
        writer = self._writer()
        manager = LiveOrderManager(writer)
        intent = manager.create_intent(self._request())
        sync = LiveExecutionSync(writer)

        result = sync.apply_order_snapshot_and_fill_delta(
            order_id=intent.order_id,
            snapshot=snapshot_from_kis_daily_order_fill(
                self._record(filled_qty=3, remaining_qty=7, avg_fill_price=70000.0),
                matched=False,
            ),
            synced_at=self._now(),
            settlement_day="2026-05-20",
        )

        self.assertEqual(result.decision.status, "unknown")
        self.assertFalse(result.fill_inserted)
        self.assertEqual(writer.sqlite_store.count_rows("live_fills"), 0)
        self.assertTrue(result.consistent)
        self.assertEqual(result.order_filled_qty, 0)

    def test_apply_unmatched_snapshot_marks_order_unknown(self) -> None:
        writer = self._writer()
        manager = LiveOrderManager(writer)
        intent = manager.create_intent(self._request())
        snapshot = snapshot_from_kis_daily_order_fill(self._record(), matched=False)

        decision = LiveExecutionSync(writer).apply_order_snapshot(
            order_id=intent.order_id,
            snapshot=snapshot,
            synced_at=self._now(),
            previous_applied_fill_qty=0,
        )

        self.assertEqual(decision.status, "unknown")
        self.assertEqual(writer.sqlite_store.fetch_live_order(intent.order_id)["status"], "unknown")

    def test_reconcile_unknown_order_from_complete_broker_history(self) -> None:
        writer = self._writer()
        intent = self._submitted_order(writer)
        broker = FakeOrderHistoryBroker([
            self._record(filled_qty=10, remaining_qty=0, avg_fill_price=70010.0)
        ])

        result = LiveExecutionSync(writer).recover_open_orders_from_broker(
            trading_day="2026-05-18",
            broker=broker,
            synced_at=self._now() + timedelta(minutes=1),
            settlement_day="2026-05-20",
        )

        self.assertEqual(result.status, "reconciled")
        self.assertEqual(result.reconciled_order_ids, (intent.order_id,))
        self.assertEqual(result.unresolved, ())
        self.assertEqual(writer.sqlite_store.fetch_live_order(intent.order_id)["status"], "filled")
        self.assertEqual(writer.sqlite_store.sum_live_fill_qty(intent.order_id), 10)
        event_types = [row["event_type"] for row in writer.sqlite_store.fetch_all_rows("live_order_events", "event_time")]
        self.assertIn("restart_recovery_unknown", event_types)
        self.assertEqual(len(broker.calls), 1)
        self.assertEqual(broker.calls[0]["start_date"], "20260518")
        self.assertEqual(broker.calls[0]["end_date"], "20260518")

    def test_reconcile_unknown_order_requires_complete_pagination_before_mutation(self) -> None:
        writer = self._writer()
        intent = self._submitted_order(writer)
        broker = FakeOrderHistoryBroker([self._record(filled_qty=10, remaining_qty=0)], pagination_complete=False)

        with self.assertRaises(LiveRecoveryIncompleteError):
            LiveExecutionSync(writer).recover_open_orders_from_broker(
                trading_day="2026-05-18",
                broker=broker,
                synced_at=self._now() + timedelta(minutes=1),
                settlement_day="2026-05-20",
            )

        row = writer.sqlite_store.fetch_live_order(intent.order_id)
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(row["filled_qty"], 0)
        self.assertEqual(writer.sqlite_store.count_rows("live_fills"), 0)

    def test_reconcile_unknown_order_keeps_identity_mismatch_unknown(self) -> None:
        writer = self._writer()
        intent = self._unknown_order(writer)
        broker = FakeOrderHistoryBroker([self._record(symbol="000660")])

        result = LiveExecutionSync(writer).recover_open_orders_from_broker(
            trading_day="2026-05-18",
            broker=broker,
            synced_at=self._now() + timedelta(minutes=1),
            settlement_day="2026-05-20",
        )

        self.assertEqual(result.status, "attention_required")
        self.assertEqual(result.reconciled_order_ids, ())
        self.assertEqual(result.unresolved, ((intent.order_id, "broker_identity_mismatch"),))
        self.assertEqual(writer.sqlite_store.fetch_live_order(intent.order_id)["status"], "unknown")
        self.assertEqual(writer.sqlite_store.count_rows("live_fills"), 0)

    def test_reconcile_unknown_order_does_not_infer_state_when_order_is_absent(self) -> None:
        writer = self._writer()
        intent = self._unknown_order(writer)

        result = LiveExecutionSync(writer).recover_open_orders_from_broker(
            trading_day="2026-05-18",
            broker=FakeOrderHistoryBroker([]),
            synced_at=self._now() + timedelta(minutes=1),
            settlement_day="2026-05-20",
        )

        self.assertEqual(result.status, "attention_required")
        self.assertEqual(result.unresolved, ((intent.order_id, "broker_order_not_found"),))
        self.assertEqual(writer.sqlite_store.fetch_live_order(intent.order_id)["status"], "unknown")
        self.assertEqual(writer.sqlite_store.count_rows("live_fills"), 0)

    def test_reconcile_unknown_orders_rejects_duplicate_local_broker_identity(self) -> None:
        writer = self._writer()
        first = self._unknown_order(writer)
        manager = LiveOrderManager(writer)
        second = manager.create_intent(replace(
            self._request(),
            order_id="order-sync-2",
            prediction_id="prediction-2",
            signal_id="signal-2",
            target_id="target-2",
        ))
        manager.store.update_live_order_transition(
            order_id=second.order_id,
            status="unknown",
            broker_order_no="broker-1",
            broker_branch_no="01",
            reject_reason=None,
            cancel_reason=None,
            submitted_at=self._now(),
            last_synced_at=self._now(),
            detail_json={"order_policy": {}, "blocking_reasons": [], "raw_broker_response": {}},
        )

        result = LiveExecutionSync(writer).recover_open_orders_from_broker(
            trading_day="2026-05-18",
            broker=FakeOrderHistoryBroker([self._record(filled_qty=10, remaining_qty=0)]),
            synced_at=self._now() + timedelta(minutes=1),
            settlement_day="2026-05-20",
        )

        self.assertEqual(
            result.unresolved,
            (
                (first.order_id, "local_broker_identity_ambiguous"),
                (second.order_id, "local_broker_identity_ambiguous"),
            ),
        )
        self.assertEqual(writer.sqlite_store.count_rows("live_fills"), 0)

    def test_reconcile_unknown_order_rejects_non_live_broker_before_query(self) -> None:
        writer = self._writer()
        broker = FakeOrderHistoryBroker([], mode="paper")

        with self.assertRaisesRegex(ValueError, "live profile"):
            LiveExecutionSync(writer).recover_open_orders_from_broker(
                trading_day="2026-05-18",
                broker=broker,
                synced_at=self._now(),
                settlement_day="2026-05-20",
            )

        self.assertEqual(broker.calls, [])


if __name__ == "__main__":
    unittest.main()
