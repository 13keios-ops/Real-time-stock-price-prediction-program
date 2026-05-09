from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_kis_live_feature_diagnostics import summarize


def _feature_payload(
    *,
    return_1m_pct: float,
    bid_ask_imbalance: float,
    spread_bps: float = 5.0,
) -> str:
    return json.dumps(
        {
            "avg_trade_size": 10.0,
            "hl_range_pct": 0.1,
            "mid_price": 70000.0,
            "return_1m_pct": return_1m_pct,
            "spread_bps": spread_bps,
            "bid_ask_imbalance": bid_ask_imbalance,
        },
        sort_keys=True,
    )


class KisLiveFeatureDiagnosticsTests(unittest.TestCase):
    def test_summarizes_labeled_kis_feature_relationships_after_cybos_overlap(self) -> None:
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
                    ("005930", "2026-05-08T09:00:01+09:00", 70100, 10, "kis-ws"),
                    ("005930", "2026-05-08T09:01:01+09:00", 70200, 10, "kis-ws"),
                    ("005930", "2026-05-08T09:02:01+09:00", 70300, 10, "kis-ws"),
                    ("005930", "2026-05-08T09:03:01+09:00", 70400, 10, "kis-ws"),
                ],
            )
            connection.executemany(
                "INSERT INTO raw_orderbook_ticks VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("005930", "2026-05-08T09:00:05+09:00", 70090, 70110, 100, 50, "kis-ws"),
                    ("005930", "2026-05-08T09:01:05+09:00", 70190, 70210, 100, 50, "kis-ws"),
                    ("005930", "2026-05-08T09:02:05+09:00", 70290, 70310, 50, 100, "kis-ws"),
                    ("005930", "2026-05-08T09:03:05+09:00", 70390, 70410, 50, 100, "kis-ws"),
                ],
            )
            rows = [
                ("2026-05-08T09:00:00+09:00", 0.20, 0.8, "up", 0.25),
                ("2026-05-08T09:01:00+09:00", 0.10, 0.4, "up", 0.15),
                ("2026-05-08T09:02:00+09:00", -0.10, -0.4, "down", -0.15),
                ("2026-05-08T09:03:00+09:00", -0.20, -0.8, "down", -0.25),
            ]
            connection.executemany(
                "INSERT INTO feature_model_inputs VALUES (?, ?, ?, ?)",
                [
                    ("005930", event_time, "feature-set-v1", _feature_payload(return_1m_pct=ret, bid_ask_imbalance=imbalance))
                    for event_time, ret, imbalance, _, _ in rows
                ],
            )
            connection.executemany(
                "INSERT INTO feature_labels VALUES (?, ?, ?, ?, ?, ?)",
                [("005930", event_time, 15, label, 0.13, future_return) for event_time, _, _, label, future_return in rows],
            )
            connection.commit()
            connection.close()

            report = summarize(
                database_path,
                recent_days=5,
                bucket_count=2,
                write_reports=False,
            )

        self.assertEqual(report["date_selection"], "post_cybos_overlap")
        self.assertEqual(report["sample"]["rows"], 4)
        self.assertEqual(report["sample"]["label_distribution"], {"down": 2, "up": 2})
        by_feature = {item["feature"]: item for item in report["feature_diagnostics"]}
        self.assertGreater(by_feature["bid_ask_imbalance"]["pearson_future_return"], 0.99)
        self.assertEqual(by_feature["bid_ask_imbalance"]["top_bottom_up_ratio_delta"], 1.0)
        self.assertEqual(by_feature["bid_ask_imbalance"]["buckets"][0]["label_distribution"], {"down": 2})
        self.assertEqual(by_feature["bid_ask_imbalance"]["buckets"][1]["label_distribution"], {"up": 2})


if __name__ == "__main__":
    unittest.main()
