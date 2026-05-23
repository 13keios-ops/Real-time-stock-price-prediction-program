import unittest
from datetime import datetime, timedelta, timezone

from app.services.market_data_freshness import evaluate_market_data_freshness


class MarketDataFreshnessTests(unittest.TestCase):
    def _now(self) -> datetime:
        return datetime(2026, 5, 18, 1, 0, tzinfo=timezone.utc)

    def test_all_required_inputs_fresh_allows_submit_preflight(self) -> None:
        now = self._now()

        decision = evaluate_market_data_freshness(
            now=now,
            latest_trade_at=now - timedelta(seconds=5),
            latest_orderbook_at=now - timedelta(seconds=8),
            latest_bar_at=now - timedelta(seconds=60),
            latest_prediction_at=now - timedelta(seconds=70),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.blocking_reasons, ())
        self.assertEqual(decision.ages_seconds["trade_tick"], 5.0)

    def test_stale_prediction_blocks_submit_preflight(self) -> None:
        now = self._now()

        decision = evaluate_market_data_freshness(
            now=now,
            latest_trade_at=now - timedelta(seconds=5),
            latest_orderbook_at=now - timedelta(seconds=8),
            latest_bar_at=now - timedelta(seconds=60),
            latest_prediction_at=now - timedelta(seconds=121),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("prediction_stale", decision.blocking_reasons)

    def test_missing_required_input_blocks_but_optional_input_does_not(self) -> None:
        now = self._now()

        decision = evaluate_market_data_freshness(
            now=now,
            latest_trade_at=now - timedelta(seconds=5),
            latest_orderbook_at=None,
            latest_bar_at=now - timedelta(seconds=60),
            latest_prediction_at=None,
            require_orderbook=False,
        )

        self.assertFalse(decision.allowed)
        self.assertNotIn("orderbook_tick_missing", decision.blocking_reasons)
        self.assertIn("prediction_missing", decision.blocking_reasons)

    def test_timestamp_from_future_blocks_when_beyond_tolerance(self) -> None:
        now = self._now()

        decision = evaluate_market_data_freshness(
            now=now,
            latest_trade_at=now + timedelta(seconds=3),
            latest_orderbook_at=now - timedelta(seconds=8),
            latest_bar_at=now - timedelta(seconds=60),
            latest_prediction_at=now - timedelta(seconds=70),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("trade_tick_from_future", decision.blocking_reasons)


if __name__ == "__main__":
    unittest.main()
