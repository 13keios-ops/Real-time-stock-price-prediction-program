import unittest
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.live_kill_switch import LiveKillSwitch
from app.services.live_order_guard import LiveOrderGuard, LiveOrderGuardError
from app.services.market_data_freshness import evaluate_market_data_freshness
from app.services.market_status import evaluate_market_status
from app.services.system_clock import evaluate_clock_skew
from app.storage.contracts import MarketStatusSnapshot


@dataclass(slots=True)
class FakeSettings:
    trading_mode: str
    allow_live_orders: bool


class LiveOrderGuardTests(unittest.TestCase):
    def _now(self) -> datetime:
        return datetime(2026, 5, 15, 15, 45, tzinfo=timezone.utc)

    def _path(self) -> Path:
        root = Path(__file__).resolve().parents[1]
        return root / ".tmp-tests" / "live-order-guard" / str(uuid.uuid4()) / "kill-switch.json"

    def _kill_switch_state(self, *, enabled: bool = False):
        switch = LiveKillSwitch(self._path())
        return switch.write_state(
            enabled=enabled,
            reason="fixture",
            actor="system",
            now=self._now(),
            stale_after=self._now() + timedelta(hours=1),
        )

    def _market_decision(self, *, tradable: bool = True, vi_active: bool = False):
        snapshot = MarketStatusSnapshot(
            snapshot_id="market-status-1",
            trading_day="2026-05-15",
            created_at=self._now(),
            source="manual_fixture",
            symbol_set_hash="hash-1",
            status_json={
                "symbols": {"005930": {"tradable": tradable, "vi_active": vi_active}},
                "market_session": "regular",
                "source_generated_at": self._now().isoformat(),
            },
            stale_after=self._now() + timedelta(minutes=5),
        )
        return evaluate_market_status(snapshot, "005930", now=self._now())

    def _real_ws_evidence_type(self) -> str:
        return "real_kis_ws_observed"

    def test_live_readonly_allows_disabled_live_orders_but_submit_blocks(self) -> None:
        settings = FakeSettings(trading_mode="live", allow_live_orders=False)

        decision = LiveOrderGuard.assert_readonly(settings, "phase1_readonly")

        self.assertTrue(decision.allowed)
        with self.assertRaisesRegex(LiveOrderGuardError, "live_orders_disabled"):
            LiveOrderGuard.assert_can_submit(
                settings,
                "phase2_conservative",
                "live",
                self._kill_switch_state(enabled=False),
                market_status_decision=self._market_decision(),
                phase_approved=True,
            )

    def test_submit_allowed_when_all_guards_are_green(self) -> None:
        settings = FakeSettings(trading_mode="live", allow_live_orders=True)

        decision = LiveOrderGuard.assert_can_submit(
            settings,
            "phase2_conservative",
            "live",
            self._kill_switch_state(enabled=False),
            market_status_decision=self._market_decision(),
            phase_approved=True,
            ws_recovery_evidence_type=self._real_ws_evidence_type(),
        )

        self.assertTrue(decision.allowed)

    def test_submit_phase_requires_real_ws_recovery_evidence(self) -> None:
        settings = FakeSettings(trading_mode="live", allow_live_orders=True)

        with self.assertRaises(LiveOrderGuardError) as missing:
            LiveOrderGuard.assert_can_submit(
                settings,
                "phase2_conservative",
                "live",
                self._kill_switch_state(enabled=False),
                market_status_decision=self._market_decision(),
                phase_approved=True,
            )
        with self.assertRaises(LiveOrderGuardError) as synthetic:
            LiveOrderGuard.assert_can_submit(
                settings,
                "phase2_conservative",
                "live",
                self._kill_switch_state(enabled=False),
                market_status_decision=self._market_decision(),
                phase_approved=True,
                ws_recovery_evidence_type="synthetic_fault_injection",
            )

        self.assertIn("ws_recovery_real_evidence_required", missing.exception.blocking_reasons)
        self.assertIn("ws_recovery_real_evidence_required", synthetic.exception.blocking_reasons)

    def test_submit_requires_live_mode_profile_phase_approval_and_limit_order(self) -> None:
        settings = FakeSettings(trading_mode="paper", allow_live_orders=True)

        with self.assertRaises(LiveOrderGuardError) as caught:
            LiveOrderGuard.assert_can_submit(
                settings,
                "phase1_readonly",
                "paper",
                self._kill_switch_state(enabled=False),
                market_status_decision=self._market_decision(),
                phase_approved=False,
                order_type="market",
            )

        self.assertIn("trading_mode_not_live", caught.exception.blocking_reasons)
        self.assertIn("profile_mode_not_live", caught.exception.blocking_reasons)
        self.assertIn("phase_readonly", caught.exception.blocking_reasons)
        self.assertIn("phase_not_approved", caught.exception.blocking_reasons)
        self.assertIn("order_type_not_allowed", caught.exception.blocking_reasons)

    def test_kill_switch_blocks_submit_but_cancel_is_allowed(self) -> None:
        settings = FakeSettings(trading_mode="live", allow_live_orders=True)
        kill_switch_state = self._kill_switch_state(enabled=True)

        with self.assertRaisesRegex(LiveOrderGuardError, "kill_switch_enabled"):
            LiveOrderGuard.assert_can_submit(
                settings,
                "phase2_conservative",
                "live",
                kill_switch_state,
                market_status_decision=self._market_decision(),
                phase_approved=True,
            )

        decision = LiveOrderGuard.assert_can_cancel(
            settings,
            "phase2_conservative",
            "live",
            kill_switch_state,
        )
        self.assertTrue(decision.allowed)

    def test_missing_and_stale_kill_switch_block_submit_but_allow_cancel(self) -> None:
        settings = FakeSettings(trading_mode="live", allow_live_orders=True)
        states = [LiveKillSwitch(self._path()).read_state(now=self._now())]
        stale_switch = LiveKillSwitch(self._path())
        stale_switch.write_state(
            enabled=False,
            reason="old_state",
            actor="system",
            now=self._now() - timedelta(hours=2),
            stale_after=self._now() - timedelta(hours=1),
        )
        states.append(stale_switch.read_state(now=self._now()))

        for state in states:
            with self.subTest(status=state.status):
                with self.assertRaises(LiveOrderGuardError):
                    LiveOrderGuard.assert_can_submit(
                        settings,
                        "phase2_conservative",
                        "live",
                        state,
                        market_status_decision=self._market_decision(),
                        phase_approved=True,
                    )
                self.assertTrue(
                    LiveOrderGuard.assert_can_cancel(
                        settings,
                        "phase2_conservative",
                        "live",
                        state,
                    ).allowed
                )

    def test_market_status_blocks_submit(self) -> None:
        settings = FakeSettings(trading_mode="live", allow_live_orders=True)

        with self.assertRaises(LiveOrderGuardError) as caught:
            LiveOrderGuard.assert_can_submit(
                settings,
                "phase2_conservative",
                "live",
                self._kill_switch_state(enabled=False),
                market_status_decision=self._market_decision(vi_active=True),
                phase_approved=True,
            )

        self.assertIn("vi_active", caught.exception.blocking_reasons)

    def test_system_clock_skew_blocks_submit_when_decision_is_supplied(self) -> None:
        settings = FakeSettings(trading_mode="live", allow_live_orders=True)
        skew_decision = evaluate_clock_skew(
            local_time=self._now(),
            reference_time=self._now() + timedelta(seconds=3),
        )

        with self.assertRaises(LiveOrderGuardError) as caught:
            LiveOrderGuard.assert_can_submit(
                settings,
                "phase2_conservative",
                "live",
                self._kill_switch_state(enabled=False),
                market_status_decision=self._market_decision(),
                phase_approved=True,
                clock_skew_decision=skew_decision,
            )

        self.assertIn("system_clock_skew_exceeded", caught.exception.blocking_reasons)

    def test_system_clock_check_can_be_required_for_submit(self) -> None:
        settings = FakeSettings(trading_mode="live", allow_live_orders=True)

        with self.assertRaises(LiveOrderGuardError) as caught:
            LiveOrderGuard.assert_can_submit(
                settings,
                "phase2_conservative",
                "live",
                self._kill_switch_state(enabled=False),
                market_status_decision=self._market_decision(),
                phase_approved=True,
                require_clock_skew_check=True,
            )

        self.assertIn("system_clock_check_missing", caught.exception.blocking_reasons)

    def test_market_data_freshness_blocks_submit_when_supplied_stale(self) -> None:
        settings = FakeSettings(trading_mode="live", allow_live_orders=True)
        now = self._now()
        freshness_decision = evaluate_market_data_freshness(
            now=now,
            latest_trade_at=now - timedelta(seconds=5),
            latest_orderbook_at=now - timedelta(seconds=8),
            latest_bar_at=now - timedelta(seconds=60),
            latest_prediction_at=now - timedelta(seconds=121),
        )

        with self.assertRaises(LiveOrderGuardError) as caught:
            LiveOrderGuard.assert_can_submit(
                settings,
                "phase2_conservative",
                "live",
                self._kill_switch_state(enabled=False),
                market_status_decision=self._market_decision(),
                phase_approved=True,
                market_data_freshness_decision=freshness_decision,
            )

        self.assertIn("prediction_stale", caught.exception.blocking_reasons)

    def test_market_data_freshness_check_can_be_required_for_submit(self) -> None:
        settings = FakeSettings(trading_mode="live", allow_live_orders=True)

        with self.assertRaises(LiveOrderGuardError) as caught:
            LiveOrderGuard.assert_can_submit(
                settings,
                "phase2_conservative",
                "live",
                self._kill_switch_state(enabled=False),
                market_status_decision=self._market_decision(),
                phase_approved=True,
                require_market_data_freshness_check=True,
            )

        self.assertIn("market_data_freshness_check_missing", caught.exception.blocking_reasons)

    def test_unknown_phase_blocks_submit_instead_of_bypassing_readonly_policy(self) -> None:
        settings = FakeSettings(trading_mode="live", allow_live_orders=True)

        with self.assertRaises(LiveOrderGuardError) as caught:
            LiveOrderGuard.assert_can_submit(
                settings,
                "phase2-conservativ-typo",
                "live",
                self._kill_switch_state(enabled=False),
                market_status_decision=self._market_decision(),
                phase_approved=True,
            )

        self.assertIn("phase_unknown", caught.exception.blocking_reasons)


if __name__ == "__main__":
    unittest.main()
