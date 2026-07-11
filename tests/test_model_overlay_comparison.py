import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_model_overlay_comparison import build_report, render_markdown


class ModelOverlayComparisonTests(unittest.TestCase):
    def test_lightgbm_and_linear_score_overlay_roles_are_compared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "overlay.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.1}\n', encoding="utf-8")
            connection = sqlite3.connect(db_path)
            self.addCleanup(connection.close)
            connection.executescript(
                """
                CREATE TABLE feature_model_inputs (
                    symbol TEXT,
                    event_time TEXT,
                    feature_set_version TEXT,
                    values_json TEXT
                );
                CREATE TABLE feature_labels (
                    symbol TEXT,
                    event_time TEXT,
                    horizon_min INTEGER,
                    label TEXT,
                    threshold_pct REAL,
                    future_return_pct REAL
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
                CREATE TABLE serving_trade_signals (
                    signal_id TEXT,
                    symbol TEXT,
                    event_time TEXT,
                    side TEXT,
                    confidence REAL,
                    reason TEXT,
                    allowed INTEGER
                );
                CREATE TABLE serving_decision_ledger (
                    symbol TEXT,
                    event_time TEXT,
                    signal_side TEXT,
                    signal_allowed INTEGER,
                    time_gate_allowed INTEGER,
                    spread_gate_allowed INTEGER,
                    decision_stage TEXT,
                    decision_reason TEXT,
                    order_id TEXT,
                    fill_id TEXT
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
            feature_rows = [
                ("005930", "2026-06-11T09:15:00+09:00", "feature-set-v1", '{"return_1m_pct": -1.0, "bid_ask_imbalance": -1.0, "spread_bps": 1.0, "hl_range_pct": 0.1}'),
                ("005930", "2026-06-11T09:16:00+09:00", "feature-set-v1", '{"return_1m_pct": 1.0, "bid_ask_imbalance": 1.0, "spread_bps": 0.1, "hl_range_pct": 0.1}'),
                ("005930", "2026-06-11T09:17:00+09:00", "feature-set-v1", '{"return_1m_pct": 1.0, "bid_ask_imbalance": 1.0, "spread_bps": 0.1, "hl_range_pct": 0.1}'),
                ("005930", "2026-06-11T09:18:00+09:00", "feature-set-v1", '{"return_1m_pct": -1.0, "bid_ask_imbalance": -1.0, "spread_bps": 1.0, "hl_range_pct": 0.1}'),
                ("005930", "2026-06-11T09:25:00+09:00", "feature-set-v1", '{"return_1m_pct": 1.0, "bid_ask_imbalance": 1.0, "spread_bps": 0.1, "hl_range_pct": 0.1}'),
                ("005930", "2026-06-11T09:26:00+09:00", "feature-set-v1", '{"return_1m_pct": 1.0, "bid_ask_imbalance": 1.0, "spread_bps": 0.1, "hl_range_pct": 0.1}'),
            ]
            connection.executemany("INSERT INTO feature_model_inputs VALUES (?, ?, ?, ?)", feature_rows)
            labels = [
                ("005930", "2026-06-11T09:15:00+09:00", 15, "down", 0.35, -1.0),
                ("005930", "2026-06-11T09:16:00+09:00", 15, "up", 0.35, 1.0),
                ("005930", "2026-06-11T09:17:00+09:00", 15, "up", 0.35, 1.2),
                ("005930", "2026-06-11T09:18:00+09:00", 15, "down", 0.35, -1.2),
                ("005930", "2026-06-11T09:25:00+09:00", 15, "up", 0.35, 0.6),
                ("005930", "2026-06-11T09:26:00+09:00", 15, "up", 0.35, 0.4),
            ]
            connection.executemany("INSERT INTO feature_labels VALUES (?, ?, ?, ?, ?, ?)", labels)
            predictions = [
                ("p1", "005930", "2026-06-11T09:15:00+09:00", 15, "lightgbm-h15-v1", 0.2, 0.2, 0.6),
                ("p2", "005930", "2026-06-11T09:16:00+09:00", 15, "lightgbm-h15-v1", 0.6, 0.2, 0.2),
                ("p3", "005930", "2026-06-11T09:17:00+09:00", 15, "lightgbm-h15-v1", 0.7, 0.2, 0.1),
                ("p4", "005930", "2026-06-11T09:18:00+09:00", 15, "lightgbm-h15-v1", 0.2, 0.2, 0.6),
                ("p5", "005930", "2026-06-11T09:25:00+09:00", 15, "lightgbm-h15-v1", 0.7, 0.2, 0.1),
                ("p6", "005930", "2026-06-11T09:26:00+09:00", 15, "lightgbm-h15-v1", 0.7, 0.2, 0.1),
            ]
            connection.executemany("INSERT INTO serving_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", predictions)
            signals = [
                ("s1", "005930", "2026-06-11T09:15:00+09:00", "buy", 0.6, "baseline", 1),
                ("s2", "005930", "2026-06-11T09:16:00+09:00", "buy", 0.6, "baseline", 1),
                ("s3", "005930", "2026-06-11T09:17:00+09:00", "sell", 0.6, "baseline", 0),
                ("s4", "005930", "2026-06-11T09:18:00+09:00", "sell", 0.6, "baseline", 0),
            ]
            connection.executemany("INSERT INTO serving_trade_signals VALUES (?, ?, ?, ?, ?, ?, ?)", signals)
            decisions = [
                ("005930", "2026-06-11T09:17:00+09:00", "sell", 0, 1, 1, "signal_blocked", "long_only_policy", None, None),
                ("005930", "2026-06-11T09:18:00+09:00", "sell", 0, 1, 1, "signal_blocked", "long_only_policy", None, None),
            ]
            connection.executemany(
                "INSERT INTO serving_decision_ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                decisions,
            )
            orders = [
                ("buy-1", "005930", "2026-06-11T09:20:00+09:00", "buy", 1, 100.0, "filled", None, None, None),
                ("sell-1", "005930", "2026-06-11T09:25:00+09:00", "sell", 1, 101.0, "filled", None, None, None),
            ]
            fills = [
                ("fb", "buy-1", "2026-06-11T09:20:00+09:00", 100.0, 1, 0.0, 0.0),
                ("fs", "sell-1", "2026-06-11T09:25:00+09:00", 101.0, 1, 0.0, 0.0),
            ]
            bars = [
                ("005930", "2026-06-11T09:26:00+09:00", 101.0, 102.0, 101.0, 102.0, 1, 1),
            ]
            connection.executemany("INSERT INTO paper_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", orders)
            connection.executemany("INSERT INTO paper_fills VALUES (?, ?, ?, ?, ?, ?, ?)", fills)
            connection.executemany("INSERT INTO curated_minute_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?)", bars)
            connection.commit()

            report = build_report(
                database_path=db_path,
                diagnostics_path=diagnostics_path,
                horizon_min=15,
                since_date="2026-06-11",
                avoid_thresholds=(0.4,),
                rescue_thresholds=(0.4,),
                hold_thresholds=(0.4,),
                require_down_argmax=True,
                require_up_argmax=True,
                max_extension_minutes=10,
                max_loss_pct=1.2,
                forced_flat_time="15:10",
            )

        self.assertEqual(report["status"], "ok")
        models = {model["name"]: model for model in report["models"]}
        self.assertIn("LightGBM", models)
        self.assertIn("linear-score", models)
        self.assertGreater(models["LightGBM"]["buy_avoid"]["best"]["delta_net_return_pct_points"], 0)
        self.assertGreater(models["linear-score"]["buy_avoid"]["best"]["delta_net_return_pct_points"], 0)
        self.assertGreater(models["LightGBM"]["buy_rescue"]["best"]["rescued_net_return_pct_points"], 0)
        self.assertGreater(models["linear-score"]["buy_rescue"]["best"]["rescued_net_return_pct_points"], 0)
        self.assertFalse(models["LightGBM"]["buy_avoid"]["candidate"])
        self.assertFalse(models["LightGBM"]["buy_rescue"]["candidate"])
        self.assertEqual(report["decision_ledger"]["status"], "ok")
        self.assertEqual(report["decision_ledger"]["rescue_eligible_rows"], 2)
        self.assertIn("combination_policy_review", report)
        self.assertEqual(report["combination_policy_review"]["status"], "ok")
        self.assertIsNone(report["combination_policy_review"]["best_policy"])
        self.assertIsNotNone(report["combination_policy_review"]["best_diagnostic_policy"])
        self.assertIn("strength_segments", models["LightGBM"]["classification"])
        self.assertIn("top_accuracy_segments", models["linear-score"]["classification"]["strength_segments"])
        markdown = render_markdown(report)
        self.assertIn("LightGBM", markdown)
        self.assertIn("linear-score", markdown)
        self.assertIn("모델 조합 후보", markdown)
        self.assertIn("모델별 강점 구간", markdown)
        self.assertIn("주문 정책", markdown)


if __name__ == "__main__":
    unittest.main()
