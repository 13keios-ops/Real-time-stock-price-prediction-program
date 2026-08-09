from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_kis_live_data_quality import (
    _decision_lineage_summary,
    _websocket_reconnect_summary,
    summarize,
)


class KisLiveDataQualitySummaryTests(unittest.TestCase):
    def test_summary_counts_actual_kis_minutes_and_filters_other_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "test.db"
            connection = sqlite3.connect(database_path)
            connection.executescript(
                """
                CREATE TABLE raw_market_ticks (
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE TABLE raw_orderbook_ticks (
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    bid_price REAL NOT NULL,
                    ask_price REAL NOT NULL,
                    bid_size INTEGER NOT NULL,
                    ask_size INTEGER NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE TABLE curated_minute_bars (
                    symbol TEXT NOT NULL,
                    bar_time TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    trade_count INTEGER NOT NULL
                );
                CREATE TABLE feature_model_inputs (
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    feature_set_version TEXT NOT NULL,
                    values_json TEXT NOT NULL
                );
                CREATE TABLE feature_labels (
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    horizon_min INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    threshold_pct REAL NOT NULL,
                    future_return_pct REAL NOT NULL
                );
                CREATE TABLE serving_predictions (
                    prediction_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    horizon_min INTEGER NOT NULL,
                    model_version TEXT NOT NULL,
                    probability_up REAL NOT NULL,
                    probability_flat REAL NOT NULL,
                    probability_down REAL NOT NULL
                );
                CREATE TABLE serving_trade_signals (
                    signal_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    side TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reason TEXT NOT NULL,
                    allowed INTEGER NOT NULL
                );
                """
            )
            connection.executemany(
                "INSERT INTO raw_market_ticks VALUES (?, ?, ?, ?, ?)",
                [
                    ("005930", "2026-05-08T09:00:01+09:00", 70000, 10, "kis-ws"),
                    ("005930", "2026-05-08T09:01:01+09:00", 70010, 12, "kis-ws"),
                    ("000660", "2026-05-08T09:00:02+09:00", 120000, 5, "kis-rest"),
                    ("005930", "2026-05-08T09:00:03+09:00", 69900, 1, "cybos-historical"),
                ],
            )
            connection.executemany(
                "INSERT INTO raw_orderbook_ticks VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("005930", "2026-05-08T09:00:05+09:00", 69990, 70010, 100, 90, "kis-ws"),
                    ("005930", "2026-05-08T09:01:05+09:00", 70000, 70020, 100, 90, "kis-ws"),
                    ("000660", "2026-05-08T09:00:07+09:00", 119900, 120100, 80, 70, "kis-ws"),
                ],
            )
            connection.executemany(
                "INSERT INTO curated_minute_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("005930", "2026-05-08T09:00:00+09:00", 70000, 70000, 70000, 70000, 10, 1),
                    ("005930", "2026-05-08T09:01:00+09:00", 70010, 70010, 70010, 70010, 12, 1),
                    ("000660", "2026-05-08T09:00:00+09:00", 120000, 120000, 120000, 120000, 5, 1),
                    ("035420", "2026-05-08T09:00:00+09:00", 200000, 200000, 200000, 200000, 5, 1),
                ],
            )
            connection.executemany(
                "INSERT INTO feature_model_inputs VALUES (?, ?, ?, ?)",
                [
                    ("005930", "2026-05-08T09:00:00+09:00", "feature-set-v1", "{}"),
                    ("005930", "2026-05-08T09:01:00+09:00", "feature-set-v1", "{}"),
                    ("000660", "2026-05-08T09:00:00+09:00", "feature-set-v1", "{}"),
                ],
            )
            connection.executemany(
                "INSERT INTO feature_labels VALUES (?, ?, ?, ?, ?, ?)",
                [
                    ("005930", "2026-05-08T09:00:00+09:00", 15, "up", 0.13, 0.2),
                    ("005930", "2026-05-08T09:01:00+09:00", 15, "flat", 0.13, 0.0),
                    ("000660", "2026-05-08T09:00:00+09:00", 60, "down", 0.13, -0.2),
                ],
            )
            connection.commit()
            connection.close()

            result = summarize(database_path, recent_days=5)

        self.assertEqual(result["latest_trade_date"], "2026-05-08")
        self.assertEqual(result["trade_dates_observed"], 1)
        latest = result["recent_days"][0]
        self.assertEqual(latest["raw_market"]["symbol_minutes"], 3)
        self.assertEqual(latest["raw_orderbook"]["symbol_minutes"], 3)
        self.assertEqual(latest["minute_bars"]["symbol_minutes"], 3)
        self.assertEqual(latest["features"]["symbol_minutes"], 3)
        self.assertEqual(latest["labels_h15"]["symbol_minutes"], 2)
        self.assertEqual(latest["label_distribution_h15"], {"flat": 1, "up": 1})
        self.assertEqual(latest["feature_to_bar_symbol_minute_ratio"], 1.0)
        self.assertEqual(len(result["latest_symbol_summary"]), 2)
        coverage = result["latest_intraday_coverage"]
        self.assertEqual(coverage["status"], "ok")
        self.assertEqual(coverage["trade_date"], "2026-05-08")
        self.assertEqual(coverage["watchlist_symbols"], 10)
        self.assertEqual(coverage["expected_minute_slots_per_symbol"], 2)
        self.assertEqual(coverage["expected_symbol_minutes"], 20)
        self.assertEqual(coverage["closed_expected_minute_slots_per_symbol"], 1)
        self.assertEqual(coverage["closed_expected_symbol_minutes"], 10)
        self.assertIn("latest_raw_minute_lag_seconds", coverage)
        self.assertEqual(coverage["raw_market_coverage_ratio"], 0.15)
        self.assertEqual(coverage["feature_coverage_ratio"], 0.15)
        self.assertEqual(coverage["feature_closed_coverage_ratio"], 0.3)
        self.assertEqual(result["assessment"]["status"], "needs_attention")
        self.assertTrue(
            any("coverage is below 80%" in note for note in result["assessment"]["notes"])
        )


