import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from app.services.e7_daily_evidence import (
    E7_DAILY_EVIDENCE_SCHEMA_VERSION,
    E7_EVIDENCE_VALIDATION_VERSION,
    E7_EXPECTED_MANIFEST_SHA256,
    build_e7_daily_evidence,
    validate_e7_evidence_for_reuse,
    write_e7_daily_evidence_once,
)
from app.services.e7_portfolio_evaluator import E7_PORTFOLIO_REPLAY_MANIFEST
from app.services import e7_daily_evidence as evidence_service
from scripts import generate_e7_daily_evidence as daily_cli


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
            active_artifact_sha256 TEXT,
            shadow_predictions_json TEXT NOT NULL
        );
        CREATE TABLE serving_predictions (
            prediction_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            event_time TEXT NOT NULL,
            horizon_min INTEGER NOT NULL,
            model_version TEXT NOT NULL,
            probability_up REAL NOT NULL,
            probability_flat REAL NOT NULL,
            probability_down REAL NOT NULL,
            training_run_id TEXT,
            artifact_id TEXT,
            artifact_sha256 TEXT
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
                'signal_blocked', NULL, NULL, 'run-1', 'artifact-1', 'sha-1', ?
            )
            """,
            (f"decision-{index}", event_time.isoformat(), json.dumps([{
                "prediction_id": f"prediction-{index}",
                "model_version": "lightgbm-h15-v1",
                "training_run_id": "shadow-run-1",
                "artifact_id": "shadow-artifact-1",
                "artifact_sha256": "shadow-sha-1",
                "probability_up": probability_up,
                "probability_flat": 0.20,
                "probability_down": 0.20,
            }])),
        )
        connection.execute(
            """
            INSERT INTO serving_predictions VALUES (
                ?, '005930', ?, 15, 'lightgbm-h15-v1', ?, 0.20, 0.20,
                'shadow-run-1', 'shadow-artifact-1', 'shadow-sha-1'
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
        self.assertEqual(report["evidence_validation_version"], "e7-shadow-lineage-v2-exact-id")
        self.assertEqual(report["schema_version"], 3)
        self.assertTrue(report["source"]["shadow_lineage_validation"]["passed"])

    def _assert_lineage_blocked(self, report: dict, reason: str) -> None:
        self.assertEqual(report["official_evaluation_status"], "invalid_evidence")
        self.assertFalse(report["evidence_health"]["passed"])
        self.assertIn(reason, report["evidence_health"]["reasons"])
        self.assertFalse(report["profitability_assessment"]["strategy_failure"])
        for key in ("normal_cost", "double_cost", "random_control"):
            self.assertEqual(report[key]["status"], "blocked_invalid_evidence")
        self.assertEqual(report["future_intervals"]["interval_2_status"], "blocked_invalid_evidence")

    def test_shadow_identity_and_probability_mismatch_fail_closed(self) -> None:
        for key in ("prediction_id", "model_version", "training_run_id", "artifact_id",
                    "artifact_sha256", "probability_up", "probability_flat", "probability_down"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "runtime.db"
                _create_db(db_path, event_times=[START])
                with sqlite3.connect(db_path) as connection:
                    shadow = json.loads(connection.execute(
                        "SELECT shadow_predictions_json FROM serving_decision_ledger"
                    ).fetchone()[0])
                    shadow[0][key] = 0.21 if key.startswith("probability") else "different"
                    connection.execute(
                        "UPDATE serving_decision_ledger SET shadow_predictions_json = ?",
                        (json.dumps(shadow),),
                    )
                report = build_e7_daily_evidence(db_path, through_trading_day=START.date())
                reason = ("shadow_prediction_missing" if key == "model_version" else
                          "shadow_prediction_row_missing" if key == "prediction_id" else
                          "shadow_prediction_mismatch")
                self._assert_lineage_blocked(report, reason)

    def test_missing_prediction_is_not_silently_dropped_by_join(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START])
            with sqlite3.connect(db_path) as connection:
                connection.execute("DELETE FROM serving_predictions")
            report = build_e7_daily_evidence(db_path, through_trading_day=START.date())
        self._assert_lineage_blocked(report, "shadow_prediction_row_missing")
        self.assertEqual(report["source"]["future_decision_rows"], 1)

    def test_duplicate_shadow_entries_and_prediction_reuse_fail_closed(self) -> None:
        for duplicate in ("shadow_entry", "decision"):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "runtime.db"
                _create_db(db_path, event_times=[START])
                with sqlite3.connect(db_path) as connection:
                    if duplicate == "shadow_entry":
                        shadow = json.loads(connection.execute(
                            "SELECT shadow_predictions_json FROM serving_decision_ledger"
                        ).fetchone()[0])
                        connection.execute(
                            "UPDATE serving_decision_ledger SET shadow_predictions_json = ?",
                            (json.dumps(shadow * 2),),
                        )
                        reason = "shadow_predictions_ambiguous"
                    else:
                        connection.execute("""
                            INSERT INTO serving_decision_ledger
                            SELECT 'duplicate-decision', symbol, event_time, horizon_min,
                                   signal_side, signal_allowed, time_gate_allowed, spread_gate_allowed,
                                   decision_stage, order_id, fill_id, active_training_run_id,
                                   active_artifact_id, active_artifact_sha256, shadow_predictions_json
                            FROM serving_decision_ledger
                        """)
                        reason = "shadow_prediction_reused"
                report = build_e7_daily_evidence(db_path, through_trading_day=START.date())
                self._assert_lineage_blocked(report, reason)

    def test_exact_id_ignores_unreferenced_prediction_at_same_minute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START])
            with sqlite3.connect(db_path) as connection:
                connection.execute("""
                    INSERT INTO serving_predictions
                    SELECT 'unreferenced', symbol, event_time, horizon_min, model_version,
                           0.1, probability_flat, probability_down,
                           training_run_id, artifact_id, artifact_sha256
                    FROM serving_predictions
                """)
            report = build_e7_daily_evidence(db_path, through_trading_day=START.date())
        self.assertTrue(report["source"]["shadow_lineage_validation"]["passed"])
        self.assertEqual(report["source"]["joined_future_rows"], 1)
        self.assertEqual(report["episodes"], 1)

    def test_exact_id_checks_prediction_tuple(self) -> None:
        for key, value in (("symbol", "000660"), ("event_time", (START + timedelta(minutes=1)).isoformat()),
                           ("horizon_min", 60)):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "runtime.db"
                _create_db(db_path, event_times=[START])
                with sqlite3.connect(db_path) as connection:
                    connection.execute(f"UPDATE serving_predictions SET {key} = ?", (value,))
                report = build_e7_daily_evidence(db_path, through_trading_day=START.date())
                self._assert_lineage_blocked(report, "shadow_prediction_tuple_mismatch")

    def test_exact_id_reads_decisions_and_predictions_from_one_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START])
            with sqlite3.connect(db_path) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
            original = evidence_service._stored_shadow_prediction_id
            def concurrent_change(payload):
                with sqlite3.connect(db_path) as connection:
                    connection.execute("UPDATE serving_predictions SET probability_up = 0.1")
                return original(payload)
            with patch.object(evidence_service, "_stored_shadow_prediction_id", side_effect=concurrent_change):
                report = build_e7_daily_evidence(db_path, through_trading_day=START.date())
        self.assertTrue(report["source"]["shadow_lineage_validation"]["passed"])
        self.assertEqual(report["episodes"], 1)

    def test_exact_id_multiple_batches_keep_second_batch_fail_closed(self) -> None:
        count = 502
        last_id = sorted(f"prediction-{index}" for index in range(count))[-1]
        for failure, reason in (("missing", "shadow_prediction_row_missing"),
                                ("score", "shadow_prediction_mismatch"),
                                ("metadata", "shadow_prediction_mismatch")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "runtime.db"
                _create_db(db_path, event_times=[START + timedelta(minutes=index) for index in range(count)],
                           probability_up=0.4)
                valid = build_e7_daily_evidence(db_path, through_trading_day=START.date())
                self.assertTrue(valid["source"]["shadow_lineage_validation"]["passed"])
                self.assertEqual(valid["source"]["joined_future_rows"], count)
                with sqlite3.connect(db_path) as connection:
                    if failure == "missing":
                        connection.execute("DELETE FROM serving_predictions WHERE prediction_id = ?", (last_id,))
                    elif failure == "score":
                        connection.execute("UPDATE serving_predictions SET probability_up = 0.1 WHERE prediction_id = ?", (last_id,))
                    else:
                        connection.execute("UPDATE serving_predictions SET artifact_id = 'different' WHERE prediction_id = ?", (last_id,))
                report = build_e7_daily_evidence(db_path, through_trading_day=START.date())
                self._assert_lineage_blocked(report, reason)
                self.assertEqual(report["source"]["future_decision_rows"], count)
                self.assertEqual(report["source"]["shadow_lineage_validation"]["failed_decision_rows"], 1)

    def test_tuple_validator_artifact_is_not_promoted_to_exact_id_validator(self) -> None:
        payload = {"schema_version": 2, "evidence_validation_version": "e7-shadow-lineage-v1",
                   "official_evaluation_status": "collecting_future_sample",
                   "evidence_health": {"passed": True, "status": "valid_collecting", "reasons": []},
                   "source": {"shadow_lineage_validation": {"version": "e7-shadow-lineage-v1", "passed": True,
                                                            "reason_counts": {}}}}
        self._assert_lineage_blocked(validate_e7_evidence_for_reuse(payload),
                                     "shadow_lineage_validation_not_available")
        self.assertTrue(payload["evidence_health"]["passed"])

    def test_distinct_predictions_link_once_but_duplicate_decision_minute_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START, START])
            report = build_e7_daily_evidence(db_path, through_trading_day=START.date())
        self.assertEqual(report["source"]["joined_future_rows"], 2)
        self.assertEqual(report["source"]["future_decision_rows"], 2)
        self._assert_lineage_blocked(report, "duplicate_decision_minute")
        self.assertEqual(report["source"]["shadow_lineage_validation"]["reason_counts"],
                         {"duplicate_decision_minute": 2})

    def test_malformed_missing_and_nonfinite_shadow_values_fail_closed(self) -> None:
        for value, reason in (
            ("{invalid", "shadow_predictions_malformed"),
            ("{}", "shadow_predictions_malformed"),
            ("[null]", "shadow_predictions_malformed"),
            ("[]", "shadow_prediction_missing"),
        ):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "runtime.db"
                _create_db(db_path, event_times=[START])
                with sqlite3.connect(db_path) as connection:
                    connection.execute(
                        "UPDATE serving_decision_ledger SET shadow_predictions_json = ?", (value,)
                    )
                self._assert_lineage_blocked(
                    build_e7_daily_evidence(db_path, through_trading_day=START.date()), reason
                )
        for value in (float("nan"), float("inf"), -0.01, 1.01, True, None, "0.6"):
            with self.subTest(probability=value), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "runtime.db"
                _create_db(db_path, event_times=[START])
                with sqlite3.connect(db_path) as connection:
                    shadow = json.loads(connection.execute(
                        "SELECT shadow_predictions_json FROM serving_decision_ledger"
                    ).fetchone()[0])
                    shadow[0]["probability_up"] = value
                    connection.execute("UPDATE serving_decision_ledger SET shadow_predictions_json = ?",
                                       (json.dumps(shadow),))
                self._assert_lineage_blocked(
                    build_e7_daily_evidence(db_path, through_trading_day=START.date()),
                    "shadow_probability_invalid",
                )

    def test_missing_active_or_shadow_metadata_fail_closed(self) -> None:
        for table, column, reason in (
            ("serving_decision_ledger", "active_training_run_id", "active_lineage_incomplete"),
            ("serving_predictions", "artifact_sha256", "shadow_lineage_incomplete"),
        ):
            with self.subTest(column=column), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "runtime.db"
                _create_db(db_path, event_times=[START])
                with sqlite3.connect(db_path) as connection:
                    connection.execute(f"UPDATE {table} SET {column} = NULL")
                self._assert_lineage_blocked(
                    build_e7_daily_evidence(db_path, through_trading_day=START.date()), reason
                )

    def test_missing_lineage_schema_is_invalid_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START])
            with sqlite3.connect(db_path) as connection:
                connection.execute("ALTER TABLE serving_decision_ledger DROP COLUMN shadow_predictions_json")
            report = build_e7_daily_evidence(db_path, through_trading_day=START.date())
        self._assert_lineage_blocked(report, "required_lineage_columns_missing")

    def test_prediction_tuple_and_invalid_score_fail_closed(self) -> None:
        for column, value, reason in (
            ("symbol", "000000", "shadow_prediction_tuple_mismatch"),
            ("horizon_min", 60, "shadow_prediction_tuple_mismatch"),
            ("event_time", (START + timedelta(minutes=1)).isoformat(), "shadow_prediction_tuple_mismatch"),
            ("model_version", "other-model", "shadow_prediction_mismatch"),
            ("probability_up", float("inf"), "shadow_probability_invalid"),
            ("probability_flat", -0.1, "shadow_probability_invalid"),
        ):
            with self.subTest(column=column), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "runtime.db"
                _create_db(db_path, event_times=[START])
                with sqlite3.connect(db_path) as connection:
                    connection.execute(f"UPDATE serving_predictions SET {column} = ?", (value,))
                self._assert_lineage_blocked(
                    build_e7_daily_evidence(db_path, through_trading_day=START.date()), reason
                )

    def test_invalid_rows_before_future_start_do_not_block_future_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START - timedelta(minutes=1), START])
            with sqlite3.connect(db_path) as connection:
                connection.execute("UPDATE serving_decision_ledger SET shadow_predictions_json = '{}' WHERE decision_id = 'decision-0'")
            report = build_e7_daily_evidence(db_path, through_trading_day=START.date())
        self.assertTrue(report["evidence_health"]["passed"])
        self.assertEqual(report["source"]["future_decision_rows"], 1)
        self.assertEqual(report["episodes"], 1)

    def test_validation_fingerprint_tracks_identity_without_changing_evaluation_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START])
            before = build_e7_daily_evidence(db_path, through_trading_day=START.date())
            with sqlite3.connect(db_path) as connection:
                shadow = json.loads(connection.execute(
                    "SELECT shadow_predictions_json FROM serving_decision_ledger"
                ).fetchone()[0])
                shadow[0]["artifact_id"] = "another-valid-artifact"
                connection.execute("UPDATE serving_decision_ledger SET shadow_predictions_json = ?", (json.dumps(shadow),))
                connection.execute("UPDATE serving_predictions SET artifact_id = 'another-valid-artifact'")
            after = build_e7_daily_evidence(db_path, through_trading_day=START.date())
        self.assertTrue(after["evidence_health"]["passed"])
        self.assertEqual(before["source"]["source_fingerprint"], after["source"]["source_fingerprint"])
        self.assertNotEqual(before["source"]["shadow_lineage_validation"]["source_lineage_fingerprint"],
                            after["source"]["shadow_lineage_validation"]["source_lineage_fingerprint"])

    def test_legacy_daily_artifact_not_upgraded_or_reused_as_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dated, latest = root / "daily.json", root / "latest.json"
            legacy = {"schema_version": 1, "through_trading_day": "2026-08-31",
                      "evidence_health": {"passed": True, "status": "valid_collecting", "reasons": []}}
            dated.write_text(json.dumps(legacy))
            before = dated.read_bytes()
            stored, written = write_e7_daily_evidence_once(
                {"through_trading_day": "2026-08-31"}, dated_path=dated, latest_path=latest
            )
            self.assertEqual(dated.read_bytes(), before)
            self.assertFalse(latest.exists())
        self.assertFalse(written)
        self._assert_lineage_blocked(stored, "shadow_lineage_validation_not_available")

    def test_current_validation_cannot_claim_success_with_failed_proof(self) -> None:
        payload = {"schema_version": E7_DAILY_EVIDENCE_SCHEMA_VERSION, "evidence_validation_version": E7_EVIDENCE_VALIDATION_VERSION,
                   "official_evaluation_status": "collecting_future_sample",
                   "evidence_health": {"passed": True, "status": "valid_collecting", "reasons": []},
                   "source": {"shadow_lineage_validation": {"version": E7_EVIDENCE_VALIDATION_VERSION, "passed": False,
                                                            "reason_counts": {"shadow_prediction_missing": 1}}}}
        self._assert_lineage_blocked(
            validate_e7_evidence_for_reuse(payload), "shadow_lineage_validation_inconsistent"
        )
        self.assertTrue(payload["evidence_health"]["passed"])

    def test_cached_identity_drift_cannot_reuse_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START])
            valid = build_e7_daily_evidence(db_path, through_trading_day=START.date())
        for field, reason in (
            ("manifest_hash", "manifest_hash_drift"),
            ("current_manifest_hash", "manifest_hash_drift"),
            ("expected_manifest_hash", "manifest_hash_drift"),
            ("evaluator_version", "evaluator_version_drift"),
            ("expected_evaluator_version", "evaluator_version_drift"),
        ):
            for value in (None, "different-identity"):
                with self.subTest(field=field, value=value):
                    changed = {**valid, field: value}
                    self._assert_lineage_blocked(validate_e7_evidence_for_reuse(changed), reason)
        self.assertIs(validate_e7_evidence_for_reuse(valid), valid)

    def test_cli_cached_legacy_or_invalid_artifact_returns_failure_without_rewrite(self) -> None:
        for current in (False, True):
            with self.subTest(current=current), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                db_path = root / "runtime-data/dev.db"
                db_path.parent.mkdir(parents=True)
                db_path.touch()
                dated = root / "runtime-data/reports/research/e7/daily/2026-08-31.json"
                dated.parent.mkdir(parents=True)
                payload = {"through_trading_day": "2026-08-31", "schema_version": 1,
                           "evidence_health": {"status": "valid_collecting", "passed": True, "reasons": []}}
                if current:
                    payload.update(schema_version=E7_DAILY_EVIDENCE_SCHEMA_VERSION, evidence_validation_version=E7_EVIDENCE_VALIDATION_VERSION,
                                   official_evaluation_status="invalid_evidence",
                                   evidence_health={"status": "invalid", "passed": False, "reasons": ["shadow_prediction_missing"]},
                                   source={"shadow_lineage_validation": {"version": E7_EVIDENCE_VALIDATION_VERSION, "passed": False,
                                                                         "reason_counts": {"shadow_prediction_missing": 1}}})
                dated.write_text(json.dumps(payload))
                before = dated.read_bytes()
                with patch.object(daily_cli.sys, "argv", ["e7", "--project-root", str(root)]), \
                     patch.object(daily_cli, "load_settings", return_value=SimpleNamespace(timezone="Asia/Seoul", market_calendar=None)), \
                     patch.object(daily_cli, "now_local", return_value=START.replace(hour=20)), \
                     patch.object(daily_cli, "get_market_session_status", return_value="post-close"), \
                     patch.object(daily_cli, "is_market_holiday", return_value=False), \
                     patch.object(daily_cli, "_runtime_running", return_value=False), \
                     patch.object(daily_cli, "build_e7_daily_evidence") as build, redirect_stdout(StringIO()) as output:
                    self.assertEqual(daily_cli.main(), 1)
                build.assert_not_called()
                self.assertEqual(dated.read_bytes(), before)
                self.assertFalse(json.loads(output.getvalue())["report_written"])

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
            "schema_version": E7_DAILY_EVIDENCE_SCHEMA_VERSION,
            "evidence_validation_version": E7_EVIDENCE_VALIDATION_VERSION,
            "evaluator_version": E7_PORTFOLIO_REPLAY_MANIFEST.evaluator_version,
            "expected_evaluator_version": E7_PORTFOLIO_REPLAY_MANIFEST.evaluator_version,
            "manifest_hash": E7_EXPECTED_MANIFEST_SHA256,
            "current_manifest_hash": E7_EXPECTED_MANIFEST_SHA256,
            "expected_manifest_hash": E7_EXPECTED_MANIFEST_SHA256,
            "source": {"shadow_lineage_validation": {"version": E7_EVIDENCE_VALIDATION_VERSION, "passed": True, "reason_counts": {}}},
            "evidence_health": {"passed": True, "status": "valid_collecting", "reasons": []},
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
        self.assertTrue(stored_second["evidence_health"]["passed"])

    def test_database_is_opened_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            _create_db(db_path, event_times=[START])
            before = hashlib.sha256(db_path.read_bytes()).hexdigest()

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
            after = hashlib.sha256(db_path.read_bytes()).hexdigest()

        self.assertEqual(decision_count, 1)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
