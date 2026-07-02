from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
import unittest

from scripts.summarize_social_signal_shadow import build_report, render_markdown


class SocialSignalShadowTests(unittest.TestCase):
    def test_social_events_match_future_labels_directionally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "events.db"
            events_path = root / "events.jsonl"
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
            connection.execute(
                "INSERT INTO feature_labels VALUES (?, ?, ?, ?, ?)",
                ("005930", "2026-07-03T09:20:00+09:00", 15, "up", 0.42),
            )
            connection.execute(
                "INSERT INTO feature_labels VALUES (?, ?, ?, ?, ?)",
                ("035420", "2026-07-03T09:25:00+09:00", 15, "down", -0.51),
            )
            connection.commit()
            events_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "event_id": "e1",
                                "source": "manual",
                                "author_id": "person-a",
                                "published_at": "2026-07-03T09:10:00+09:00",
                                "symbols": ["005930"],
                                "event_type": "executive_comment",
                                "impact_direction": "positive",
                            }
                        ),
                        json.dumps(
                            {
                                "event_id": "e2",
                                "source": "manual",
                                "author_id": "person-b",
                                "published_at": "2026-07-03T09:12:00+09:00",
                                "symbols": ["035420"],
                                "event_type": "market_comment",
                                "impact_direction": "negative",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_report(
                database_path=db_path,
                events_path=events_path,
                horizon_min=15,
                max_lag_minutes=60,
                generated_at="2026-07-03T10:00:00+09:00",
            )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["matched"], 2)
        self.assertEqual(report["summary"]["directional_hit_rate"], 1.0)
        markdown = render_markdown(report)
        self.assertIn("Social Signal Shadow", markdown)
        self.assertIn("Phase 1", markdown)

    def test_missing_event_file_is_safe_no_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_report(
                database_path=Path(tmp) / "missing.db",
                events_path=Path(tmp) / "missing.jsonl",
                horizon_min=15,
                generated_at="2026-07-03T10:00:00+09:00",
            )

        self.assertEqual(report["status"], "no_events_file")
        self.assertEqual(report["summary"]["events"], 0)


if __name__ == "__main__":
    unittest.main()
