import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_lightgbm_defensive_shadow import build_summary


class LightGbmDefensiveShadowTests(unittest.TestCase):
    def test_buy_avoid_and_early_exit_are_evaluated_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shadow.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.1}\n', encoding="utf-8")
            connection = sqlite3.connect(db_path)
            self.addCleanup(connection.close)
            connection.executescript(
                """
                CREATE TABLE serving_trade_signals (
                    signal_id TEXT,
                    symbol TEXT,
                    event_time TEXT,
                    side TEXT,
                    confidence REAL,
                    reason TEXT,
                    allowed INTEGER
                );
                CREATE TABLE serving_predictions (
                    prediction_id TEXT,
                    symbol TEXT,
                    event_time TEXT,
                    horizon_min INTEGER,
                    model_version TEXT,
                    probability_up REAL,
                    probability_flat REAL,
                    probability_down REAL
                );
                CREATE TABLE feature_labels (
                    symbol TEXT,
                    event_time TEXT,
                    horizon_min INTEGER,
                    label TEXT,
                    threshold_pct REAL,
                    future_return_pct REAL
                );
                CREATE TABLE paper_orders (
                    order_id TEXT,
                    symbol TEXT,
                    event_time TEXT,
                    side TEXT,
                    qty REAL,
                    limit_price REAL,
                    status TEXT,
                    prediction_id TEXT,
                    signal_id TEXT,
                    target_id TEXT
                );
                CREATE TABLE paper_fills (
                    fill_id TEXT,
                    order_id TEXT,
                    event_time TEXT,
                    fill_price REAL,
                    fill_qty REAL,
                    commission REAL,
                    tax REAL
                );
                CREATE TABLE curated_minute_bars (
                    symbol TEXT,
                    bar_time TEXT,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    trade_count INTEGER
                );
                """
            )
            connection.executemany(
                "INSERT INTO serving_trade_signals VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("sig-1", "005930", "2026-06-11T09:15:00+09:00", "buy", 0.6, "baseline", 1),
                    ("sig-2", "005930", "2026-06-11T09:16:00+09:00", "buy", 0.6, "baseline", 1),
                ],
            )
            connection.executemany(
                "INSERT INTO serving_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("p-1", "005930", "2026-06-11T09:15:00+09:00", 15, "lightgbm-h15-v1", 0.2, 0.2, 0.6),
                    ("p-2", "005930", "2026-06-11T09:16:00+09:00", 15, "lightgbm-h15-v1", 0.6, 0.2, 0.2),
                    ("p-exit", "005930", "2026-06-11T09:17:00+09:00", 15, "lightgbm-h15-v1", 0.2, 0.2, 0.6),
                ],
            )
            connection.executemany(
                "INSERT INTO feature_labels VALUES (?, ?, ?, ?, ?, ?)",
                [
                    ("005930", "2026-06-11T09:15:00+09:00", 15, "down", 0.35, -1.0),
                    ("005930", "2026-06-11T09:16:00+09:00", 15, "up", 0.35, 1.0),
                ],
            )
            connection.executemany(
                "INSERT INTO paper_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("buy-1", "005930", "2026-06-11T09:15:00+09:00", "buy", 1, 100.0, "filled", None, None, None),
                    ("sell-1", "005930", "2026-06-11T09:20:00+09:00", "sell", 1, 102.0, "filled", None, None, None),
                ],
            )
            connection.executemany(
                "INSERT INTO paper_fills VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("fill-buy", "buy-1", "2026-06-11T09:15:00+09:00", 100.0, 1, 0.0, 0.0),
                    ("fill-sell", "sell-1", "2026-06-11T09:20:00+09:00", 102.0, 1, 0.0, 0.0),
                ],
            )
            connection.execute(
                "INSERT INTO curated_minute_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("005930", "2026-06-11T09:17:00+09:00", 100.0, 100.0, 100.0, 100.0, 1, 1),
            )
            connection.commit()

            summary = build_summary(
                database_path=db_path,
                diagnostics_path=diagnostics_path,
                horizon_min=15,
                thresholds=[0.5],
                require_down_argmax=True,
            )

        self.assertEqual(summary["status"], "buy_avoid_candidate_found")
        buy_avoid = summary["buy_avoid_shadow"]["thresholds"][0]
        self.assertEqual(buy_avoid["skipped"]["signals"], 1)
        self.assertGreater(buy_avoid["delta"]["net_return_pct"], 0)
        early_exit = summary["early_exit_shadow"]["thresholds"][0]
        self.assertEqual(early_exit["early_exit_lots"], 1)
        self.assertLess(early_exit["delta"]["net_return_pct"], 0)



    def test_window_filter_and_e5_only_mode_exclude_outside_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shadow-window.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.1}\n', encoding="utf-8")
            connection = sqlite3.connect(db_path)
            self.addCleanup(connection.close)
            connection.executescript(
                """
                CREATE TABLE serving_trade_signals (
                    signal_id TEXT,
                    symbol TEXT,
                    event_time TEXT,
                    side TEXT,
                    confidence REAL,
                    reason TEXT,
                    allowed INTEGER
                );
                CREATE TABLE serving_predictions (
                    prediction_id TEXT,
                    symbol TEXT,
                    event_time TEXT,
                    horizon_min INTEGER,
                    model_version TEXT,
                    probability_up REAL,
                    probability_flat REAL,
                    probability_down REAL
                );
                CREATE TABLE feature_labels (
                    symbol TEXT,
                    event_time TEXT,
                    horizon_min INTEGER,
                    label TEXT,
                    threshold_pct REAL,
                    future_return_pct REAL
                );
                """
            )
            rows = [
                ("outside", "2026-07-03T09:15:00+09:00", -1.0),
                ("inside", "2026-07-10T09:15:00+09:00", -1.0),
            ]
            for prefix, event_time, future_return in rows:
                connection.execute(
                    "INSERT INTO serving_trade_signals VALUES (?, '005930', ?, 'buy', 0.6, 'baseline', 1)",
                    (f"sig-{prefix}", event_time),
                )
                connection.execute(
                    "INSERT INTO serving_predictions VALUES (?, '005930', ?, 15, 'lightgbm-h15-v1', 0.2, 0.2, 0.6)",
                    (f"pred-{prefix}", event_time),
                )
                connection.execute(
                    "INSERT INTO feature_labels VALUES ('005930', ?, 15, 'down', 0.35, ?)",
                    (event_time, future_return),
                )
            connection.commit()

            summary = build_summary(
                database_path=db_path,
                diagnostics_path=diagnostics_path,
                horizon_min=15,
                thresholds=[0.4],
                require_down_argmax=True,
                start_date="2026-07-04",
                end_date="2026-07-18",
                evaluate_early_exit=False,
            )

        self.assertEqual(summary["joined_rows"], 1)
        self.assertEqual(
            summary["requested_date_range"],
            {"start_date": "2026-07-04", "end_date": "2026-07-18"},
        )
        self.assertTrue(summary["date_range"]["start"].startswith("2026-07-10"))
        self.assertEqual(
            summary["early_exit_shadow"]["status"],
            "not_evaluated_for_windowed_e5",
        )

if __name__ == "__main__":
    unittest.main()
