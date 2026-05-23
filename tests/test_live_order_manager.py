import json
import unittest
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.live_kill_switch import LiveKillSwitch
from app.services.live_order_manager import (
    BrokerCancelResult,
    BrokerSubmitResult,
    LiveOrderIntentRequest,
    LiveOrderManager,
)
from app.services.market_status import evaluate_market_status
from app.services.system_clock import evaluate_clock_skew_from_http_date_header
from app.storage.contracts import MarketStatusSnapshot
from app.storage.jsonl_store import JsonlArtifactStore
from app.storage.runtime_writer import RuntimeWriter
from app.storage.sqlite_store import SQLiteRuntimeStore


@dataclass(slots=True)
class FakeSettings:
    trading_mode: str = "live"
    allow_live_orders: bool = True


class FakeSubmitBroker:
    def __init__(self, result: BrokerSubmitResult | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def submit_cash_order(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeCancelBroker:
    def __init__(self, result: BrokerCancelResult | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def cancel_order(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class LiveOrderManagerTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1] / ".tmp-tests" / "live-order-manager" / str(uuid.uuid4())

    def _now(self) -> datetime:
        return datetime(2026, 5, 16, 0, 30, tzinfo=timezone.utc)

    def _writer(self) -> RuntimeWriter:
        root = self._root()
        return RuntimeWriter(
            jsonl_store=JsonlArtifactStore(root / "runtime-data"),
            sqlite_store=SQLiteRuntimeStore(root / "dev.db"),
        )

    def _manager(self) -> LiveOrderManager:
        return LiveOrderManager(self._writer())

    def _request(
        self,
        *,
        order_id: str | None = None,
        symbol: str = "005930",
        qty: int = 1,
        limit_price: float = 70000.0,
        prediction_id: str = "prediction-1",
        signal_id: str = "signal-1",
        target_id: str = "target-1",
        gate_decision_id: str = "gate-1",
        phase: str = "phase2_conservative",
        order_policy: dict[str, object] | None = None,
    ) -> LiveOrderIntentRequest:
        return LiveOrderIntentRequest(
            order_id=order_id,
            trading_day="2026-05-18",
            phase=phase,
            symbol=symbol,
            side="buy",
            qty=qty,
            order_type="limit",
            limit_price=limit_price,
            prediction_id=prediction_id,
            signal_id=signal_id,
            target_id=target_id,
            gate_decision_id=gate_decision_id,
            market_status_snapshot_id="market-status-1",
            model_version="model-1",
            rule_version="rule-1",
            created_at=self._now(),
            order_policy=order_policy or {"type": "phase2_limit_only"},
        )

    def _kill_switch_state(self, manager: LiveOrderManager, *, enabled: bool = False):
        path = manager.store.database_path.parent / "runtime-data" / "reports" / "live-risk" / "kill-switch.json"
        return LiveKillSwitch(path).write_state(
            enabled=enabled,
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

    def _real_ws_evidence_type(self) -> str:
        return "real_kis_ws_observed"

    def test_create_intent_is_idempotent(self) -> None:
        manager = self._manager()
        request = self._request()

        first = manager.create_intent(request)
        second = manager.create_intent(request)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.order_id, second.order_id)
        self.assertEqual(manager.store.count_rows("live_orders"), 1)
        self.assertEqual(manager.store.count_rows("live_order_events"), 1)

    def test_create_intent_rejects_missing_traceability_fields_without_writing(self) -> None:
        manager = self._manager()

        with self.assertRaisesRegex(ValueError, "prediction_id"):
            manager.create_intent(self._request(prediction_id=""))

        self.assertEqual(manager.store.count_rows("live_orders"), 0)
        self.assertEqual(manager.store.count_rows("live_order_events"), 0)

    def test_create_intent_rejects_invalid_qty_and_limit_price_without_writing(self) -> None:
        manager = self._manager()

        with self.assertRaisesRegex(ValueError, "qty"):
            manager.create_intent(self._request(qty=0))
        with self.assertRaisesRegex(ValueError, "limit_price"):
            manager.create_intent(self._request(limit_price=0.0))

        self.assertEqual(manager.store.count_rows("live_orders"), 0)
        self.assertEqual(manager.store.count_rows("live_order_events"), 0)

    def test_submit_transitions_through_guard_and_broker_response(self) -> None:
        manager = self._manager()
        intent = manager.create_intent(self._request(order_id="order-submit-ok"))
        broker = FakeSubmitBroker(
            BrokerSubmitResult(
                accepted=True,
                status="submitted",
                broker_order_no="broker-1",
                broker_branch_no="01",
                raw_response={"rt_cd": "0"},
            )
        )

        result = manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(manager),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=broker,
            submitted_at=self._now(),
            ws_recovery_evidence_type=self._real_ws_evidence_type(),
        )

        row = manager.store.fetch_live_order(intent.order_id)
        self.assertEqual(result.status, "submitted")
        self.assertEqual(row["status"], "submitted")
        self.assertEqual(row["broker_order_no"], "broker-1")
        self.assertEqual(len(broker.calls), 1)
        self.assertEqual(manager.store.count_rows("live_order_events"), 3)

    def test_submit_redacts_sensitive_raw_response_before_persisting(self) -> None:
        manager = self._manager()
        intent = manager.create_intent(self._request(order_id="order-submit-redact"))
        broker = FakeSubmitBroker(
            BrokerSubmitResult(
                accepted=True,
                status="submitted",
                broker_order_no="broker-redact-1",
                broker_branch_no="01",
                raw_response={
                    "rt_cd": "0",
                    "account_number": "1234567890",
                    "app_secret": "secret-value",
                    "pdno": "005930",
                },
            )
        )

        result = manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(manager),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=broker,
            submitted_at=self._now(),
            ws_recovery_evidence_type=self._real_ws_evidence_type(),
        )

        self.assertEqual(result.raw_response["account_number"], "<REDACTED>")
        self.assertEqual(result.raw_response["app_secret"], "<REDACTED>")
        row = manager.store.fetch_live_order(intent.order_id)
        detail = json.loads(row["detail_json"])
        self.assertEqual(detail["raw_broker_response"]["account_number"], "<REDACTED>")
        self.assertEqual(detail["raw_broker_response"]["app_secret"], "<REDACTED>")
        self.assertEqual(detail["raw_broker_response"]["pdno"], "005930")
        events = manager.store.fetch_all_rows("live_order_events", "event_time")
        raw_response = json.loads(events[-1]["detail_json"])["raw_broker_response"]
        self.assertEqual(raw_response["account_number"], "<REDACTED>")
        self.assertEqual(raw_response["app_secret"], "<REDACTED>")

    def test_submit_guard_block_marks_order_blocked_without_broker_call(self) -> None:
        manager = self._manager()
        intent = manager.create_intent(self._request(order_id="order-submit-blocked"))
        broker = FakeSubmitBroker(BrokerSubmitResult(accepted=True, status="submitted", broker_order_no="broker-1"))

        result = manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(trading_mode="paper", allow_live_orders=False),
            profile_mode="paper",
            kill_switch_state=self._kill_switch_state(manager),
            market_status_decision=self._market_decision(),
            phase_approved=False,
            broker=broker,
            submitted_at=self._now(),
        )

        row = manager.store.fetch_live_order(intent.order_id)
        detail = json.loads(row["detail_json"])
        self.assertEqual(result.status, "blocked")
        self.assertEqual(row["status"], "blocked")
        self.assertEqual(broker.calls, [])
        self.assertIn("live_orders_disabled", detail["blocking_reasons"])

    def test_submit_blocks_synthetic_ws_recovery_evidence_without_broker_call(self) -> None:
        manager = self._manager()
        intent = manager.create_intent(self._request(order_id="order-submit-synthetic-ws"))
        broker = FakeSubmitBroker(BrokerSubmitResult(accepted=True, status="submitted", broker_order_no="broker-1"))

        result = manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(manager),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=broker,
            submitted_at=self._now(),
            ws_recovery_evidence_type="synthetic_fault_injection",
        )

        detail = json.loads(manager.store.fetch_live_order(intent.order_id)["detail_json"])
        self.assertEqual(result.status, "blocked")
        self.assertEqual(broker.calls, [])
        self.assertIn("ws_recovery_real_evidence_required", detail["blocking_reasons"])

    def test_submit_can_require_system_clock_check_before_broker_call(self) -> None:
        manager = self._manager()
        intent = manager.create_intent(self._request(order_id="order-submit-clock-missing"))
        broker = FakeSubmitBroker(BrokerSubmitResult(accepted=True, status="submitted", broker_order_no="broker-1"))

        result = manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(manager),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=broker,
            submitted_at=self._now(),
            require_clock_skew_check=True,
        )

        detail = json.loads(manager.store.fetch_live_order(intent.order_id)["detail_json"])
        self.assertEqual(result.status, "blocked")
        self.assertEqual(broker.calls, [])
        self.assertIn("system_clock_check_missing", detail["blocking_reasons"])

    def test_submit_accepts_system_clock_decision_from_kis_http_date_header(self) -> None:
        manager = self._manager()
        intent = manager.create_intent(self._request(order_id="order-submit-clock-ok"))
        broker = FakeSubmitBroker(BrokerSubmitResult(accepted=True, status="submitted", broker_order_no="broker-1"))
        clock_decision = evaluate_clock_skew_from_http_date_header(
            {"date": "Sat, 16 May 2026 00:29:59 GMT"},
            local_time=self._now(),
        )

        result = manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(manager),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=broker,
            submitted_at=self._now(),
            clock_skew_decision=clock_decision,
            require_clock_skew_check=True,
            ws_recovery_evidence_type=self._real_ws_evidence_type(),
        )

        self.assertEqual(result.status, "submitted")
        self.assertEqual(len(broker.calls), 1)

    def test_submit_blocks_system_clock_decision_from_stale_http_date_header(self) -> None:
        manager = self._manager()
        intent = manager.create_intent(self._request(order_id="order-submit-clock-stale"))
        broker = FakeSubmitBroker(BrokerSubmitResult(accepted=True, status="submitted", broker_order_no="broker-1"))
        clock_decision = evaluate_clock_skew_from_http_date_header(
            {"date": "Sat, 16 May 2026 00:29:55 GMT"},
            local_time=self._now(),
        )

        result = manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(manager),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=broker,
            submitted_at=self._now(),
            clock_skew_decision=clock_decision,
            require_clock_skew_check=True,
        )

        detail = json.loads(manager.store.fetch_live_order(intent.order_id)["detail_json"])
        self.assertEqual(result.status, "blocked")
        self.assertEqual(broker.calls, [])
        self.assertIn("system_clock_skew_exceeded", detail["blocking_reasons"])

    def test_phase2_blocks_second_parent_order_for_same_trading_day(self) -> None:
        manager = self._manager()

        first = manager.create_intent(self._request(order_id="order-parent-1", symbol="005930"))
        second = manager.create_intent(
            self._request(
                order_id="order-parent-2",
                symbol="000660",
                prediction_id="prediction-2",
                signal_id="signal-2",
                target_id="target-2",
                gate_decision_id="gate-2",
            )
        )

        second_row = manager.store.fetch_live_order(second.order_id)
        detail = json.loads(second_row["detail_json"])
        self.assertEqual(first.status, "intent_created")
        self.assertEqual(second.status, "blocked")
        self.assertIn("phase2_parent_order_limit_exceeded", second.blocking_reasons)
        self.assertIn("phase2_parent_order_limit_exceeded", detail["blocking_reasons"])
        self.assertEqual(detail["pre_submit_policy_context"]["parent_order_count"], 1)
        self.assertEqual(detail["pre_submit_policy_context"]["max_parent_orders_per_day"], 1)
        self.assertEqual(
            detail["pre_submit_policy_context"]["phase2_parent_order_limit_exceeded"],
            {"current": 1, "limit": 1},
        )

    def test_phase2_canary_uses_phase2_pre_submit_policy_defaults(self) -> None:
        manager = self._manager()

        first = manager.create_intent(self._request(order_id="order-canary-parent-1", phase="phase2_canary"))
        second = manager.create_intent(
            self._request(
                order_id="order-canary-parent-2",
                phase="phase2_canary",
                symbol="000660",
                prediction_id="prediction-canary-2",
                signal_id="signal-canary-2",
                target_id="target-canary-2",
                gate_decision_id="gate-canary-2",
            )
        )

        self.assertEqual(first.status, "intent_created")
        self.assertEqual(second.status, "blocked")
        self.assertIn("phase2_parent_order_limit_exceeded", second.blocking_reasons)

    def test_phase2_blocks_parent_order_above_default_notional_limit(self) -> None:
        manager = self._manager()

        result = manager.create_intent(self._request(order_id="order-notional-block", qty=2, limit_price=70000.0))

        row = manager.store.fetch_live_order(result.order_id)
        detail = json.loads(row["detail_json"])
        self.assertEqual(result.status, "blocked")
        self.assertIn("phase2_order_qty_limit_exceeded", result.blocking_reasons)
        self.assertIn("phase2_order_notional_limit_exceeded", result.blocking_reasons)
        self.assertEqual(detail["pre_submit_policy_context"]["phase2_order_qty_limit_exceeded"], {"current": 2, "limit": 1})
        self.assertEqual(detail["pre_submit_policy_context"]["order_notional"], 140000.0)
        self.assertEqual(detail["pre_submit_policy_context"]["effective_max_order_notional"], 100000.0)

    def test_phase2_blocks_multiple_shares_even_when_notional_is_within_limit(self) -> None:
        manager = self._manager()

        result = manager.create_intent(self._request(order_id="order-qty-block", qty=2, limit_price=50000.0))

        row = manager.store.fetch_live_order(result.order_id)
        detail = json.loads(row["detail_json"])
        self.assertEqual(result.status, "blocked")
        self.assertIn("phase2_order_qty_limit_exceeded", result.blocking_reasons)
        self.assertNotIn("phase2_order_notional_limit_exceeded", result.blocking_reasons)
        self.assertEqual(detail["pre_submit_policy_context"]["phase2_order_qty_limit_exceeded"], {"current": 2, "limit": 1})

    def test_phase2_order_notional_limit_can_be_adjusted_by_order_policy(self) -> None:
        manager = self._manager()
        policy = {
            "type": "phase2_limit_only",
            "max_order_qty": 2,
            "max_order_notional": 200000,
            "allocation_amount": 500000,
            "max_order_allocation_pct": 0.5,
        }

        result = manager.create_intent(
            self._request(order_id="order-notional-allowed", qty=2, limit_price=70000.0, order_policy=policy)
        )

        row = manager.store.fetch_live_order(result.order_id)
        detail = json.loads(row["detail_json"])
        self.assertEqual(result.status, "intent_created")
        self.assertEqual(detail["pre_submit_policy_context"]["order_notional"], 140000.0)
        self.assertEqual(detail["pre_submit_policy_context"]["effective_max_order_notional"], 200000.0)

    def test_phase2_allocation_pct_can_tighten_order_notional_limit(self) -> None:
        manager = self._manager()
        policy = {
            "type": "phase2_limit_only",
            "max_order_notional": 200000,
            "allocation_amount": 500000,
            "max_order_allocation_pct": 0.1,
        }

        result = manager.create_intent(
            self._request(order_id="order-notional-allocation-block", qty=1, limit_price=70000.0, order_policy=policy)
        )

        row = manager.store.fetch_live_order(result.order_id)
        detail = json.loads(row["detail_json"])
        self.assertEqual(result.status, "blocked")
        self.assertIn("phase2_order_notional_limit_exceeded", result.blocking_reasons)
        self.assertEqual(detail["pre_submit_policy_context"]["effective_max_order_notional"], 50000.0)

    def test_phase2_blocks_same_symbol_pending_when_parent_limit_allows_more(self) -> None:
        manager = self._manager()
        policy = {
            "type": "phase2_limit_only",
            "max_parent_orders_per_day": 5,
            "block_same_symbol_pending": True,
        }

        first = manager.create_intent(self._request(order_id="order-symbol-1", order_policy=policy))
        second = manager.create_intent(
            self._request(
                order_id="order-symbol-2",
                prediction_id="prediction-2",
                signal_id="signal-2",
                target_id="target-2",
                gate_decision_id="gate-2",
                order_policy=policy,
            )
        )

        self.assertEqual(first.status, "intent_created")
        self.assertEqual(second.status, "blocked")
        self.assertNotIn("phase2_parent_order_limit_exceeded", second.blocking_reasons)
        self.assertIn("same_symbol_order_pending", second.blocking_reasons)

    def test_phase2_blocks_new_intent_when_live_fill_mismatch_exists(self) -> None:
        manager = self._manager()
        policy = {
            "type": "phase2_limit_only",
            "max_parent_orders_per_day": 5,
            "block_same_symbol_pending": True,
            "block_live_fill_mismatch": True,
        }
        first = manager.create_intent(self._request(order_id="order-mismatch-1", symbol="005930", order_policy=policy))
        manager.store.update_live_order_transition(
            order_id=first.order_id,
            status="filled",
            filled_qty=3,
            remaining_qty=0,
            avg_fill_price=70000.0,
            broker_order_no="broker-mismatch-1",
            broker_branch_no="01",
            reject_reason=None,
            cancel_reason=None,
            submitted_at=self._now(),
            last_synced_at=self._now(),
            detail_json={"order_policy": policy, "blocking_reasons": [], "raw_broker_response": {}},
        )

        second = manager.create_intent(
            self._request(
                order_id="order-mismatch-2",
                symbol="000660",
                prediction_id="prediction-2",
                signal_id="signal-2",
                target_id="target-2",
                gate_decision_id="gate-2",
                order_policy=policy,
            )
        )

        row = manager.store.fetch_live_order(second.order_id)
        detail = json.loads(row["detail_json"])
        self.assertEqual(second.status, "blocked")
        self.assertIn("live_fill_mismatch_detected", second.blocking_reasons)
        self.assertIn("live_fill_mismatch_detected", detail["blocking_reasons"])

    def test_submit_exception_marks_unknown(self) -> None:
        manager = self._manager()
        intent = manager.create_intent(self._request(order_id="order-submit-unknown"))

        result = manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(manager),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=FakeSubmitBroker(RuntimeError("network split")),
            submitted_at=self._now(),
            ws_recovery_evidence_type=self._real_ws_evidence_type(),
        )

        row = manager.store.fetch_live_order(intent.order_id)
        self.assertEqual(result.status, "unknown")
        self.assertEqual(row["status"], "unknown")

    def test_cancel_is_allowed_while_kill_switch_blocks_new_submit(self) -> None:
        manager = self._manager()
        intent = manager.create_intent(self._request(order_id="order-cancel"))
        manager.submit_intent(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(manager),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            broker=FakeSubmitBroker(
                BrokerSubmitResult(
                    accepted=True,
                    status="open",
                    broker_order_no="broker-2",
                    broker_branch_no="01",
                )
            ),
            submitted_at=self._now(),
            ws_recovery_evidence_type=self._real_ws_evidence_type(),
        )

        result = manager.request_cancel(
            order_id=intent.order_id,
            settings=FakeSettings(),
            profile_mode="live",
            kill_switch_state=self._kill_switch_state(manager, enabled=True),
            broker=FakeCancelBroker(BrokerCancelResult(accepted=True, raw_response={"rt_cd": "0"})),
            requested_at=self._now(),
            reason="unit_test_cancel",
        )

        self.assertEqual(result.status, "cancel_requested")
        self.assertEqual(manager.store.fetch_live_order(intent.order_id)["status"], "cancel_requested")

    def test_recover_open_orders_marks_inflight_orders_unknown(self) -> None:
        manager = self._manager()
        intent = manager.create_intent(self._request(order_id="order-recover"))
        manager.store.update_live_order_transition(
            order_id=intent.order_id,
            status="open",
            broker_order_no="broker-3",
            broker_branch_no="01",
            reject_reason=None,
            cancel_reason=None,
            submitted_at=self._now(),
            last_synced_at=self._now(),
            detail_json={"order_policy": {}, "blocking_reasons": [], "raw_broker_response": {}},
        )

        results = manager.recover_open_orders(trading_day="2026-05-18", recovered_at=self._now())

        self.assertEqual([(item.order_id, item.status) for item in results], [(intent.order_id, "unknown")])
        self.assertEqual(manager.store.fetch_live_order(intent.order_id)["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
