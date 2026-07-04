import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_cost_horizon_diagnostics import build_summary


SCHEMA = """
CREATE TABLE feature_labels (
    symbol TEXT,
    event_time TEXT,
    horizon_min INTEGER,
    label TEXT,
    threshold_pct REAL,
    future_return_pct REAL
)
"""


class CostHorizonDiagnosticsTests(unittest.TestCase):
    def test_h15_falls_back_to_all_when_kis_live_subset_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cost.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.108}\n', encoding="utf-8")
            conn = sqlite3.connect(db_path)
            self.addCleanup(conn.close)
            conn.execute(SCHEMA)
            for idx, value in enumerate([-0.10, -0.08, 0.06, 0.12, 0.18]):
                conn.execute(
                    "INSERT INTO feature_labels VALUES ('005930', ?, 15, 'flat', 0.35, ?)",
                    (f"2026-06-10T09:{15 + idx:02d}:00+09:00", value),
                )
            conn.commit()

            summary = build_summary(database_path=db_path, diagnostics_path=diagnostics_path, horizons=(15, 60))

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["decision"]["policy_source"], "all_fallback_no_kis_live_subset")
        self.assertEqual(summary["decision"]["status"], "all_fallback_no_kis_live_subset_h15_median_move_below_2x_cost")
        self.assertTrue(summary["decision"]["filter_tuning_only_warning"])
        h60 = [row for row in summary["horizons"] if row["horizon_min"] == 60][0]
        self.assertEqual(h60["status"], "no_labels")

    def test_h15_kis_live_source_split_drives_policy_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cost.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.108}\n', encoding="utf-8")
            conn = sqlite3.connect(db_path)
            self.addCleanup(conn.close)
            conn.execute(SCHEMA)
            conn.execute(
                """
                CREATE TABLE serving_predictions (
                    prediction_id TEXT,
                    symbol TEXT,
                    event_time TEXT,
                    horizon_min INTEGER,
                    model_version TEXT,
                    probability_up REAL,
                    probability_flat REAL,
                    probability_down REAL
                )
                """
            )
            # Cybos-like historical rows dominate the all-source population and sit below 2x cost.
            for idx, value in enumerate([-0.08, 0.09, -0.10, 0.11, 0.12, -0.13]):
                conn.execute(
                    "INSERT INTO feature_labels VALUES ('005930', ?, 15, 'flat', 0.35, ?)",
                    (f"2026-06-10T09:{10 + idx:02d}:00+09:00", value),
                )
            # KIS-live approximation rows are after the start date and use a runtime symbol.
            for idx, value in enumerate([-0.30, 0.32, -0.35, 0.40]):
                event_time = f"2026-06-11T09:{10 + idx:02d}:00+09:00"
                conn.execute(
                    "INSERT INTO feature_labels VALUES ('005930', ?, 15, 'up', 0.35, ?)",
                    (event_time, value),
                )
                conn.execute(
                    "INSERT INTO serving_predictions VALUES (?, '005930', ?, 15, 'model', 0.5, 0.2, 0.3)",
                    (f"p{idx}", event_time),
                )
            conn.commit()

            summary = build_summary(database_path=db_path, diagnostics_path=diagnostics_path, horizons=(15,))

        self.assertEqual(summary["decision"]["policy_source"], "kis_live")
        self.assertEqual(summary["decision"]["status"], "kis_live_h15_median_move_covers_2x_cost")
        self.assertFalse(summary["decision"]["filter_tuning_only_warning"])
        sources = {row["source_key"]: row for row in summary["source_summaries"]}
        self.assertTrue(sources["all"]["horizons"][0]["median_abs_less_than_2x_cost"])
        self.assertFalse(sources["kis_live"]["horizons"][0]["median_abs_less_than_2x_cost"])
        self.assertAlmostEqual(sources["kis_live"]["horizons"][0]["share_of_all_rows"], 0.4)
        self.assertIn("do not carry a source column", summary["source_classification"]["method_note"])

    def test_baseline_buy_join_source_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cost.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.108}\n', encoding="utf-8")
            conn = sqlite3.connect(db_path)
            self.addCleanup(conn.close)
            conn.execute(SCHEMA)
            conn.execute(
                """
                CREATE TABLE serving_trade_signals (
                    signal_id TEXT,
                    symbol TEXT,
                    event_time TEXT,
                    side TEXT,
                    confidence REAL,
                    reason TEXT,
                    allowed INTEGER
                )
                """
            )
            for idx, value in enumerate([0.22, -0.24, 0.31]):
                event_time = f"2026-06-11T09:{20 + idx:02d}:00+09:00"
                conn.execute(
                    "INSERT INTO feature_labels VALUES ('005930', ?, 15, 'up', 0.35, ?)",
                    (event_time, value),
                )
                conn.execute(
                    "INSERT INTO serving_trade_signals VALUES (?, '005930', ?, 'buy', 0.7, 'baseline', 1)",
                    (f"s{idx}", event_time),
                )
            conn.commit()

            summary = build_summary(database_path=db_path, diagnostics_path=diagnostics_path, horizons=(15,))

        sources = {row["source_key"]: row for row in summary["source_summaries"]}
        baseline = sources["kis_live_baseline_buy_join"]["horizons"][0]
        self.assertEqual(baseline["status"], "ok")
        self.assertEqual(baseline["rows"], 3)
        self.assertEqual(sources["kis_live_baseline_buy_join"]["role"], "diagnostic_runtime_buy_signals")


if __name__ == "__main__":
    unittest.main()
