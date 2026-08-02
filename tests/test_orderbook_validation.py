import os
from datetime import datetime
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.features.minute_bars import build_feature_snapshot
from app.risk.gates import SpreadRiskGate
from app.services.streaming import OnlinePipelineProcessor
from app.storage.contracts import MinuteBar, OrderbookSnapshot
from app.storage.runtime_writer import get_sqlite_store


class OrderbookValidationTests(unittest.TestCase):
    def _orderbook(self, *, bid: float, ask: float) -> OrderbookSnapshot:
        return OrderbookSnapshot(
            symbol="000660",
            event_time=datetime.fromisoformat("2026-07-31T14:27:00+09:00"),
            bid_price=bid,
            ask_price=ask,
            bid_size=100,
            ask_size=50,
            source="kis-ws",
        )

    def test_zero_or_crossed_quote_fails_closed(self) -> None:
        zero_ask = self._orderbook(bid=1718000.0, ask=0.0)
        crossed = self._orderbook(bid=1719000.0, ask=1718000.0)
        non_finite_bid = self._orderbook(bid=float("nan"), ask=1718000.0)
        gate = SpreadRiskGate(max_spread_bps=50.0)

        self.assertFalse(zero_ask.is_valid_for_trading)
        self.assertEqual(zero_ask.trading_validity_reason, "invalid_orderbook_ask")
        self.assertEqual(gate.evaluate(zero_ask).reason, "invalid_orderbook_ask")
        self.assertFalse(gate.evaluate(crossed).allowed)
        self.assertEqual(gate.evaluate(crossed).reason, "invalid_orderbook_crossed")
        self.assertEqual(non_finite_bid.trading_validity_reason, "invalid_orderbook_bid")

    def test_invalid_quote_produces_neutral_orderbook_features(self) -> None:
        bar = MinuteBar(
            symbol="000660",
            bar_time=datetime.fromisoformat("2026-07-31T14:27:00+09:00"),
            open=1718000.0,
            high=1718000.0,
            low=1718000.0,
            close=1718000.0,
            volume=100,
            trade_count=1,
        )

        features = build_feature_snapshot(bar, self._orderbook(bid=1718000.0, ask=0.0), "feature-set-v1")

        self.assertEqual(features.values["mid_price"], 0.0)
        self.assertEqual(features.values["spread_bps"], 0.0)
        self.assertEqual(features.values["bid_ask_imbalance"], 0.0)

    def test_streaming_keeps_last_valid_quote_and_records_invalid_raw_event(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "orderbook-validation" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'test.db'}",
            "ENABLE_BROKER_PAPER_MIRRORING": "false",
        }
        valid_time = datetime.fromisoformat("2026-07-31T14:26:55+09:00")
        invalid_time = datetime.fromisoformat("2026-07-31T14:27:10+09:00")

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            processor = OnlinePipelineProcessor(settings)
            processor.process_orderbook_record(
                {
                    "MKSC_SHRN_ISCD": "000660",
                    "BIDP1": "1717000",
                    "ASKP1": "1718000",
                    "BIDP_RSQN1": "100",
                    "ASKP_RSQN1": "50",
                },
                event_time=valid_time,
            )
            processor.process_orderbook_record(
                {
                    "MKSC_SHRN_ISCD": "000660",
                    "BIDP1": "1718000",
                    "ASKP1": "",
                    "BIDP_RSQN1": "100",
                    "ASKP_RSQN1": "0",
                },
                event_time=invalid_time,
            )
            sqlite_store = get_sqlite_store(settings)

        self.assertIsNotNone(sqlite_store)
        self.assertEqual(processor.raw_orderbook_events, 2)
        self.assertEqual(processor.invalid_orderbook_events, 1)
        self.assertEqual(processor.states["000660"].latest_orderbook.ask_price, 1718000.0)
        self.assertEqual(sqlite_store.count_rows("raw_orderbook_ticks"), 2)


if __name__ == "__main__":
    unittest.main()