class KisLiveSessionObservabilityTests(unittest.TestCase):
    def test_decision_lineage_and_reconnect_summary_are_date_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_path = root / "test.db"
            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row
            connection.execute(
                """
                CREATE TABLE serving_decision_ledger (
                    decision_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    decision_stage TEXT NOT NULL,
                    active_prediction_id TEXT NOT NULL,
                    active_model_version TEXT NOT NULL,
                    active_training_run_id TEXT,
                    active_artifact_id TEXT,
                    active_artifact_sha256 TEXT,
                    shadow_predictions_json TEXT NOT NULL
                )
                """
            )
            complete_shadow = (
                '[{"prediction_id":"shadow-1","model_version":"challenger-v1",'
                '"training_run_id":"run-1","artifact_id":"artifact-1",'
                '"artifact_sha256":"abc"}]'
            )
            connection.executemany(
                "INSERT INTO serving_decision_ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "decision-1",
                        "005930",
                        "2026-08-07T09:00:00+09:00",
                        "signal_blocked",
                        "prediction-1",
                        "baseline-v1",
                        "run-active",
                        "artifact-active",
                        "hash-active",
                        complete_shadow,
                    ),
                    (
                        "decision-2",
                        "000660",
                        "2026-08-07T09:01:00+09:00",
                        "target_blocked",
                        "prediction-2",
                        "baseline-v1",
                        None,
                        "artifact-active",
                        "hash-active",
                        "not-json",
                    ),
                ],
            )
            connection.commit()
            lineage = _decision_lineage_summary(connection, "2026-08-07")
            connection.close()

            log_path = root / "live-runtime.stderr.log"
            log_path.write_text(
                "2026-08-07 09:00:01,000 WARNING KIS WebSocket disconnected; reconnecting "
                "in 5s (attempt 1/10, consecutive=1, storm=False): no close frame received or sent\n"
                "2026-08-08 09:00:01,000 WARNING KIS WebSocket disconnected; reconnecting "
                "in 5s (attempt 2/10, consecutive=1, storm=True): timeout\n",
                encoding="utf-8",
            )
            reconnects = _websocket_reconnect_summary(log_path, "2026-08-07")

        self.assertEqual(lineage["status"], "lineage_incomplete")
        self.assertEqual(lineage["rows"], 2)
        self.assertEqual(lineage["complete_lineage_rows"], 1)
        self.assertEqual(lineage["lineage_completion_ratio"], 0.5)
        self.assertEqual(lineage["malformed_shadow_rows"], 1)
        self.assertEqual(reconnects["status"], "observed_no_storm")
        self.assertEqual(reconnects["count"], 1)
        self.assertEqual(reconnects["max_attempt"], 1)


if __name__ == "__main__":
    unittest.main()
