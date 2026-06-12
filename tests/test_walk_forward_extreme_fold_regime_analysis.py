import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_walk_forward_extreme_fold_regimes import build_summary


class WalkForwardExtremeFoldRegimeAnalysisTests(unittest.TestCase):
    def test_extreme_fold_regime_analysis_adds_label_and_bar_hypotheses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "regime.db"
            connection = sqlite3.connect(db_path)
            self.addCleanup(connection.close)
            connection.executescript(
                """
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
                    volume REAL,
                    trade_count INTEGER
                );
                """
            )
            label_rows = [
                ("005930", "2026-01-02T09:00:00+09:00", 15, "flat", 0.35, 0.01),
                ("005930", "2026-01-02T09:01:00+09:00", 15, "flat", 0.35, -0.01),
                ("005930", "2026-01-02T09:02:00+09:00", 15, "flat", 0.35, 0.02),
                ("005930", "2026-01-02T09:03:00+09:00", 15, "down", 0.35, -1.0),
            ]
            bar_rows = [
                ("005930", "2026-01-02T09:00:00+09:00", 100.0, 100.0, 100.0, 100.0, 1, 1),
                ("005930", "2026-01-02T09:01:00+09:00", 100.0, 104.0, 96.0, 104.0, 1, 1),
                ("005930", "2026-01-02T09:02:00+09:00", 104.0, 104.0, 90.0, 90.0, 1, 1),
                ("005930", "2026-01-02T09:03:00+09:00", 90.0, 110.0, 90.0, 110.0, 1, 1),
            ]
            connection.executemany("INSERT INTO feature_labels VALUES (?, ?, ?, ?, ?, ?)", label_rows)
            connection.executemany("INSERT INTO curated_minute_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?)", bar_rows)
            connection.commit()
            report = {
                "evaluation_id": "wf-test",
                "evaluated_at": "2026-01-03T00:00:00+09:00",
                "fold_summaries": [
                    {
                        "fold": 1,
                        "test_start_event_time": "2026-01-02T09:00:00+09:00",
                        "test_end_event_time": "2026-01-02T09:03:00+09:00",
                        "three_class_accuracy": 0.10,
                        "up_hit_rate": 0.5,
                        "flat_hit_rate": 0.0,
                        "down_hit_rate": 0.5,
                        "virtual_direction_cumulative_net_return_pct": -5.0,
                        "confusion_matrix": {
                            "flat": {"up": 3, "flat": 0, "down": 0},
                            "down": {"up": 0, "flat": 0, "down": 1},
                        },
                    },
                    {
                        "fold": 2,
                        "test_start_event_time": "2026-01-02T09:00:00+09:00",
                        "test_end_event_time": "2026-01-02T09:03:00+09:00",
                        "three_class_accuracy": 0.80,
                        "up_hit_rate": 0.8,
                        "flat_hit_rate": 0.8,
                        "down_hit_rate": 0.8,
                        "virtual_direction_cumulative_net_return_pct": 1.0,
                        "confusion_matrix": {"flat": {"flat": 3}, "down": {"down": 1}},
                    },
                ],
            }

            summary = build_summary(
                report,
                database_path=db_path,
                horizon_min=15,
                worst_count=1,
                best_count=1,
            )

        self.assertEqual(summary["worst_folds"][0]["fold"], 1)
        hypotheses = summary["worst_folds"][0]["hypotheses"]
        self.assertTrue(any(item.startswith("actual_label_imbalance:flat") for item in hypotheses))
        self.assertTrue(any(item.startswith("low_flat_hit_rate") for item in hypotheses))
        self.assertTrue(any(item.startswith("negative_virtual_direction_net") for item in hypotheses))
        self.assertGreater(
            summary["worst_folds"][0]["bar_regime"]["minute_return_volatility_pct"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
