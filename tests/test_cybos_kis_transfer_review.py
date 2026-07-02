from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
import unittest

from scripts.summarize_cybos_kis_transfer_review import summarize


def _event_time(month: int, day: int, index: int) -> str:
    minute_of_day = index % 390
    hour = 9 + minute_of_day // 60
    minute = minute_of_day % 60
    return f"2026-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00+09:00"


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE raw_market_ticks (
            symbol TEXT NOT NULL,
            event_time TEXT NOT NULL,
            price REAL NOT NULL,
            volume INTEGER NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE feature_model_inputs (
            symbol TEXT NOT NULL,
            event_time TEXT NOT NULL,
            feature_set_version TEXT NOT NULL,
            values_json TEXT NOT NULL,
            PRIMARY KEY (symbol, event_time, feature_set_version)
        );
        CREATE TABLE feature_labels (
            symbol TEXT NOT NULL,
            event_time TEXT NOT NULL,
            horizon_min INTEGER NOT NULL,
            label TEXT NOT NULL,
            threshold_pct REAL NOT NULL,
            future_return_pct REAL NOT NULL,
            PRIMARY KEY (symbol, event_time, horizon_min)
        );
        """
    )


def _insert_row(
    connection: sqlite3.Connection,
    *,
    source: str,
    symbol: str,
    event_time: str,
    feature_value: float,
    future_return_pct: float,
    spread_bps: float = 0.0,
) -> None:
    label = "up" if future_return_pct > 0.03 else "down" if future_return_pct < -0.03 else "flat"
    connection.execute(
        "INSERT INTO raw_market_ticks VALUES (?, ?, ?, ?, ?)",
        (symbol, event_time, 1000.0, 1, source),
    )
    connection.execute(
        "INSERT INTO feature_model_inputs VALUES (?, ?, ?, ?)",
        (
            symbol,
            event_time,
            "feature-set-v1",
            json.dumps(
                {
                    "return_1m_pct": feature_value,
                    "hl_range_pct": abs(feature_value) + 0.1,
                    "spread_bps": spread_bps,
                    "bid_ask_imbalance": 0.0,
                    "avg_trade_size": 1.0,
                    "mid_price": 1000.0,
                }
            ),
        ),
    )
    connection.execute(
        "INSERT INTO feature_labels VALUES (?, ?, ?, ?, ?, ?)",
        (symbol, event_time, 15, label, 0.03, future_return_pct),
    )


class CybosKisTransferReviewTests(unittest.TestCase):
    def test_detects_source_stable_feature_relationship(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "dev.db"
            with sqlite3.connect(db_path) as connection:
                _create_schema(connection)
                for index in range(600):
                    feature = -0.2 if index < 300 else 0.2
                    future = -0.1 if index < 300 else 0.1
                    _insert_row(
                        connection,
                        source="cybos-historical",
                        symbol="000001",
                        event_time=_event_time(5, 1 + index // 390, index),
                        feature_value=feature,
                        future_return_pct=future,
                    )
                    _insert_row(
                        connection,
                        source="kis-ws",
                        symbol="000001",
                        event_time=_event_time(6, 11 + index // 390, index),
                        feature_value=feature,
                        future_return_pct=future,
                    )
                connection.commit()

            report = summarize(
                db_path,
                cybos_sample_size=1_000,
                kis_sample_size=1_000,
                write_reports=False,
            )
            return_item = next(item for item in report["feature_transfer"] if item["feature"] == "return_1m_pct")
            self.assertEqual(return_item["transfer_grade"], "source_stable_candidate")
            self.assertGreater(return_item["kis_top_bottom_delta_pct"], 0.0)
            self.assertEqual(report["assessment"]["posture"], "kis_sample_still_small")

    def test_marks_orderbook_as_kis_only_when_cybos_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "dev.db"
            with sqlite3.connect(db_path) as connection:
                _create_schema(connection)
                for index in range(600):
                    feature = -0.2 if index < 300 else 0.2
                    future = -0.1 if index < 300 else 0.1
                    _insert_row(
                        connection,
                        source="cybos-historical",
                        symbol="000001",
                        event_time=_event_time(5, 1 + index // 390, index),
                        feature_value=feature,
                        future_return_pct=future,
                        spread_bps=0.0,
                    )
                    _insert_row(
                        connection,
                        source="kis-ws",
                        symbol="000001",
                        event_time=_event_time(6, 11 + index // 390, index),
                        feature_value=feature,
                        future_return_pct=future,
                        spread_bps=5.0 if index < 300 else 20.0,
                    )
                connection.commit()

            report = summarize(
                db_path,
                cybos_sample_size=1_000,
                kis_sample_size=1_000,
                write_reports=False,
            )
            spread_item = next(item for item in report["feature_transfer"] if item["feature"] == "spread_bps")
            self.assertEqual(spread_item["transfer_grade"], "kis_only_orderbook_watch")


if __name__ == "__main__":
    unittest.main()
