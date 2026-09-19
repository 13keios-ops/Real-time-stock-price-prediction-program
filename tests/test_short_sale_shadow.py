from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
import unittest

from scripts.summarize_short_sale_shadow import build_report, render_markdown


class ShortSaleShadowTests(unittest.TestCase):
    def test_eod_short_sale_uses_later_labels_and_computes_position_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_path = root / "events.db"
            observations_path = root / "short_sale.jsonl"
            connection = sqlite3.connect(database_path)
            self.addCleanup(connection.close)
            connection.executescript(
                """
                CREATE TABLE feature_labels (
                    symbol TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    horizon_min INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    future_return_pct REAL NOT NULL
                );
                """
            )
            connection.executemany(
                "INSERT INTO feature_labels VALUES (?, ?, ?, ?, ?)",
                [
                    ("005930", "2026-09-17T19:59:00+09:00", 15, "up", 2.0),
                    ("005930", "2026-09-18T09:15:00+09:00", 15, "down", -0.41),
                    ("005930", "2026-09-19T09:15:00+09:00", 15, "up", 0.23),
                ],
            )
            connection.commit()
            base = {
                "source": "krx_manual_export",
                "source_url": "https://data.krx.co.kr/example",
                "market": "KOSPI",
                "symbol": "005930",
                "short_sale_volume": 100,
                "total_volume": 1000,
                "short_sale_value_krw": 7_000_000,
                "total_value_krw": 70_000_000,
                "observed_at": "2026-09-17T20:15:00+09:00",
                "completeness": "final",
            }
            observations_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                **base,
                                "observation_id": "short-001",
                                "trade_date": "2026-09-17",
                                "available_at": "2026-09-17T20:10:00+09:00",
                                "net_short_position_qty": 1000,
                                "net_short_position_value_krw": 70_000_000,
                            }
                        ),
                        json.dumps(
                            {
                                **base,
                                "observation_id": "short-002",
                                "trade_date": "2026-09-18",
                                "available_at": "2026-09-18T20:10:00+09:00",
                                "observed_at": "2026-09-18T20:15:00+09:00",
                                "net_short_position_qty": 1050,
                                "net_short_position_value_krw": 75_000_000,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_report(
                database_path=database_path,
                observations_path=observations_path,
                horizon_min=15,
                generated_at="2026-09-19T16:00:00+09:00",
            )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["observations"], 2)
        self.assertEqual(report["summary"]["matched"], 2)
        self.assertEqual(report["matches"][0]["short_volume_ratio_pct"], 10.0)
        self.assertIsNone(report["matches"][0]["net_short_position_qty_delta"])
        self.assertEqual(report["matches"][1]["net_short_position_qty_delta"], 50.0)
        self.assertEqual(report["matches"][0]["label_event_time"], "2026-09-18T09:15:00+09:00")
        self.assertIn("E7", render_markdown(report))

    def test_invalid_eod_values_fail_closed_before_database_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observations_path = root / "short_sale.jsonl"
            base = {
                "source": "krx_manual_export",
                "source_url": "https://data.krx.co.kr/example",
                "market": "KOSPI",
                "symbol": "005930",
                "trade_date": "2026-09-17",
                "short_sale_volume": 100,
                "short_sale_value_krw": 7_000_000,
                "total_value_krw": 70_000_000,
                "available_at": "2026-09-17T20:10:00+09:00",
                "observed_at": "2026-09-17T20:15:00+09:00",
                "completeness": "final",
            }
            observations_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                **base,
                                "observation_id": "zero-volume",
                                "total_volume": 0,
                            }
                        ),
                        json.dumps(
                            {
                                **base,
                                "observation_id": "before-availability",
                                "total_volume": 1000,
                                "observed_at": "2026-09-17T20:09:59+09:00",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_report(
                database_path=root / "must-not-open.db",
                observations_path=observations_path,
                horizon_min=15,
            )

        self.assertEqual(report["status"], "no_valid_observations")
        self.assertEqual(
            {row["reason"] for row in report["invalid_observations"]},
            {"invalid_total_volume", "observed_before_available_at"},
        )

    def test_missing_observations_file_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_report(
                database_path=Path(tmp) / "missing.db",
                observations_path=Path(tmp) / "missing.jsonl",
                horizon_min=15,
            )

        self.assertEqual(report["status"], "no_observations_file")
        self.assertEqual(report["summary"]["observations"], 0)


if __name__ == "__main__":
    unittest.main()
