from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_feature_source_drift import summarize


def _feature_payload(
    *,
    avg_trade_size: float,
    hl_range_pct: float,
    mid_price: float,
    return_1m_pct: float,
    spread_bps: float,
    bid_ask_imbalance: float,
) -> str:
    return json.dumps(
        {
            "avg_trade_size": avg_trade_size,
            "hl_range_pct": hl_range_pct,
            "mid_price": mid_price,
            "return_1m_pct": return_1m_pct,
            "spread_bps": spread_bps,
            "bid_ask_imbalance": bid_ask_imbalance,
        },
        sort_keys=True,
    )


class FeatureSourceDriftSummaryTests(unittest.TestCase):
    def test_flags_orderbook_feature_drift_between_cybos_and_kis_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "test.db"
            connection = sqlite3.connect(database_path)
            connection.executescript(
                """
                CREATE TABLE raw_market_ticks (
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE TABLE raw_orderbook_ticks (
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    bid_price REAL NOT NULL,
                    ask_price REAL NOT NULL,
                    bid_size INTEGER NOT NULL,
                    ask_size INTEGER NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE TABLE feature_model_inputs (
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    feature_set_version TEXT NOT NULL,
                    values_json TEXT NOT NULL
                );
                CREATE TABLE feature_labels (
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    horizon_min INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    threshold_pct REAL NOT NULL,
                    future_return_pct REAL NOT NULL
                );
                """
            )
            connection.executemany(
                "INSERT INTO raw_market_ticks VALUES (?, ?, ?, ?, ?)",
                [
                    ("005930", "2026-05-01T09:00:00+09:00", 70000, 100, "cybos-historical"),
                    ("005930", "2026-05-01T09:15:00+09:00", 70100, 120, "cybos-historical"),
                    ("005930", "2026-05-08T09:00:01+09:00", 70200, 10, "kis-ws"),
                    ("005930", "2026-05-08T09:01:01+09:00", 70250, 12, "kis-ws"),
                ],
            )
            connection.executemany(
                "INSERT INTO raw_orderbook_ticks VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("005930", "2026-05-08T09:00:05+09:00", 70190, 70210, 100, 60, "kis-ws"),
                    ("005930", "2026-05-08T09:01:05+09:00", 70240, 70260, 50, 90, "kis-ws"),
                ],
            )
            connection.executemany(
                "INSERT INTO feature_model_inputs VALUES (?, ?, ?, ?)",
                [
                    (
                        "005930",
                        "2026-05-01T09:00:00+09:00",
                        "feature-set-v1",
                        _feature_payload(
                            avg_trade_size=1000.0,
                            hl_range_pct=0.10,
                            mid_price=70000.0,
                            return_1m_pct=0.0,
                            spread_bps=0.0,
                            bid_ask_imbalance=0.0,
                        ),
                    ),
                    (
                        "005930",
                        "2026-05-01T09:15:00+09:00",
                        "feature-set-v1",
                        _feature_payload(
                            avg_trade_size=1200.0,
                            hl_range_pct=0.20,
                            mid_price=70100.0,
                            return_1m_pct=0.1,
                            spread_bps=0.0,
                            bid_ask_imbalance=0.0,
                        ),
                    ),
                    (
                        "005930",
                        "2026-05-08T09:00:00+09:00",
                        "feature-set-v1",
                        _feature_payload(
                            avg_trade_size=10.0,
                            hl_range_pct=0.12,
                            mid_price=70200.0,
                            return_1m_pct=0.05,
                            spread_bps=5.0,
                            bid_ask_imbalance=0.5,
                        ),
                    ),
                    (
                        "005930",
                        "2026-05-08T09:01:00+09:00",
                        "feature-set-v1",
                        _feature_payload(
                            avg_trade_size=12.0,
                            hl_range_pct=0.14,
                            mid_price=70250.0,
                            return_1m_pct=-0.02,
                            spread_bps=6.0,
                            bid_ask_imbalance=-0.4,
                        ),
                    ),
                ],
            )
            connection.executemany(
                "INSERT INTO feature_labels VALUES (?, ?, ?, ?, ?, ?)",
                [
                    ("005930", "2026-05-01T09:00:00+09:00", 15, "flat", 0.13, 0.0),
                    ("005930", "2026-05-01T09:15:00+09:00", 15, "up", 0.13, 0.2),
                    ("005930", "2026-05-08T09:00:00+09:00", 15, "down", 0.13, -0.2),
                    ("005930", "2026-05-08T09:01:00+09:00", 15, "up", 0.13, 0.2),
                ],
            )
            connection.commit()
            connection.close()

            report = summarize(
                database_path,
                kis_recent_days=5,
                cybos_sample_size=10,
                cybos_lookback_days=10,
                write_reports=False,
            )

        self.assertEqual(report["kis_date_selection"], "post_cybos_overlap")
        self.assertEqual(report["samples"]["kis_live"]["rows"], 2)
        self.assertEqual(report["samples"]["cybos_historical"]["rows"], 2)
        self.assertEqual(report["assessment"]["posture"], "source_drift_detected")
        findings_by_feature = {item["feature"]: item for item in report["drift_findings"]}
        self.assertIn("spread_bps", findings_by_feature)
        self.assertIn("bid_ask_imbalance", findings_by_feature)
        self.assertIn("orderbook_feature_source_mismatch", findings_by_feature["spread_bps"]["flags"])
        self.assertEqual(findings_by_feature["spread_bps"]["cybos_zero_ratio"], 1.0)
        self.assertEqual(findings_by_feature["spread_bps"]["kis_zero_ratio"], 0.0)


if __name__ == "__main__":
    unittest.main()
