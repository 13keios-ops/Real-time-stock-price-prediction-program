import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.services.e7_daily_evidence import (
    E7_EXPECTED_MANIFEST_SHA256,
    build_e7_daily_evidence,
    write_e7_daily_evidence_once,
)
from app.services.e7_portfolio_evaluator import E7_PORTFOLIO_REPLAY_MANIFEST


START = E7_PORTFOLIO_REPLAY_MANIFEST.future_evaluation_start


def _create_db(
    path: Path,
    *,
    event_times: list[datetime],
    probability_up: float = 0.60,
    missing_bar_minute: int | None = None,
) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE serving_decision_ledger (
            decision_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            event_time TEXT NOT NULL,
            horizon_min INTEGER NOT NULL,
            signal_side TEXT,
            signal_allowed INTEGER,
            time_gate_allowed INTEGER,
            spread_gate_allowed INTEGER,
            decision_stage TEXT,
            order_id TEXT,
            fill_id TEXT,
            active_training_run_id TEXT,
            active_artifact_id TEXT,
            active_artifact_sha256 TEXT
        );
        CREATE TABLE serving_predictions (
            prediction_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            event_time TEXT NOT NULL,
            horizon_min INTEGER NOT NULL,
            model_version TEXT NOT NULL,
            probability_up REAL NOT NULL,
            probability_flat REAL NOT NULL,
            probability_down REAL NOT NULL
        );
        CREATE TABLE curated_minute_bars (
            symbol TEXT NOT NULL,
            bar_time TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER NOT NULL,
            trade_count INTEGER NOT NULL,
            PRIMARY KEY (symbol, bar_time)
        );
        """
    )
    for index, event_time in enumerate(event_times):
        connection.execute(
            """
            INSERT INTO serving_decision_ledger VALUES (
                ?, '005930', ?, 15, 'hold', 0, 1, 1,
                'signal_blocked', NULL, NULL, 'run-1', 'artifact-1', 'sha-1'
            )
            """,
            (f"decision-{index}", event_time.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO serving_predictions VALUES (
                ?, '005930', ?, 15, 'lightgbm-h15-v1', ?, 0.20, 0.20
            )
            """,
            (f"prediction-{index}", event_time.isoformat(), probability_up),
        )
    bar_start = START.replace(minute=15)
    for minute_index in range(17):
        bar_time = bar_start + timedelta(minutes=minute_index)
        if missing_bar_minute is not None and minute_index == missing_bar_minute:
            continue
        connection.execute(
            """
            INSERT INTO curated_minute_bars
            VALUES ('005930', ?, 70000, 70100, 69900, 70000, 100, 10)
            """,
            (bar_time.isoformat(),),
        )
    connection.commit()
    connection.close()


