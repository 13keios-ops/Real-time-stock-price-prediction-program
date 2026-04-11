from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.services.research import (
    build_feature_dataset_from_sqlite,
    build_minute_bars_from_sqlite,
    run_signal_backtest_from_sqlite,
    run_walk_forward_backtest_from_sqlite,
    train_centroid_baseline_from_sqlite,
)
from app.storage.contracts import MarketTickEvent, OrderbookSnapshot
from app.storage.runtime_writer import RuntimeWriter, get_sqlite_store
from app.utils.time import get_timezone


class ResearchPipelineTests(unittest.TestCase):
    def test_sqlite_pipeline_builds_and_trains(self) -> None:
        root = Path(__file__).resolve().parents[1]
        kst = get_timezone("Asia/Seoul")
        runtime_root = root / ".tmp-tests" / "research" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            writer = RuntimeWriter.from_settings(settings)

            base_time = datetime(2026, 4, 11, 9, 15, tzinfo=kst)
            for minute_index in range(0, 80):
                event_time = base_time + timedelta(minutes=minute_index)
                price = 70000 + (minute_index * 10)
                writer.write_market_tick(
                    MarketTickEvent(
                        symbol="005930",
                        event_time=event_time,
                        price=float(price),
                        volume=100 + minute_index,
                        source="test",
                    )
                )
                writer.write_orderbook_snapshot(
                    OrderbookSnapshot(
                        symbol="005930",
                        event_time=event_time,
                        bid_price=float(price - 5),
                        ask_price=float(price + 5),
                        bid_size=1000 + minute_index,
                        ask_size=900 + minute_index,
                        source="test",
                    )
                )

            bar_result = build_minute_bars_from_sqlite(project_root=root)
            feature_result = build_feature_dataset_from_sqlite(project_root=root)
            training_result = train_centroid_baseline_from_sqlite(project_root=root, horizon_min=15)
            backtest_result = run_signal_backtest_from_sqlite(project_root=root, horizon_min=15)
            walk_forward_result = run_walk_forward_backtest_from_sqlite(
                project_root=root,
                horizon_min=15,
                min_train_rows=30,
                test_window_rows=10,
                step_rows=10,
            )
            sqlite_store = get_sqlite_store(settings)

            self.assertIsNotNone(sqlite_store)
            self.assertEqual(bar_result.bars_written, 80)
            self.assertGreater(feature_result.features_written, 0)
            self.assertGreater(feature_result.labels_written, 0)
            self.assertTrue(training_result.artifact_path.exists())
            self.assertGreaterEqual(training_result.validation_accuracy, 0.0)
            self.assertTrue(backtest_result.report_markdown_path.exists())
            self.assertTrue(backtest_result.report_json_path.exists())
            self.assertGreaterEqual(backtest_result.rows_evaluated, 1)
            self.assertTrue(walk_forward_result.report_markdown_path.exists())
            self.assertTrue(walk_forward_result.report_json_path.exists())
            self.assertGreaterEqual(walk_forward_result.folds, 1)
            self.assertGreater(sqlite_store.count_rows("curated_minute_bars"), 0)
            self.assertGreater(sqlite_store.count_rows("feature_model_inputs"), 0)
            self.assertGreater(sqlite_store.count_rows("feature_labels"), 0)
            self.assertGreater(sqlite_store.count_rows("ml_training_runs"), 0)
            self.assertGreaterEqual(sqlite_store.count_rows("ml_model_evaluations"), 3)
            logging.shutdown()


if __name__ == "__main__":
    unittest.main()
