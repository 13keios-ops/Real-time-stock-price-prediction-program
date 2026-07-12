import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_lightgbm_defensive_shadow import _trade_cost_context, build_summary


LINEAGE = ("train-1", "artifact-1", "sha-1")


class LightGbmDefensiveCostContextTests(unittest.TestCase):
    def test_missing_diagnostics_uses_current_shared_cost_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = _trade_cost_context(Path(tmp) / "missing.json")

        self.assertEqual(context["version"], "krx-common-stock-2026-v1")
        self.assertEqual(context["round_trip_cost_pct"], 0.29)
        self.assertEqual(context["source"], "shared_current_default")


def _create_schema(connection: sqlite3.Connection, *, include_paper: bool = True) -> None:
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
            probability_down REAL,
            training_run_id TEXT,
            artifact_id TEXT,
            artifact_sha256 TEXT
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
            volume REAL,
            trade_count INTEGER
        );
        """
    )
    if include_paper:
        connection.executescript(
            """
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
            """
        )


class LightGbmDefensiveShadowTests(unittest.TestCase):
    def test_buy_avoid_requires_portfolio_and_random_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shadow.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.1}\n', encoding="utf-8")
            connection = sqlite3.connect(db_path)
            self.addCleanup(connection.close)
            _create_schema(connection)
            connection.executemany(
                "INSERT INTO serving_trade_signals VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("sig-1", "005930", "2026-06-11T09:15:00+09:00", "buy", 0.6, "baseline", 1),
                    ("sig-2", "005930", "2026-06-11T09:16:00+09:00", "buy", 0.6, "baseline", 1),
                ],
            )
            prediction_rows = [
                ("p-1", "2026-06-11T09:15:00+09:00", 0.2, 0.2, 0.6),
                ("p-2", "2026-06-11T09:16:00+09:00", 0.6, 0.2, 0.2),
                ("p-exit", "2026-06-11T09:17:00+09:00", 0.2, 0.2, 0.6),
            ]
            connection.executemany(
                """
                INSERT INTO serving_predictions
                VALUES (?, '005930', ?, 15, 'lightgbm-h15-v1', ?, ?, ?, ?, ?, ?)
                """,
                [(*row, *LINEAGE) for row in prediction_rows],
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
            connection.executemany(
                "INSERT INTO curated_minute_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("005930", "2026-06-11T09:16:00+09:00", 100.0, 100.0, 100.0, 100.0, 1, 1),
                    ("005930", "2026-06-11T09:18:00+09:00", 99.0, 99.0, 99.0, 99.0, 1, 1),
                    ("005930", "2026-06-11T09:30:00+09:00", 101.0, 101.0, 101.0, 101.0, 1, 1),
                ],
            )
            connection.commit()

            summary = build_summary(
                database_path=db_path,
                diagnostics_path=diagnostics_path,
                horizon_min=15,
                thresholds=[0.5],
                require_down_argmax=True,
                random_simulations=20,
            )

        self.assertEqual(summary["status"], "rejected_random_control")
        self.assertEqual(summary["cost_model_version"], "legacy_or_custom_unversioned")
        self.assertEqual(summary["cost_model"]["source"], "diagnostics_report")
        self.assertTrue(summary["prediction_lineage"]["candidate_eligible"])
        buy_avoid = summary["buy_avoid_shadow"]["thresholds"][0]
        self.assertEqual(buy_avoid["skipped"]["signals"], 1)
        self.assertGreater(buy_avoid["delta"]["net_return_pct"], 0)
        self.assertFalse(
            buy_avoid["portfolio_replay"]["candidate_eligibility"]["passed"]
        )
        replay = buy_avoid["portfolio_replay"]
        self.assertEqual(summary["portfolio_parameters"]["random_simulations"], 20)
        self.assertEqual(summary["portfolio_parameters"]["random_seed"], 42)
        self.assertEqual(
            replay["baseline"]["execution_price_basis"],
            "next_minute_open_after_completed_signal",
        )
        self.assertEqual(replay["baseline"]["closed_trades"][0]["entry_time"], "2026-06-11T09:16:00+09:00")
        self.assertEqual(replay["portfolio_random_control"]["seed"], 42)
        early_exit = summary["early_exit_shadow"]
        self.assertEqual(early_exit["status"], "diagnostic_only_future_validation_required")
        self.assertFalse(early_exit["candidate_eligible"])
        self.assertEqual(early_exit["thresholds"][0]["early_exit_lots"], 1)
        self.assertLess(early_exit["thresholds"][0]["delta"]["net_return_pct"], 0)

    def test_window_filter_and_e5_only_mode_exclude_outside_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shadow-window.db"
            diagnostics_path = Path(tmp) / "diagnostics.json"
            diagnostics_path.write_text('{"trade_cost_pct": 0.1}\n', encoding="utf-8")
            connection = sqlite3.connect(db_path)
            self.addCleanup(connection.close)
            _create_schema(connection, include_paper=False)
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
                    """
                    INSERT INTO serving_predictions
                    VALUES (?, '005930', ?, 15, 'lightgbm-h15-v1', 0.2, 0.2, 0.6, ?, ?, ?)
                    """,
                    (f"pred-{prefix}", event_time, *LINEAGE),
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
        self.assertEqual(summary["early_exit_shadow"]["status"], "not_evaluated_for_windowed_e5")


if __name__ == "__main__":
    unittest.main()