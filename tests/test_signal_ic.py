import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_signal_ic import build_summary, spearman


class SignalIcTests(unittest.TestCase):
    def test_spearman_handles_ties_with_average_ranks(self) -> None:
        self.assertAlmostEqual(spearman([1, 2, 2, 4], [4, 3, 3, 1]), -1.0)

    def test_down_probability_ic_uses_daily_rank_correlation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ic.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.108}\n', encoding="utf-8")
            conn = sqlite3.connect(db_path)
            self.addCleanup(conn.close)
            conn.executescript(
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
                ("2026-06-11", "A", 0.9, -3.0),
                ("2026-06-11", "B", 0.6, -1.0),
                ("2026-06-11", "C", 0.2, 2.0),
                ("2026-06-12", "A", 0.8, -2.0),
                ("2026-06-12", "B", 0.5, 0.0),
                ("2026-06-12", "C", 0.1, 3.0),
            ]
            for idx, (day, symbol, prob_down, future_return) in enumerate(rows):
                event_time = f"{day}T09:{15 + idx:02d}:00+09:00"
                conn.execute(
                    "INSERT INTO serving_trade_signals VALUES (?, ?, ?, 'buy', 0.5, 'baseline', 1)",
                    (f"sig-{idx}", symbol, event_time),
                )
                conn.execute(
                    "INSERT INTO serving_predictions VALUES (?, ?, ?, 15, 'lightgbm-h15-v1', ?, 0.1, ?)",
                    (f"pred-{idx}", symbol, event_time, 1.0 - prob_down, prob_down),
                )
                conn.execute(
                    "INSERT INTO feature_labels VALUES (?, ?, 15, ?, 0.35, ?)",
                    (symbol, event_time, "down" if future_return < 0 else "up", future_return),
                )
            conn.commit()

            summary = build_summary(
                database_path=db_path,
                diagnostics_path=diagnostics_path,
                horizon_min=15,
                min_daily_rows=2,
            )

        self.assertEqual(summary["status"], "ok")
        down = summary["probability_down"]
        self.assertEqual(down["summary"]["days_usable"], 2)
        self.assertLessEqual(down["summary"]["mean_daily_ic"], -0.99)
        self.assertEqual(down["decision"]["decision"], "down_signal_has_correct_direction_information")

    def test_decomposition_reports_time_symbol_and_volatility_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ic.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.108}\n', encoding="utf-8")
            conn = sqlite3.connect(db_path)
            self.addCleanup(conn.close)
            conn.executescript(
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
                CREATE TABLE curated_minute_bars (
                    symbol TEXT,
                    bar_time TEXT,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume INTEGER,
                    trade_count INTEGER
                );
                """
            )
            symbols = ["A", "B", "C"]
            times = ["09:15", "12:00", "14:45"]
            idx = 0
            for day_idx in range(5):
                day = f"2026-06-{11 + day_idx:02d}"
                for time_text in times:
                    hour, minute = (int(part) for part in time_text.split(":"))
                    for symbol_idx, symbol in enumerate(symbols):
                        event_time = f"{day}T{time_text}:00+09:00"
                        prob_down = 0.2 + 0.2 * symbol_idx
                        future_return = (symbol_idx - 1) * 0.5 + (0.1 * day_idx)
                        conn.execute(
                            "INSERT INTO serving_trade_signals VALUES (?, ?, ?, 'buy', 0.5, 'baseline', 1)",
                            (f"sig-{idx}", symbol, event_time),
                        )
                        conn.execute(
                            "INSERT INTO serving_predictions VALUES (?, ?, ?, 15, 'lightgbm-h15-v1', ?, 0.1, ?)",
                            (f"pred-{idx}", symbol, event_time, 1.0 - prob_down, prob_down),
                        )
                        conn.execute(
                            "INSERT INTO feature_labels VALUES (?, ?, 15, 'flat', 0.35, ?)",
                            (symbol, event_time, future_return),
                        )
                        for offset in range(5, -1, -1):
                            bar_minute = minute - offset
                            bar_hour = hour
                            if bar_minute < 0:
                                bar_hour -= 1
                                bar_minute += 60
                            bar_time = f"{day}T{bar_hour:02d}:{bar_minute:02d}:00+09:00"
                            close = 100 + symbol_idx * 10 + day_idx + offset * (symbol_idx + 1) * 0.05
                            conn.execute(
                                "INSERT INTO curated_minute_bars VALUES (?, ?, ?, ?, ?, ?, 1000, 10)",
                                (symbol, bar_time, close, close, close, close),
                            )
                        idx += 1
            conn.commit()

            summary = build_summary(
                database_path=db_path,
                diagnostics_path=diagnostics_path,
                horizon_min=15,
                min_daily_rows=2,
            )

        self.assertEqual(summary["status"], "ok")
        criteria = summary["preregistered_criteria"]
        self.assertIn("decomposition_candidate_after_multiple_comparison", criteria)
        self.assertIn("0.03", criteria["decomposition_candidate_after_multiple_comparison"])
        self.assertIn("2.5", criteria["decomposition_candidate_after_multiple_comparison"])
        families = summary["decomposition"]["families"]
        self.assertEqual({entry["group_key"] for entry in families["time_bucket"]}, {"open_early", "midday", "close"})
        self.assertEqual({entry["group_key"] for entry in families["symbol"]}, set(symbols))
        self.assertIn("volatility_bucket", families)
        self.assertTrue(families["volatility_bucket"])
        open_entry = [entry for entry in families["time_bucket"] if entry["group_key"] == "open_early"][0]
        self.assertIn("probability_down", open_entry)
        self.assertIn("probability_up", open_entry)

if __name__ == "__main__":
    unittest.main()
