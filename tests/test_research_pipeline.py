from datetime import datetime, timedelta
import json
import logging
import math
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.models.lightgbm_model import LightGbmArtifact, LightGbmDirectionModel
from app.config.settings import load_settings
from app.services.research import (
    _load_labeled_feature_dataset,
    _lightgbm_artifact_training_status,
    _resolve_feature_row_source,
    _split_dataset_with_challenger_holdout,
    _training_run_holdout_status,
    build_feature_dataset_from_sqlite,
    build_minute_bars_from_sqlite,
    run_cybos_expected_value_review_from_sqlite,
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
    def test_challenger_holdout_split_keeps_validation_before_holdout(self) -> None:
        kst = get_timezone("Asia/Seoul")
        base_time = datetime(2025, 1, 2, 9, 0, tzinfo=kst)
        labels = ("down", "flat", "up")
        dataset = []
        for day_index in range(60):
            event_time = base_time + timedelta(days=day_index)
            dataset.append(
                {
                    "symbol": "005930",
                    "event_time": event_time,
                    "label": labels[day_index % len(labels)],
                }
            )

        split_payload = _split_dataset_with_challenger_holdout(dataset, horizon_min=15)
        train_rows = split_payload["train_rows"]
        validation_rows = split_payload["validation_rows"]
        challenger_rows = split_payload["challenger_rows"]
        metadata = split_payload["metadata"]

        self.assertEqual(metadata["dataset_scope"], "challenger_holdout_tail_10pct")
        self.assertGreater(len(train_rows), 0)
        self.assertGreater(len(validation_rows), 0)
        self.assertGreater(len(challenger_rows), 0)
        self.assertLess(
            max(row["event_time"] for row in validation_rows),
            min(row["event_time"] for row in challenger_rows),
        )
        training_keys = {(row["symbol"], row["event_time"]) for row in train_rows + validation_rows}
        challenger_keys = {(row["symbol"], row["event_time"]) for row in challenger_rows}
        self.assertFalse(training_keys.intersection(challenger_keys))

    def test_training_run_holdout_status_guards_independence(self) -> None:
        split_metadata = {
            "dataset_scope": "challenger_holdout_tail_10pct",
            "challenger_holdout": {
                "first_event_time": "2025-10-24T09:00:00+09:00",
            },
        }
        valid_summary = {
            "challenger_holdout_split": {
                "dataset_scope": "challenger_holdout_tail_10pct",
                "challenger_holdout": {
                    "first_event_time": "2025-10-24T00:00:00+00:00",
                },
                "validation": {
                    "last_event_time": "2025-10-23T15:15:00+09:00",
                },
            },
        }

        self.assertEqual(
            _training_run_holdout_status(valid_summary, split_metadata),
            "independent_challenger_holdout",
        )
        self.assertEqual(
            _training_run_holdout_status(valid_summary, {"dataset_scope": "validation_tail_20pct_fallback"}),
            "not_independent_validation_fallback",
        )
        self.assertEqual(
            _training_run_holdout_status(None, split_metadata),
            "unknown_training_summary",
        )
        self.assertEqual(
            _training_run_holdout_status({}, split_metadata),
            "legacy_training_without_reserved_holdout",
        )
        self.assertEqual(
            _training_run_holdout_status(
                {"challenger_holdout_split": {"dataset_scope": "validation_tail_20pct"}},
                split_metadata,
            ),
            "training_reserved_holdout_missing",
        )
        self.assertEqual(
            _training_run_holdout_status(
                {"challenger_holdout_split": {"dataset_scope": "challenger_holdout_tail_10pct"}},
                split_metadata,
            ),
            "holdout_metadata_missing",
        )
        self.assertEqual(
            _training_run_holdout_status(
                {
                    "challenger_holdout_split": {
                        "dataset_scope": "challenger_holdout_tail_10pct",
                        "challenger_holdout": {"first_event_time": "2025-10-25T09:00:00+09:00"},
                    }
                },
                split_metadata,
            ),
            "holdout_window_mismatch",
        )
        self.assertEqual(
            _training_run_holdout_status(
                {
                    "challenger_holdout_split": {
                        "dataset_scope": "challenger_holdout_tail_10pct",
                        "challenger_holdout": {"first_event_time": "2025-10-24T09:00:00+09:00"},
                        "validation": {"last_event_time": "2025-10-24T09:00:00+09:00"},
                    }
                },
                split_metadata,
            ),
            "validation_overlaps_challenger_holdout",
        )

    def test_lightgbm_artifact_training_status_requires_matching_run_id(self) -> None:
        artifact = LightGbmArtifact(
            model_version="lightgbm-h15-v1",
            feature_set_version="feature-set-v1",
            horizon_min=15,
            feature_names=["return_1m_pct"],
            class_labels=["down", "flat", "up"],
            training_run_id="train-lightgbm-h15-current",
        )

        self.assertEqual(
            _lightgbm_artifact_training_status(artifact, {"training_run_id": "train-lightgbm-h15-current"}),
            "artifact_training_run_match",
        )
        self.assertEqual(
            _lightgbm_artifact_training_status(artifact, {"training_run_id": "train-lightgbm-h15-previous"}),
            "artifact_training_run_mismatch",
        )
        self.assertEqual(
            _lightgbm_artifact_training_status(artifact, None),
            "unknown_training_summary",
        )
        artifact.training_run_id = None
        self.assertEqual(
            _lightgbm_artifact_training_status(artifact, {"training_run_id": "train-lightgbm-h15-current"}),
            "artifact_missing_training_run_id",
        )

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
            lightgbm_artifact = LightGbmDirectionModel.from_path(training_result.artifact_path).artifact
            self.assertEqual(lightgbm_artifact.training_run_id, training_result.training_run_id)
            self.assertEqual(lightgbm_artifact.dataset_scope, "challenger_holdout_tail_10pct")
            self.assertIsNotNone(lightgbm_artifact.challenger_holdout_first_event_time)
            lightgbm_training_rows = [
                row
                for row in sqlite_store.fetch_all_rows("ml_training_runs", "completed_at")
                if row["model_version"] == training_result.model_version
            ]
            self.assertTrue(lightgbm_training_rows)
            lightgbm_training_summary = json.loads(lightgbm_training_rows[-1]["training_summary_json"])
            self.assertIn("challenger_holdout_split", lightgbm_training_summary)
            self.assertTrue(backtest_result.report_markdown_path.exists())
            self.assertTrue(backtest_result.report_json_path.exists())
            self.assertGreaterEqual(backtest_result.rows_evaluated, 1)
            self.assertTrue(walk_forward_result.report_markdown_path.exists())
            self.assertTrue(walk_forward_result.report_json_path.exists())
            self.assertGreaterEqual(walk_forward_result.folds, 1)
            self.assertEqual(walk_forward_result.gap_rows, 15)
            self.assertIsNone(walk_forward_result.max_train_rows)
            self.assertEqual(walk_forward_result.parameter_profile, "ad_hoc")
            self.assertEqual(walk_forward_result.command_source, "run_walk_forward_backtest_from_sqlite")
            self.assertIsNone(walk_forward_result.feature_market_source)
            walk_forward_payload = json.loads(walk_forward_result.report_json_path.read_text(encoding="utf-8"))
            self.assertEqual(walk_forward_payload["return_aggregation"], "sum_of_trade_pct_not_portfolio")
            self.assertEqual(
                walk_forward_payload["trade_sum_net_return_pct"],
                walk_forward_payload["cumulative_net_return_pct"],
            )
            self.assertIn("estimated_cost_drag_pct", walk_forward_payload)
            self.assertIsNone(walk_forward_payload["portfolio_return_pct"])
            self.assertTrue(challenger_result.report_markdown_path.exists())
            self.assertTrue(challenger_result.report_json_path.exists())
            self.assertTrue(challenger_result.leaderboard_json_path.exists())
            challenger_payload = json.loads(challenger_result.report_json_path.read_text(encoding="utf-8"))
            self.assertIn(
                challenger_payload["dataset_scope"],
                {"challenger_holdout_tail_10pct", "validation_tail_20pct_fallback"},
            )
            self.assertIn("evaluation_split", challenger_payload)
            self.assertTrue(
                all("evaluation_independence_status" in candidate for candidate in challenger_payload["candidates"])
            )
            if challenger_payload["dataset_scope"] == "challenger_holdout_tail_10pct":
                holdout_first = datetime.fromisoformat(
                    challenger_payload["evaluation_split"]["challenger_holdout"]["first_event_time"]
                )
                validation_last = datetime.fromisoformat(
                    challenger_payload["evaluation_split"]["validation"]["last_event_time"]
                )
                self.assertLess(validation_last, holdout_first)
            self.assertGreaterEqual(len(challenger_result.candidates), 3)
            self.assertTrue(any(candidate.candidate_name == "latest_lightgbm" for candidate in challenger_result.candidates))
            latest_lightgbm_candidates = [
                candidate for candidate in challenger_result.candidates if candidate.candidate_name == "latest_lightgbm"
            ]
            self.assertTrue(latest_lightgbm_candidates)
            self.assertEqual(latest_lightgbm_candidates[0].artifact_training_status, "artifact_training_run_match")
            self.assertEqual(latest_lightgbm_candidates[0].artifact_training_run_id, training_result.training_run_id)
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

    def test_cybos_bars_build_bar_only_features_without_orderbook(self) -> None:
        root = Path(__file__).resolve().parents[1]
        kst = get_timezone("Asia/Seoul")
        runtime_root = root / ".tmp-tests" / "research-cybos-features" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            writer = RuntimeWriter.from_settings(settings)

            base_time = datetime(2026, 4, 13, 9, 15, tzinfo=kst)
            for index in range(24):
                bar_time = base_time + timedelta(minutes=15 * index)
                close = 70000 + (index * 10)
                writer.write_market_tick(
                    MarketTickEvent(
                        symbol="005930",
                        event_time=bar_time,
                        price=float(close),
                        volume=1000 + index,
                        source="cybos-historical",
                    )
                )
                writer.write_minute_bar(
                    MinuteBar(
                        symbol="005930",
                        bar_time=bar_time,
                        open=float(close - 5),
                        high=float(close + 20),
                        low=float(close - 20),
                        close=float(close),
                        volume=1000 + index,
                        trade_count=10,
                    )
                )

            feature_result = build_feature_dataset_from_sqlite(project_root=root, horizons=(15,))
            sqlite_store = get_sqlite_store(settings)

            self.assertIsNotNone(sqlite_store)
            self.assertEqual(feature_result.features_written, 24)
            self.assertGreater(feature_result.labels_written, 0)

            feature_rows = sqlite_store.fetch_feature_rows(horizon_min=15)
            self.assertGreater(len(feature_rows), 0)
            self.assertEqual(_resolve_feature_row_source(feature_rows[0]), "cybos-historical")

            feature_names, dataset = _load_labeled_feature_dataset(sqlite_store, horizon_min=15)
            self.assertEqual(feature_names, ["avg_trade_size", "hl_range_pct", "return_1m_pct"])
            self.assertGreater(len(dataset), 0)
            self.assertEqual(dataset[0]["feature_source"], "cybos-historical")
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

    def test_cybos_expected_value_review_writes_reports(self) -> None:
        root = Path(__file__).resolve().parents[1]
        kst = get_timezone("Asia/Seoul")
        runtime_root = root / ".tmp-tests" / "cybos-expected-value" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            writer = RuntimeWriter.from_settings(settings)

            for day_index in range(14):
                base_time = datetime(2026, 4, 1 + day_index, 9, 15, tzinfo=kst)
                previous_close = 10000.0 + (day_index * 10)
                for bar_index in range(26):
                    bar_time = base_time + timedelta(minutes=15 * bar_index)
                    close = previous_close + (90 if bar_index % 3 == 0 else (-70 if bar_index % 3 == 1 else 5))
                    high = max(previous_close, close) + 8
                    low = min(previous_close, close) - 8
                    volume = 1000 + (day_index * 10) + (bar_index * 25)
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

            result = run_cybos_expected_value_review_from_sqlite(
                project_root=root,
                train_max_rows=120,
                walk_forward_test_rows=30,
                walk_forward_step_rows=30,
                walk_forward_gap_rows=1,
                walk_forward_max_folds=4,
                feature_set_name="bar_context_momentum",
                trade_cost_pct=0.13,
                threshold_grid=(0.0, 0.3, 0.5),
                calibration_rows=20,
                min_calibration_trades=1,
            )

            self.assertEqual(result["review"], "cybos_expected_value_review")
            self.assertTrue(Path(str(result["report_json_path"])).exists())
            self.assertTrue(Path(str(result["report_markdown_path"])).exists())
            self.assertGreaterEqual(int(result["walk_forward"]["folds"]), 1)
            self.assertEqual(
                result["walk_forward"]["return_aggregation"],
                "sum_of_trade_pct_not_portfolio",
            )
            self.assertIsNotNone(result["walk_forward"]["portfolio_return_pct"])
            self.assertEqual(
                result["walk_forward"]["portfolio_return_model"],
                "fixed_fraction_per_signal_horizon_proxy",
            )
            logging.shutdown()


if __name__ == "__main__":
    unittest.main()
