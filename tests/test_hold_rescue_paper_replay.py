from __future__ import annotations

import sqlite3
import unittest

from app.paper_trading.costs import DOMESTIC_STOCK_COST_MODEL_VERSION
from scripts.summarize_hold_rescue_paper_replay import (
    DEFAULT_TRADE_COST_PCT,
    analyze_database,
    render_markdown,
)


class HoldRescuePaperReplayTests(unittest.TestCase):
    def test_replay_improves_when_exit_up_probability_stays_high(self) -> None:
        connection = sqlite3.connect(":memory:")
        _create_schema(connection)
        _insert_basic_lot(connection, exit_probability_up=0.70, future_probability_up=0.68)

        report = analyze_database(
            connection,
            database_path=":memory:",
            since_date="2026-06-11",
            horizon_min=15,
            model_version="lightgbm-h15-v1",
            thresholds=(0.65,),
            max_extension_minutes=2,
            max_loss_pct=2.0,
            trade_cost_pct=DEFAULT_TRADE_COST_PCT,
            forced_flat_time="15:20",
        )

        result = report["replay"]["threshold_results"][0]
        self.assertEqual(report["eligibility"]["eligible_lots"], 1)
        self.assertEqual(result["applied_lots"], 1)
        self.assertGreater(result["delta_cash_sum"], 0.0)
        self.assertEqual(result["exit_reasons"], {"max_extension_or_forced_flat": 1})

        self.assertEqual(report["cost_model_version"], DOMESTIC_STOCK_COST_MODEL_VERSION)
        self.assertTrue(report["cost_model"]["matches_current_model"])

    def test_replay_does_not_apply_when_exit_up_probability_is_low(self) -> None:
        connection = sqlite3.connect(":memory:")
        _create_schema(connection)
        _insert_basic_lot(connection, exit_probability_up=0.50, future_probability_up=0.80)

        report = analyze_database(
            connection,
            database_path=":memory:",
            since_date="2026-06-11",
            horizon_min=15,
            model_version="lightgbm-h15-v1",
            thresholds=(0.65,),
            max_extension_minutes=2,
            max_loss_pct=2.0,
            trade_cost_pct=DEFAULT_TRADE_COST_PCT,
            forced_flat_time="15:20",
        )

        result = report["replay"]["threshold_results"][0]
        self.assertEqual(result["applied_lots"], 0)
        self.assertEqual(result["delta_cash_sum"], 0.0)
        self.assertEqual(result["exit_reasons"], {"threshold_not_met": 1})

    def test_markdown_marks_report_as_paper_only_not_policy_change(self) -> None:
        report = {
            "decision": {
                "status": "diagnostic_only_no_hold_rescue_candidate",
                "recommended_action": "hold-rescue 우선순위 하향",
                "scope_guardrail": "paper-only offline replay",
                "candidate_thresholds": [],
            },
            "eligibility": {
                "closed_lots": 1,
                "eligible_lots": 1,
                "excluded_lots": 0,
                "excluded_reasons": {},
            },
            "replay": {
                "thresholds": [0.65],
                "exit_probability_up_distribution": {"count": 1, "min": 0.5, "max": 0.5},
                "threshold_results": [
                    {
                        "threshold": 0.65,
                        "applied_lots": 0,
                        "applied_rate": 0.0,
                        "baseline_cash_delta_sum": 100.0,
                        "strategy_cash_delta_sum": 100.0,
                        "delta_cash_sum": 0.0,
                        "improved_applied_share": 0.0,
                        "nonnegative_day_share": 0.0,
                        "exit_reasons": {"threshold_not_met": 1},
                    }
                ]
            },
            "since_date": "2026-06-11",
            "horizon_min": 15,
            "model_version": "lightgbm-h15-v1",
            "max_extension_minutes": 15,
            "max_loss_pct": 2.0,
            "trade_cost_pct": DEFAULT_TRADE_COST_PCT,
            "cost_model_version": DOMESTIC_STOCK_COST_MODEL_VERSION,
        }

        markdown = render_markdown(report)

        self.assertIn("paper-only", markdown)
        self.assertIn("주문 정책", markdown)
        self.assertIn("관련 문서/코드 경로", markdown)
        self.assertIn(DOMESTIC_STOCK_COST_MODEL_VERSION, markdown)


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE paper_orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            status TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE paper_fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            event_time TEXT NOT NULL,
            fill_price REAL NOT NULL,
            fill_qty REAL NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE serving_predictions (
            symbol TEXT NOT NULL,
            event_time TEXT NOT NULL,
            horizon_min INTEGER NOT NULL,
            model_version TEXT NOT NULL,
            probability_up REAL,
            probability_flat REAL,
            probability_down REAL,
            predicted_label TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE curated_minute_bars (
            symbol TEXT NOT NULL,
            bar_time TEXT NOT NULL,
            close REAL NOT NULL
        )
        """
    )


def _insert_basic_lot(
    connection: sqlite3.Connection,
    *,
    exit_probability_up: float,
    future_probability_up: float,
) -> None:
    connection.executemany(
        "INSERT INTO paper_orders(order_id, symbol, side, status) VALUES (?, ?, ?, ?)",
        [
            ("o-buy", "005930", "buy", "filled"),
            ("o-sell", "005930", "sell", "filled"),
        ],
    )
    connection.executemany(
        "INSERT INTO paper_fills(fill_id, order_id, event_time, fill_price, fill_qty) VALUES (?, ?, ?, ?, ?)",
        [
            ("f-buy", "o-buy", "2026-06-11T09:10:12+09:00", 100.0, 1.0),
            ("f-sell", "o-sell", "2026-06-11T09:20:42+09:00", 101.0, 1.0),
        ],
    )
    connection.executemany(
        """
        INSERT INTO serving_predictions(
            symbol, event_time, horizon_min, model_version,
            probability_up, probability_flat, probability_down, predicted_label
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("005930", "2026-06-11T09:20:00+09:00", 15, "lightgbm-h15-v1", exit_probability_up, 0.20, 0.10, "up"),
            ("005930", "2026-06-11T09:21:00+09:00", 15, "lightgbm-h15-v1", future_probability_up, 0.20, 0.12, "up"),
            ("005930", "2026-06-11T09:22:00+09:00", 15, "lightgbm-h15-v1", future_probability_up, 0.20, 0.12, "up"),
        ],
    )
    connection.executemany(
        "INSERT INTO curated_minute_bars(symbol, bar_time, close) VALUES (?, ?, ?)",
        [
            ("005930", "2026-06-11T09:21:00+09:00", 102.0),
            ("005930", "2026-06-11T09:22:00+09:00", 103.0),
        ],
    )


if __name__ == "__main__":
    unittest.main()
