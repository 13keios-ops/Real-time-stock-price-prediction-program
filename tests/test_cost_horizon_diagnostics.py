import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_cost_horizon_diagnostics import build_summary


class CostHorizonDiagnosticsTests(unittest.TestCase):
    def test_h15_median_below_two_times_cost_sets_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cost.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.108}\n', encoding="utf-8")
            conn = sqlite3.connect(db_path)
            self.addCleanup(conn.close)
            conn.execute(
                """
                CREATE TABLE feature_labels (
                    symbol TEXT,
                    event_time TEXT,
                    horizon_min INTEGER,
                    label TEXT,
                    threshold_pct REAL,
                    future_return_pct REAL
                )
                """
            )
            for idx, value in enumerate([-0.10, -0.08, 0.06, 0.12, 0.18]):
                conn.execute(
                    "INSERT INTO feature_labels VALUES ('005930', ?, 15, 'flat', 0.35, ?)",
                    (f"2026-06-11T09:{15 + idx:02d}:00+09:00", value),
                )
            conn.commit()

            summary = build_summary(database_path=db_path, diagnostics_path=diagnostics_path, horizons=(15, 60))

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["decision"]["status"], "h15_median_move_below_2x_cost")
        self.assertTrue(summary["decision"]["filter_tuning_only_warning"])
        h60 = [row for row in summary["horizons"] if row["horizon_min"] == 60][0]
        self.assertEqual(h60["status"], "no_labels")

    def test_h15_median_above_cost_does_not_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cost.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.108}\n', encoding="utf-8")
            conn = sqlite3.connect(db_path)
            self.addCleanup(conn.close)
            conn.execute(
                """
                CREATE TABLE feature_labels (
                    symbol TEXT,
                    event_time TEXT,
                    horizon_min INTEGER,
                    label TEXT,
                    threshold_pct REAL,
                    future_return_pct REAL
                )
                """
            )
            for idx, value in enumerate([-0.40, -0.30, 0.35, 0.50, 0.80]):
                conn.execute(
                    "INSERT INTO feature_labels VALUES ('005930', ?, 15, 'up', 0.35, ?)",
                    (f"2026-06-11T09:{15 + idx:02d}:00+09:00", value),
                )
            conn.commit()

            summary = build_summary(database_path=db_path, diagnostics_path=diagnostics_path, horizons=(15,))

        self.assertEqual(summary["decision"]["status"], "h15_median_move_covers_2x_cost")
        self.assertFalse(summary["decision"]["filter_tuning_only_warning"])


if __name__ == "__main__":
    unittest.main()
