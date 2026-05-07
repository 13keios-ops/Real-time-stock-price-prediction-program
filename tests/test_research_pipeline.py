from datetime import datetime, timedelta
import logging
import math
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.services.research import (
    build_feature_dataset_from_sqlite,
    build_minute_bars_from_sqlite,
    run_cybos_rule_challenger_review_from_sqlite,
    run_model_challenger_review_from_sqlite,
    run_signal_backtest_from_sqlite,
    run_walk_forward_backtest_from_sqlite,
    set_builtin_model_active,
    train_centroid_baseline_from_sqlite,
    train_lightgbm_from_sqlite,
)
from app.storage.contracts import MarketTickEvent, MinuteBar, OrderbookSnapshot
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
                price = 70000 + int(math.sin(minute_index / 5) * 140) + (minute_index * 2)
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
            baseline_training_result = train_centroid_baseline_from_sqlite(project_root=root, horizon_min=15)
            active_result = set_builtin_model_active(project_root=root, horizon_min=15, builtin_name="baseline")
            training_result = train_lightgbm_from_sqlite(project_root=root, horizon_min=15)
            backtest_result = run_signal_backtest_from_sqlite(project_root=root, horizon_min=15)
            walk_forward_result = run_walk_forward_backtest_from_sqlite(
                project_root=root,
                horizon_min=15,
                min_train_rows=30,
                test_window_rows=10,
                step_rows=10,
            )
            challenger_result = run_model_challenger_review_from_sqlite(
                project_root=root,
                horizon_min=15,
                promote_best=False,
            )
            promoted_challenger_result = run_model_challenger_review_from_sqlite(
                project_root=root,
                horizon_min=15,
                promote_best=True,
            )
            sqlite_store = get_sqlite_store(settings)

            self.assertIsNotNone(sqlite_store)
            self.assertEqual(bar_result.bars_written, 80)
            self.assertGreater(feature_result.features_written, 0)
            self.assertGreater(feature_result.labels_written, 0)
            self.assertTrue(baseline_training_result.artifact_path.exists())
            self.assertTrue(baseline_training_result.activation_applied)
            self.assertEqual(active_result.model_version, "baseline-h15-v1")
            self.assertTrue(training_result.artifact_path.exists())
            self.assertGreaterEqual(training_result.validation_accuracy, 0.0)
            self.assertTrue(training_result.model_version.startswith("lightgbm-h15-"))
            self.assertFalse(training_result.activation_applied)
            self.assertTrue(backtest_result.report_markdown_path.exists())
            self.assertTrue(backtest_result.report_json_path.exists())
            self.assertGreaterEqual(backtest_result.rows_evaluated, 1)
            self.assertTrue(walk_forward_result.report_markdown_path.exists())
            self.assertTrue(walk_forward_result.report_json_path.exists())
            self.assertGreaterEqual(walk_forward_result.folds, 1)
            self.assertEqual(walk_forward_result.gap_rows, 15)
            self.assertIsNone(walk_forward_result.max_train_rows)
            self.assertTrue(challenger_result.report_markdown_path.exists())
            self.assertTrue(challenger_result.report_json_path.exists())
            self.assertTrue(challenger_result.leaderboard_json_path.exists())
            self.assertGreaterEqual(len(challenger_result.candidates), 3)
            self.assertTrue(any(candidate.candidate_name == "latest_lightgbm" for candidate in challenger_result.candidates))
            self.assertIn(challenger_result.recommended_action, {"promote", "keep_active", "review_required"})
            self.assertIsNotNone(challenger_result.recommended_model_version)
            self.assertIn(challenger_result.walk_forward_gate_status, {"pass", "needs_review", "missing"})
            self.assertTrue(challenger_result.walk_forward_gate_reason)
            self.assertFalse(challenger_result.promotion_requested)
            self.assertFalse(challenger_result.promotion_applied)
            self.assertIsNone(challenger_result.promoted_model_version)
            self.assertEqual(challenger_result.active_model_version_after_run, challenger_result.active_model_version)
            self.assertTrue(promoted_challenger_result.report_markdown_path.exists())
            self.assertIn(promoted_challenger_result.recommended_action, {"promote", "keep_active", "review_required"})
            self.assertIn(promoted_challenger_result.walk_forward_gate_status, {"pass", "needs_review", "missing"})
            self.assertTrue(promoted_challenger_result.promotion_requested)
            if promoted_challenger_result.promotion_applied:
                self.assertEqual(
                    promoted_challenger_result.promoted_model_version,
                    promoted_challenger_result.recommended_model_version,
                )
                self.assertEqual(
                    promoted_challenger_result.active_model_version_after_run,
                    promoted_challenger_result.promoted_model_version,
                )
            else:
                self.assertIsNone(promoted_challenger_result.promoted_model_version)
                self.assertEqual(
                    promoted_challenger_result.active_model_version_after_run,
                    promoted_challenger_result.active_model_version,
                )
            self.assertGreater(sqlite_store.count_rows("curated_minute_bars"), 0)
            self.assertGreater(sqlite_store.count_rows("feature_model_inputs"), 0)
            self.assertGreater(sqlite_store.count_rows("feature_labels"), 0)
            self.assertGreater(sqlite_store.count_rows("ml_training_runs"), 0)
            self.assertGreaterEqual(sqlite_store.count_rows("ml_model_evaluations"), 11)
            logging.shutdown()

    def test_feature_labels_use_nearest_same_day_future_bar_when_exact_minute_missing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        kst = get_timezone("Asia/Seoul")
        runtime_root = root / ".tmp-tests" / "research-sparse" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            writer = RuntimeWriter.from_settings(settings)

            timestamps = [
                datetime(2026, 4, 11, 9, 15, tzinfo=kst),
                datetime(2026, 4, 11, 9, 40, tzinfo=kst),
            ]
            prices = [70000, 70800]
            for event_time, price in zip(timestamps, prices, strict=True):
                writer.write_market_tick(
                    MarketTickEvent(
                        symbol="005930",
                        event_time=event_time,
                        price=float(price),
                        volume=100,
                        source="kis-ws",
                    )
                )
                writer.write_orderbook_snapshot(
                    OrderbookSnapshot(
                        symbol="005930",
                        event_time=event_time,
                        bid_price=float(price - 5),
                        ask_price=float(price + 5),
                        bid_size=1000,
                        ask_size=900,
                        source="kis-ws",
                    )
                )

            build_minute_bars_from_sqlite(project_root=root)
            feature_result = build_feature_dataset_from_sqlite(project_root=root, horizons=(15,))
            sqlite_store = get_sqlite_store(settings)

            self.assertIsNotNone(sqlite_store)
            self.assertEqual(feature_result.features_written, 2)
            self.assertEqual(feature_result.labels_written, 1)
            label_rows = sqlite_store.fetch_all_rows("feature_labels", "event_time")
            self.assertEqual(len(label_rows), 1)
            self.assertEqual(label_rows[0]["event_time"], "2026-04-11T09:15:00+09:00")
            self.assertGreater(float(label_rows[0]["future_return_pct"]), 0.0)
            logging.shutdown()

    def test_cybos_rule_challenger_review_writes_reports(self) -> None:
        root = Path(__file__).resolve().parents[1]
        kst = get_timezone("Asia/Seoul")
        runtime_root = root / ".tmp-tests" / "cybos-rule-review" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            writer = RuntimeWriter.from_settings(settings)

            for day_index in range(10):
                base_time = datetime(2026, 4, 1 + day_index, 9, 15, tzinfo=kst)
                previous_close = 10000.0 + (day_index * 20)
                for bar_index in range(26):
                    bar_time = base_time + timedelta(minutes=15 * bar_index)
                    if bar_index < 8:
                        close = previous_close + 80
                    elif bar_index < 16:
                        close = previous_close - 80
                    else:
                        close = previous_close + (4 if bar_index % 2 == 0 else -4)
                    high = max(previous_close, close) + 10
                    low = min(previous_close, close) - 10
                    volume = 1000 + (day_index * 10) + (bar_index * 20)
                    writer.write_market_tick(
                        MarketTickEvent(
                            symbol="005930",
                            event_time=bar_time,
                            price=close,
                            volume=volume,
                            source="cybos-historical",
                        )
                    )
                    writer.write_minute_bar(
                        MinuteBar(
                            symbol="005930",
                            bar_time=bar_time,
                            open=previous_close,
                            high=high,
                            low=low,
                            close=close,
                            volume=volume,
                            trade_count=10,
                        )
                    )
                    previous_close = close

            result = run_cybos_rule_challenger_review_from_sqlite(
                project_root=root,
                train_max_rows=80,
                walk_forward_test_rows=20,
                walk_forward_step_rows=20,
                walk_forward_gap_rows=1,
                walk_forward_max_folds=5,
                trade_cost_pct=0.13,
            )

            self.assertEqual(result["review"], "cybos_rule_challenger_review")
            self.assertTrue(Path(str(result["report_json_path"])).exists())
            self.assertTrue(Path(str(result["report_markdown_path"])).exists())
            self.assertEqual(len(result["leaderboard"]), 5)
            self.assertGreaterEqual(int(result["walk_forward"]["folds"]), 1)
            logging.shutdown()


if __name__ == "__main__":
    unittest.main()
