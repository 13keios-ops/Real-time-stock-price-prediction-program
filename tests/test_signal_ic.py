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


if __name__ == "__main__":
    unittest.main()
