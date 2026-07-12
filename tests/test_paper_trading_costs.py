from datetime import datetime
import unittest

from app.paper_trading.costs import (
    DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE,
    DOMESTIC_STOCK_COST_MODEL_VERSION,
    LEGACY_OR_CUSTOM_COST_MODEL_VERSION,
    build_domestic_stock_cost_model_metadata,
    calculate_domestic_stock_fill_tax,
    estimate_round_trip_cost_pct,
)
from app.paper_trading.engine import PaperTradingEngine
from app.storage.contracts import PaperOrder
from app.utils.time import get_timezone


class PaperTradingCostTests(unittest.TestCase):
    def test_current_common_stock_round_trip_cost_is_029_pct_at_3bps_slippage(self) -> None:
        self.assertAlmostEqual(
            estimate_round_trip_cost_pct(slippage_bps=3.0),
            0.29,
        )

    def test_domestic_stock_tax_is_sell_only(self) -> None:
        self.assertEqual(
            calculate_domestic_stock_fill_tax(side="buy", gross_notional=100_000.0),
            0.0,
        )
        self.assertEqual(
            calculate_domestic_stock_fill_tax(side="sell", gross_notional=100_000.0),
            200.0,
        )

    def test_cost_metadata_distinguishes_current_and_legacy_totals(self) -> None:
        current = build_domestic_stock_cost_model_metadata()
        legacy = build_domestic_stock_cost_model_metadata(round_trip_cost_pct=0.108)

        self.assertEqual(current["version"], DOMESTIC_STOCK_COST_MODEL_VERSION)
        self.assertTrue(current["matches_current_model"])
        self.assertEqual(current["round_trip_cost_pct"], 0.29)
        self.assertEqual(current["commission_rate_status"], "research_assumption_not_broker_statement")
        self.assertEqual(current["slippage_status"], "research_assumption_not_observed_fill_calibration")
        self.assertEqual(legacy["version"], LEGACY_OR_CUSTOM_COST_MODEL_VERSION)
        self.assertFalse(legacy["matches_current_model"])

        custom_slippage = build_domestic_stock_cost_model_metadata(slippage_bps=5.0)
        self.assertEqual(
            custom_slippage["version"],
            LEGACY_OR_CUSTOM_COST_MODEL_VERSION,
        )
        self.assertFalse(custom_slippage["matches_current_assumptions"])
        self.assertEqual(custom_slippage["round_trip_cost_pct"], 0.33)

    def test_paper_engine_applies_current_tax_only_to_sell_fill(self) -> None:
        kst = get_timezone("Asia/Seoul")
        event_time = datetime(2026, 7, 13, 9, 0, tzinfo=kst)
        engine = PaperTradingEngine()

        def fill_tax(side: str) -> float:
            order = PaperOrder(
                order_id=f"order-{side}",
                symbol="005930",
                event_time=event_time,
                side=side,
                qty=10,
                limit_price=10_000.0,
                status="created",
            )
            _, fill = engine.fill(
                order,
                fill_price=10_000.0,
                order_event_id=f"event-{side}",
                fill_id=f"fill-{side}",
            )
            return fill.tax

        self.assertEqual(engine.tax_rate, DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE)
        self.assertEqual(fill_tax("buy"), 0.0)
        self.assertEqual(fill_tax("sell"), 200.0)


if __name__ == "__main__":
    unittest.main()
