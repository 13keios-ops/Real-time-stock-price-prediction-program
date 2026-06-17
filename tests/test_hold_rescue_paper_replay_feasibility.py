from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone

from scripts.summarize_hold_rescue_paper_replay_feasibility import (
    FillEvent,
    analyze_database,
    reconstruct_closed_lots,
    render_markdown,
)


class HoldRescuePaperReplayFeasibilityTests(unittest.TestCase):
    def test_reconstruct_closed_lots_counts_orphan_sells(self) -> None:
        fills = [
            FillEvent(
                order_id="sell-before-buy",
                symbol="005930",
                side="sell",
                event_time=datetime(2026, 6, 11, 9, 10, tzinfo=timezone.utc),
                price=70000.0,
                qty=1.0,
            ),
            FillEvent(
                order_id="buy-after",
                symbol="005930",
                side="buy",
                event_time=datetime(2026, 6, 11, 9, 11, tzinfo=timezone.utc),
                price=69900.0,
                qty=2.0,
            ),
        ]

        closed, summary = reconstruct_closed_lots(fills)

        self.assertEqual(closed, [])
        self.assertEqual(summary["orphan_sell_events"], 1)
        self.assertEqual(summary["orphan_sell_qty"], 1.0)
        self.assertEqual(summary["open_qty_by_symbol"], {"005930": 2.0})

    def test_analyze_database_matches_exit_prediction_and_future_bar(self) -> None:
        connection = sqlite3.connect(":memory:")
        _create_schema(connection)
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
                ("f-buy", "o-buy", "2026-06-11T09:10:12+09:00", 70000.0, 1.0),
                ("f-sell", "o-sell", "2026-06-11T09:20:42+09:00", 70100.0, 1.0),
            ],
        )
        connection.execute(
            """
            INSERT INTO serving_predictions(
                symbol, event_time, horizon_min, model_version,
                probability_up, probability_flat, probability_down, predicted_label
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("005930", "2026-06-11T09:20:00+09:00", 15, "lightgbm-h15-v1", 0.62, 0.20, 0.18, "up"),
        )
        connection.executemany(
            "INSERT INTO curated_minute_bars(symbol, bar_time, close) VALUES (?, ?, ?)",
            [
                ("005930", "2026-06-11T09:34:00+09:00", 70150.0),
                ("005930", "2026-06-11T09:35:00+09:00", 70200.0),
            ],
        )

        report = analyze_database(
            connection,
            database_path=":memory:",
            since_date="2026-06-11",
            horizon_min=15,
            model_version="lightgbm-h15-v1",
            forced_flat_time="15:20",
        )

        self.assertEqual(report["fill_source"]["status"], "ok")
        self.assertEqual(report["closed_lot_summary"]["closed_lots"], 1)
        self.assertEqual(report["closed_lot_summary"]["lightgbm_exit_prediction_matches"], 1)
        self.assertEqual(report["closed_lot_summary"]["future_bar_matches"], 1)
        self.assertEqual(report["decision"]["status"], "not_ready")
        self.assertIn("offline feasibility only", report["decision"]["scope_guardrail"])

    def test_render_markdown_marks_report_as_feasibility_not_performance(self) -> None:
        report = {
            "decision": {
                "status": "not_ready",
                "recommended_action": "표본 추가",
                "scope_guardrail": "offline feasibility only",
                "minimums": {
                    "closed_lots": 50,
                    "lightgbm_exit_prediction_matches": 30,
                    "future_bar_matches": 30,
                    "symbols": 3,
                },
                "blockers": ["closed_lot_sample_too_small"],
                "warnings": [],
            },
            "closed_lot_summary": {
                "closed_lots": 1,
                "symbols": 1,
                "lightgbm_exit_prediction_matches": 1,
                "lightgbm_exit_prediction_match_rate": 1.0,
                "future_bar_matches": 1,
                "future_bar_match_rate": 1.0,
                "avg_hold_minutes": 10.0,
                "cash_delta_sum": 100.0,
            },
            "since_date": "2026-06-11",
            "horizon_min": 15,
            "model_version": "lightgbm-h15-v1",
        }

        markdown = render_markdown(report)

        self.assertIn("준비도 점검", markdown)
        self.assertIn("성과가 아니라", markdown)
        self.assertIn("관련 문서/코드 경로", markdown)


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


if __name__ == "__main__":
    unittest.main()
