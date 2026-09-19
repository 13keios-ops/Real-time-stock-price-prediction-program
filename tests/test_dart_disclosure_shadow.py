from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
import unittest

from scripts.summarize_dart_disclosure_shadow import build_report, render_markdown


class DartDisclosureShadowTests(unittest.TestCase):
    def test_disclosures_use_only_labels_after_recorded_availability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_path = root / "events.db"
            events_path = root / "dart_events.jsonl"
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
                    ("005930", "2026-09-17T17:59:00+09:00", 15, "down", -1.1),
                    ("005930", "2026-09-18T09:15:00+09:00", 15, "up", 0.42),
                    ("035420", "2026-09-18T09:15:00+09:00", 15, "down", -0.31),
                ],
            )
            connection.commit()
            events_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "event_id": "dart-001",
                                "source": "opendart_manual_export",
                                "source_url": "https://dart.fss.or.kr/example/001",
                                "symbol": "005930",
                                "disclosure_type": "contract_or_order",
                                "impact_direction": "positive",
                                "available_at": "2026-09-17T18:00:00+09:00",
                                "observed_at": "2026-09-17T18:02:00+09:00",
                                "publication_state": "published",
                            }
                        ),
                        json.dumps(
                            {
                                "event_id": "dart-002",
                                "source": "opendart_manual_export",
                                "source_url": "https://dart.fss.or.kr/example/002",
                                "symbol": "035420",
                                "disclosure_type": "capital_structure",
                                "impact_direction": "negative",
                                "available_at": "2026-09-17T18:00:00+09:00",
                                "observed_at": "2026-09-17T18:02:00+09:00",
                                "publication_state": "published",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_report(
                database_path=database_path,
                events_path=events_path,
                horizon_min=15,
                generated_at="2026-09-18T16:00:00+09:00",
            )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["events"], 2)
        self.assertEqual(report["summary"]["matched"], 2)
        self.assertEqual(report["summary"]["directional_hit_rate"], 1.0)
        self.assertEqual(report["matches"][0]["label_event_time"], "2026-09-18T09:15:00+09:00")
        self.assertIn("E7", render_markdown(report))

    def test_invalid_or_duplicate_disclosures_fail_closed_before_database_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "dart_events.jsonl"
            valid = {
                "event_id": "duplicate-id",
                "source": "opendart_manual_export",
                "source_url": "https://dart.fss.or.kr/example",
                "symbol": "005930",
                "disclosure_type": "contract_or_order",
                "impact_direction": "positive",
                "available_at": "2026-09-17T18:00:00+09:00",
                "observed_at": "2026-09-17T18:02:00+09:00",
                "publication_state": "published",
            }
            events_path.write_text(
                "\n".join(
                    [
                        json.dumps(valid),
                        json.dumps(valid),
                        json.dumps(
                            {
                                **valid,
                                "event_id": "observed-too-early",
                                "observed_at": "2026-09-17T17:59:59+09:00",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_report(
                database_path=root / "must-not-open.db",
                events_path=events_path,
                horizon_min=15,
            )

        self.assertEqual(report["status"], "no_valid_events")
        self.assertEqual(
            {row["reason"] for row in report["invalid_events"]},
            {"duplicate_event_id", "observed_before_available_at"},
        )

    def test_missing_event_file_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_report(
                database_path=Path(tmp) / "missing.db",
                events_path=Path(tmp) / "missing.jsonl",
                horizon_min=15,
            )

        self.assertEqual(report["status"], "no_events_file")
        self.assertEqual(report["summary"]["events"], 0)


if __name__ == "__main__":
    unittest.main()
