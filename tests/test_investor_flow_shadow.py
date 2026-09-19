from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
import unittest

from scripts.summarize_investor_flow_shadow import build_report, render_markdown


class InvestorFlowShadowTests(unittest.TestCase):
    def test_finalized_eod_flow_uses_only_labels_after_available_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "events.db"
            observations_path = root / "observations.jsonl"
            connection = sqlite3.connect(db_path)
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
                    ("005930", "2026-09-17T20:05:00+09:00", 15, "down", -0.9),
                    ("005930", "2026-09-18T09:15:00+09:00", 15, "up", 0.42),
                    ("035420", "2026-09-18T09:15:00+09:00", 15, "down", -0.31),
                ],
            )
            connection.commit()
            observations_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "observation_id": "krx-005930-foreign-20260917",
                                "source": "krx_manual_export",
                                "source_url": "https://data.krx.co.kr/example",
                                "market": "KOSPI",
                                "symbol": "005930",
                                "trade_date": "2026-09-17",
                                "investor_group": "foreign",
                                "net_value_krw": 1000000000,
                                "available_at": "2026-09-17T20:10:00+09:00",
                                "observed_at": "2026-09-17T20:12:00+09:00",
                                "completeness": "final",
                            }
                        ),
                        json.dumps(
                            {
                                "observation_id": "krx-005930-institution-20260917",
                                "source": "krx_manual_export",
                                "source_url": "https://data.krx.co.kr/example",
                                "market": "KOSPI",
                                "symbol": "005930",
                                "trade_date": "2026-09-17",
                                "investor_group": "institution",
                                "net_value_krw": 800000000,
                                "available_at": "2026-09-17T20:10:00+09:00",
                                "observed_at": "2026-09-17T20:12:00+09:00",
                                "completeness": "final",
                            }
                        ),
                        json.dumps(
                            {
                                "observation_id": "krx-035420-foreign-20260917",
                                "source": "krx_manual_export",
                                "source_url": "https://data.krx.co.kr/example",
                                "market": "KOSPI",
                                "symbol": "035420",
                                "trade_date": "2026-09-17",
                                "investor_group": "foreign",
                                "net_value_krw": -700000000,
                                "available_at": "2026-09-17T20:10:00+09:00",
                                "observed_at": "2026-09-17T20:12:00+09:00",
                                "completeness": "final",
                            }
                        ),
                        json.dumps(
                            {
                                "observation_id": "krx-035420-institution-20260917",
                                "source": "krx_manual_export",
                                "source_url": "https://data.krx.co.kr/example",
                                "market": "KOSPI",
                                "symbol": "035420",
                                "trade_date": "2026-09-17",
                                "investor_group": "institution",
                                "net_value_krw": -400000000,
                                "available_at": "2026-09-17T20:10:00+09:00",
                                "observed_at": "2026-09-17T20:12:00+09:00",
                                "completeness": "final",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_report(
                database_path=db_path,
                observations_path=observations_path,
                horizon_min=15,
                generated_at="2026-09-18T16:00:00+09:00",
            )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["flow_groups"], 2)
        self.assertEqual(report["summary"]["evaluated_groups"], 2)
        self.assertEqual(report["summary"]["directional_hit_rate"], 1.0)
        self.assertEqual(report["matches"][0]["label_event_time"], "2026-09-18T09:15:00+09:00")
        self.assertEqual(report["matches"][0]["flow_regime"], "both_net_buy")
        self.assertEqual(report["matches"][1]["flow_regime"], "both_net_sell")
        self.assertIn("E7", render_markdown(report))

    def test_missing_observations_file_is_safe_no_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_report(
                database_path=Path(tmp) / "missing.db",
                observations_path=Path(tmp) / "missing.jsonl",
                horizon_min=15,
                generated_at="2026-09-18T16:00:00+09:00",
            )

        self.assertEqual(report["status"], "no_observations_file")
        self.assertEqual(report["summary"]["flow_groups"], 0)

    def test_malformed_observations_fail_closed_without_database_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observations_path = root / "observations.jsonl"
            base = {
                "source": "krx_manual_export",
                "source_url": "https://data.krx.co.kr/example",
                "market": "KOSPI",
                "symbol": "005930",
                "trade_date": "2026-09-17",
                "investor_group": "foreign",
                "available_at": "2026-09-17T20:10:00+09:00",
                "observed_at": "2026-09-17T20:12:00+09:00",
                "completeness": "final",
            }
            observations_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                **base,
                                "observation_id": "invalid-net-value",
                                "net_value_krw": [],
                            }
                        ),
                        json.dumps(
                            {
                                **base,
                                "observation_id": "observed-before-available",
                                "net_value_krw": 1000,
                                "observed_at": "2026-09-17T20:09:00+09:00",
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
            {"invalid_net_value_krw", "observed_before_available_at"},
        )

    def test_duplicate_investor_group_is_excluded_from_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "events.db"
            observations_path = root / "observations.jsonl"
            connection = sqlite3.connect(db_path)
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
            connection.commit()
            base = {
                "source": "krx_manual_export",
                "source_url": "https://data.krx.co.kr/example",
                "market": "KOSPI",
                "symbol": "005930",
                "trade_date": "2026-09-17",
                "available_at": "2026-09-17T20:10:00+09:00",
                "observed_at": "2026-09-17T20:12:00+09:00",
                "completeness": "final",
            }
            observations_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                **base,
                                "observation_id": "foreign-first",
                                "investor_group": "foreign",
                                "net_value_krw": 1000,
                            }
                        ),
                        json.dumps(
                            {
                                **base,
                                "observation_id": "foreign-duplicate",
                                "investor_group": "foreign",
                                "net_value_krw": 2000,
                            }
                        ),
                        json.dumps(
                            {
                                **base,
                                "observation_id": "institution-only",
                                "investor_group": "institution",
                                "net_value_krw": 3000,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_report(
                database_path=db_path,
                observations_path=observations_path,
                horizon_min=15,
            )

        self.assertEqual(report["status"], "no_complete_two_sided_groups")
        self.assertEqual(report["summary"]["flow_groups"], 0)
        self.assertEqual(report["group_issues"][0]["reason"], "duplicate_investor_group_observation")


if __name__ == "__main__":
    unittest.main()
