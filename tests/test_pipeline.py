from pathlib import Path
import unittest

from app.collectors.market_data import build_sample_orderbook, build_sample_ticks
from app.features.minute_bars import aggregate_ticks_to_minute_bar, build_feature_snapshot
from app.labels.thresholds import classify_return
from app.services.runtime import run_demo_pipeline


class PipelineTests(unittest.TestCase):
    def test_bar_and_feature_generation(self) -> None:
        ticks = build_sample_ticks("005930")
        orderbook = build_sample_orderbook("005930")
        bar = aggregate_ticks_to_minute_bar("005930", ticks)
        features = build_feature_snapshot(bar, orderbook, "feature-set-v1")

        self.assertEqual(bar.trade_count, 3)
        self.assertIn("spread_bps", features.values)
        self.assertGreater(features.values["mid_price"], 0)

    def test_label_thresholds(self) -> None:
        self.assertEqual(classify_return(0.4, 0.35), "up")
        self.assertEqual(classify_return(-0.4, 0.35), "down")
        self.assertEqual(classify_return(0.1, 0.35), "flat")

    def test_demo_pipeline_runs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = run_demo_pipeline(project_root=root, symbol="005930")

        self.assertEqual(result.symbol, "005930")
        self.assertTrue(result.runtime_root.exists())
        self.assertTrue(isinstance(result.signal_allowed, bool))


if __name__ == "__main__":
    unittest.main()