class E7DailyEvidenceTests(unittest.TestCase):
    def test_first_future_day_is_collecting_not_strategy_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START])

            report = build_e7_daily_evidence(
                db_path,
                through_trading_day=date(2026, 8, 31),
                generated_at=datetime(2026, 8, 31, 12, tzinfo=timezone.utc),
            )

        self.assertEqual(report["future_trading_days"], 1)
        self.assertEqual(report["episodes"], 1)
        self.assertEqual(report["symbols"], 1)
        self.assertGreater(report["mark_observation_count"], 0)
        self.assertEqual(report["missing_mark_count"], 0)
        self.assertEqual(report["stale_mark_count"], 0)
        self.assertEqual(report["invalid_mark_count"], 0)
        self.assertEqual(
            report["official_evaluation_status"],
            "collecting_future_sample",
        )
        self.assertFalse(report["profitability_assessment"]["strategy_failure"])
        self.assertEqual(report["normal_cost"]["status"], "waiting_minimum_sample")
        self.assertEqual(
            report["normal_cost"]["prerequisite_status"],
            "waiting_minimum_sample",
        )
        self.assertEqual(report["double_cost"]["status"], "waiting_minimum_sample")
        self.assertFalse(report["random_control"]["completed"])
        self.assertEqual(report["random_control"]["completed_simulations"], 0)
        self.assertEqual(report["minimum_requirements"]["status"], "not_met")
        self.assertEqual(report["manifest_hash"], E7_EXPECTED_MANIFEST_SHA256)

    def test_evaluator_and_manifest_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START])

            evaluator_drift = build_e7_daily_evidence(
                db_path,
                through_trading_day=date(2026, 8, 31),
                observed_evaluator_version="portfolio-replay-v1-entry-mark",
            )
            manifest_drift = build_e7_daily_evidence(
                db_path,
                through_trading_day=date(2026, 8, 31),
                observed_manifest_hash="different-manifest",
            )

        self.assertEqual(evaluator_drift["evidence_health"]["status"], "invalid")
        self.assertIn(
            "evaluator_version_drift",
            evaluator_drift["evidence_health"]["reasons"],
        )
        self.assertEqual(manifest_drift["evidence_health"]["status"], "invalid")
        self.assertIn(
            "manifest_hash_drift",
            manifest_drift["evidence_health"]["reasons"],
        )
        self.assertEqual(
            evaluator_drift["official_evaluation_status"], "invalid_evidence"
        )

    def test_missing_exact_minute_mark_invalidates_evidence_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(
                db_path,
                event_times=[START],
                missing_bar_minute=5,
            )

            report = build_e7_daily_evidence(
                db_path,
                through_trading_day=date(2026, 8, 31),
            )

        self.assertEqual(report["evidence_health"]["status"], "invalid")
        self.assertGreater(report["stale_mark_count"], 0)
        self.assertGreater(report["invalid_mark_count"], 0)
        self.assertEqual(
            report["normal_cost"]["status"], "blocked_invalid_evidence"
        )
        self.assertFalse(report["profitability_assessment"]["strategy_failure"])

    def test_rows_before_future_start_never_enter_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(
                db_path,
                event_times=[START - timedelta(minutes=1)],
            )

            report = build_e7_daily_evidence(
                db_path,
                through_trading_day=date(2026, 8, 31),
            )

        self.assertEqual(report["future_trading_days"], 0)
        self.assertEqual(report["episodes"], 0)
        self.assertEqual(report["symbol_list"], [])
        self.assertEqual(
            report["official_evaluation_status"], "not_available_yet"
        )

    def test_same_day_artifact_is_idempotent(self) -> None:
        first = {
            "through_trading_day": "2026-08-31",
            "generated_at": "first",
        }
        second = {
            "through_trading_day": "2026-08-31",
            "generated_at": "second",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dated = root / "daily/2026-08-31.json"
            latest = root / "latest.json"

            stored_first, wrote_first = write_e7_daily_evidence_once(
                first,
                dated_path=dated,
                latest_path=latest,
            )
            stored_second, wrote_second = write_e7_daily_evidence_once(
                second,
                dated_path=dated,
                latest_path=latest,
            )

            dated_payload = json.loads(dated.read_text(encoding="utf-8"))
            latest_payload = json.loads(latest.read_text(encoding="utf-8"))

        self.assertTrue(wrote_first)
        self.assertFalse(wrote_second)
        self.assertEqual(stored_first["generated_at"], "first")
        self.assertEqual(stored_second["generated_at"], "first")
        self.assertEqual(dated_payload["generated_at"], "first")
        self.assertEqual(latest_payload["generated_at"], "first")

    def test_database_is_opened_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START])
            before = db_path.stat().st_size

            build_e7_daily_evidence(
                db_path,
                through_trading_day=date(2026, 8, 31),
            )

            connection = sqlite3.connect(db_path)
            try:
                decision_count = connection.execute(
                    "SELECT COUNT(*) FROM serving_decision_ledger"
                ).fetchone()[0]
            finally:
                connection.close()
            after = db_path.stat().st_size

        self.assertEqual(decision_count, 1)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
