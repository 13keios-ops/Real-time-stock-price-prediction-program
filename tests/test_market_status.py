from datetime import datetime, timezone
import unittest

from app.services.market_status import evaluate_market_status, evaluate_market_status_batch
from app.storage.contracts import MarketStatusSnapshot


class MarketStatusTests(unittest.TestCase):
    def _now(self) -> datetime:
        return datetime(2026, 5, 14, 9, 5, tzinfo=timezone.utc)

    def _snapshot(
        self,
        *,
        market_session: str = "regular",
        symbols: dict[str, dict[str, object]] | None = None,
        stale_after: datetime | None = None,
    ) -> MarketStatusSnapshot:
        return MarketStatusSnapshot(
            snapshot_id="market-status-1",
            trading_day="2026-05-14",
            created_at=self._now(),
            source="manual_fixture",
            symbol_set_hash="hash-1",
            status_json={
                "symbols": symbols if symbols is not None else {"005930": {"tradable": True}},
                "market_session": market_session,
                "source_generated_at": self._now().isoformat(),
            },
            stale_after=stale_after or datetime(2026, 5, 14, 9, 10, tzinfo=timezone.utc),
        )

    def test_regular_tradable_symbol_is_allowed(self) -> None:
        decision = evaluate_market_status(self._snapshot(), "005930", now=self._now())

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.blocking_reasons, ())
        self.assertEqual(decision.market_session, "regular")
        self.assertFalse(decision.stale)

    def test_stale_snapshot_blocks_new_orders(self) -> None:
        snapshot = self._snapshot(stale_after=datetime(2026, 5, 14, 9, 4, tzinfo=timezone.utc))

        decision = evaluate_market_status(snapshot, "005930", now=self._now())

        self.assertFalse(decision.allowed)
        self.assertIn("market_status_stale", decision.blocking_reasons)

    def test_non_regular_session_blocks_new_orders(self) -> None:
        for market_session in ("pre_open_call_auction", "closing_call_auction", "after_hours_single_price", "closed"):
            with self.subTest(market_session=market_session):
                decision = evaluate_market_status(self._snapshot(market_session=market_session), "005930", now=self._now())

                self.assertFalse(decision.allowed)
                self.assertIn("market_session_not_allowed", decision.blocking_reasons)

    def test_missing_symbol_status_blocks_new_orders(self) -> None:
        decision = evaluate_market_status(self._snapshot(symbols={}), "005930", now=self._now())

        self.assertFalse(decision.allowed)
        self.assertIn("symbol_status_missing", decision.blocking_reasons)

    def test_symbol_microstructure_flags_block_new_orders(self) -> None:
        cases = (
            ({"tradable": False}, "not_tradable"),
            ({"tradable": True, "suspended": True}, "trading_suspended"),
            ({"tradable": True, "management": True}, "management_issue"),
            ({"tradable": True, "investment_warning": True}, "investment_warning"),
            ({"tradable": True, "upper_limit": True}, "price_limit_blocked"),
            ({"tradable": True, "lower_limit": True}, "price_limit_blocked"),
            ({"tradable": True, "near_price_limit": True}, "price_limit_blocked"),
            ({"tradable": True, "vi_active": True}, "vi_active"),
            ({"tradable": True, "single_price_auction": True}, "single_price_auction"),
            ({"tradable": True, "corporate_action": True}, "corporate_action"),
            ({}, "tradable_unknown"),
        )
        for symbol_status, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                snapshot = self._snapshot(symbols={"005930": symbol_status})

                decision = evaluate_market_status(snapshot, "005930", now=self._now())

                self.assertFalse(decision.allowed)
                self.assertIn(expected_reason, decision.blocking_reasons)

    def test_truthy_microstructure_flags_block_new_orders(self) -> None:
        snapshot = self._snapshot(symbols={"005930": {"tradable": True, "vi_active": 1}})

        decision = evaluate_market_status(snapshot, "005930", now=self._now())

        self.assertFalse(decision.allowed)
        self.assertIn("vi_active", decision.blocking_reasons)

    def test_symbol_session_override_blocks_new_orders(self) -> None:
        snapshot = self._snapshot(
            symbols={"005930": {"tradable": True, "market_session": "single_price_auction"}}
        )

        decision = evaluate_market_status(snapshot, "005930", now=self._now())

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.market_session, "single_price_auction")
        self.assertIn("market_session_not_allowed", decision.blocking_reasons)

    def test_batch_evaluation_returns_symbol_decisions(self) -> None:
        snapshot = self._snapshot(
            symbols={
                "005930": {"tradable": True},
                "000660": {"tradable": True, "vi_active": True},
            }
        )

        decisions = evaluate_market_status_batch(snapshot, ["005930", "000660"], now=self._now())

        self.assertTrue(decisions["005930"].allowed)
        self.assertFalse(decisions["000660"].allowed)
        self.assertIn("vi_active", decisions["000660"].blocking_reasons)


if __name__ == "__main__":
    unittest.main()
