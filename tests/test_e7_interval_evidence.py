from datetime import datetime, timedelta
import importlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.services.e7_daily_evidence import build_e7_daily_evidence
from app.services.e7_portfolio_evaluator import run_e7_portfolio_replay
from tests.test_e7_daily_evidence import _create_db, START


ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/e7-post-recovery-acceptance-20261009.json"


class E7IntervalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("app.services.e7_interval_evidence"),
                             "fixed-interval trusted evidence producer is missing")
        self.service = importlib.import_module("app.services.e7_interval_evidence")
        self.contract = self.service.load_post_recovery_contract(RECORD)
        self.interval = self.contract.future_intervals[0]
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / ".tmp-tests")
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "fixture.db"

    def populate(self, *, historical_duplicate=False):
        times = []
        for offset in range(12):
            day = self.interval.start + timedelta(days=offset)
            if day.weekday() < 5:
                for minute in (0, 20):
                    times.extend([day + timedelta(minutes=minute)] * 5)
        if historical_duplicate:
            times.extend([START, START])
        _create_db(self.db, event_times=times)
        with sqlite3.connect(self.db) as connection:
            connection.execute("DELETE FROM curated_minute_bars")
            for index, event in enumerate(times):
                symbol = f"S{index % 5}"
                if event == START:
                    symbol = "HISTORY"
                connection.execute("UPDATE serving_decision_ledger SET symbol=? WHERE decision_id=?",
                                   (symbol, f"decision-{index}"))
                connection.execute("UPDATE serving_predictions SET symbol=? WHERE prediction_id=?",
                                   (symbol, f"prediction-{index}"))
                for minute in range(17):
                    connection.execute("INSERT OR IGNORE INTO curated_minute_bars VALUES (?, ?, 100, 101, 99, 100, 100, 1)",
                                       (symbol, (event + timedelta(minutes=minute)).isoformat()))

    def produce(self, *, approved=True, now=None):
        return self.service.produce_interval_evidence(
            self.db, acceptance_contract=self.contract, future_interval=self.interval,
            approved_contract_hash=self.contract.sha256 if approved else None,
            generated_at=now or self.interval.end + timedelta(hours=1),
        )

    def test_not_started_does_not_open_database(self):
        result = self.produce(now=self.interval.start - timedelta(days=1))
        self.assertEqual(result.report["status"], "not_started")
        self.assertFalse(result.report["database_access_started"])
        self.assertIsNone(result.report["source_acceptance"])
        self.assertIsNone(result.context)

    def test_historical_duplicates_do_not_contaminate_fixed_interval(self):
        self.populate(historical_duplicate=True)
        cumulative = build_e7_daily_evidence(self.db, through_trading_day=self.interval.end.date())
        self.assertEqual(cumulative["official_evaluation_status"], "invalid_evidence")
        result = self.produce()
        self.assertEqual(result.report["future_trading_days"], 10)
        self.assertEqual(result.report["episodes"], 100)
        self.assertEqual(result.report["symbols"], 5)
        self.assertEqual(result.report["source"]["future_decision_rows"], 100)
        self.assertEqual(result.report["status"], "ready_for_official_evaluation")
        self.assertTrue(result.report["source_acceptance"]["official_evaluation_permitted"])
        replay = run_e7_portfolio_replay(
            result.decisions, context=result.context, future_interval=self.interval,
            result_role="e7_policy", cost_scenario="normal", respect_decision_avoid=True,
            source_acceptance=result.report["source_acceptance"], acceptance_contract=self.contract,
            approved_contract_hash=self.contract.sha256,
        )
        self.assertEqual(replay["source_acceptance"]["contract_hash"], self.contract.sha256)

    def test_inside_interval_duplicate_blocks_proof(self):
        self.populate()
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE serving_decision_ledger SET event_time=? WHERE decision_id='decision-5'",
                               (self.interval.start.isoformat(),))
            connection.execute("UPDATE serving_predictions SET event_time=? WHERE prediction_id='prediction-5'",
                               (self.interval.start.isoformat(),))
        result = self.produce()
        self.assertEqual(result.report["status"], "invalid_evidence")
        self.assertIn("duplicate_decision_minute", result.report["blocking_reasons"])
        self.assertIsNone(result.report["source_acceptance"])

    def test_prediction_mismatch_blocks_proof(self):
        self.populate()
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE serving_predictions SET probability_up=0.61 WHERE prediction_id='prediction-0'")
        result = self.produce()
        self.assertIn("shadow_prediction_mismatch", result.report["blocking_reasons"])
        self.assertIsNone(result.report["source_acceptance"])

    def test_validator_version_drift_cannot_issue_old_contract_proof(self):
        self.populate()
        with patch("app.services.e7_daily_evidence.E7_EVIDENCE_VALIDATION_VERSION", "unexpected-validator"):
            result = self.produce()
        self.assertEqual(result.report["status"], "invalid_evidence")
        self.assertIn("validator_version_drift", result.report["blocking_reasons"])
        self.assertIsNone(result.report["source_acceptance"])

    def test_missing_mark_blocks_whole_population(self):
        self.populate()
        with sqlite3.connect(self.db) as connection:
            connection.execute("DELETE FROM curated_minute_bars WHERE symbol='S0' AND bar_time=?",
                               ((self.interval.start + timedelta(minutes=5)).isoformat(),))
        result = self.produce()
        self.assertEqual(result.report["status"], "invalid_evidence")
        self.assertGreater(result.report["invalid_mark_count"], 0)
        self.assertIsNone(result.report["source_acceptance"])

    def test_minimum_sample_does_not_issue_proof_before_fixed_end(self):
        self.populate()
        result = self.produce(now=self.interval.end - timedelta(hours=1))
        self.assertEqual(result.report["episodes"], 100)
        self.assertEqual(result.report["status"], "collecting_future_sample")
        self.assertIn("fixed_interval_not_closed", result.report["blocking_reasons"])
        self.assertIsNone(result.report["source_acceptance"])

    def test_no_approval_hash_remains_fail_closed(self):
        self.populate()
        result = self.produce(approved=False)
        self.assertEqual(result.report["status"], "waiting_explicit_activation")
        self.assertIsNone(result.report["source_acceptance"])

    def test_wrong_approval_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "approval"):
            self.service.produce_interval_evidence(
                self.db, acceptance_contract=self.contract, future_interval=self.interval,
                approved_contract_hash="0" * 64, generated_at=self.interval.end,
            )

    def test_contract_body_and_policy_drift_are_rejected(self):
        for target in ("contract", "evaluation_policy"):
            record = json.loads(RECORD.read_text())
            if target == "contract":
                record[target]["future_intervals"][0]["start"] = "2026-10-13T09:15:00+09:00"
            else:
                record[target]["threshold"] = 0.54
            path = Path(self.tmp.name) / "bad-contract.json"
            path.write_text(json.dumps(record))
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.service.load_post_recovery_contract(path)

    def test_insufficient_sample_after_end_is_observe_more(self):
        _create_db(self.db, event_times=[self.interval.start])
        with sqlite3.connect(self.db) as connection:
            for minute in range(17):
                connection.execute("INSERT OR IGNORE INTO curated_minute_bars VALUES ('005930', ?, 100, 101, 99, 100, 100, 1)",
                                   ((self.interval.start + timedelta(minutes=minute)).isoformat(),))
        result = self.produce()
        self.assertEqual(result.report["status"], "observe_more")
        self.assertIsNone(result.report["source_acceptance"])
        self.assertEqual(result.report["future_interval"], self.interval.to_dict())

    def test_writer_is_separate_immutable_and_idempotent(self):
        result = self.produce(now=self.interval.start - timedelta(days=1))
        report = self.service.build_post_recovery_progress(
            self.db, acceptance_contract=self.contract,
            generated_at=self.interval.start - timedelta(days=1),
        )
        directory = Path(self.tmp.name) / "post-recovery"
        path, written = self.service.write_post_recovery_progress(report, report_root=directory)
        original = path.read_bytes()
        _, written_again = self.service.write_post_recovery_progress(report, report_root=directory)
        self.assertTrue(written)
        self.assertFalse(written_again)
        self.assertEqual(path.read_bytes(), original)
        self.assertIn(self.contract.sha256, str(path))
        self.assertFalse(report["official_evaluation_permitted"])
        self.assertEqual(result.report["status"], "not_started")

    def test_cli_protected_session_never_builds_or_writes(self):
        self.assertIsNotNone(importlib.util.find_spec("scripts.generate_e7_post_recovery_progress"))
        cli = importlib.import_module("scripts.generate_e7_post_recovery_progress")
        settings = SimpleNamespace(timezone="Asia/Seoul", market_calendar=SimpleNamespace(holidays=()))
        with patch("sys.argv", ["generate_e7_post_recovery_progress"]), \
                patch.object(cli, "load_settings", return_value=settings), \
                patch.object(cli, "now_local", return_value=self.interval.start), \
                patch.object(cli, "get_market_session_status", return_value="regular-session"), \
                patch.object(cli, "_runtime_running", return_value=False), \
                patch.object(cli, "build_post_recovery_progress") as build, \
                patch.object(cli, "write_post_recovery_progress") as write, \
                redirect_stdout(StringIO()) as output:
            code = cli.main()
        self.assertEqual(code, 2)
        self.assertFalse(build.called)
        self.assertFalse(write.called)
        self.assertFalse(json.loads(output.getvalue())["database_access_started"])

    def test_end_boundary_rows_are_excluded(self):
        self.populate()
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE serving_decision_ledger SET event_time=? WHERE decision_id='decision-0'",
                               (self.interval.end.isoformat(),))
            connection.execute("UPDATE serving_predictions SET event_time=? WHERE prediction_id='prediction-0'",
                               (self.interval.end.isoformat(),))
        result = self.produce()
        self.assertEqual(result.report["source"]["future_decision_rows"], 99)
        self.assertEqual(result.report["episodes"], 99)
        self.assertEqual(result.report["status"], "observe_more")

    def test_cli_early_trading_day_cannot_freeze_post_close_artifact(self):
        cli = importlib.import_module("scripts.generate_e7_post_recovery_progress")
        settings = SimpleNamespace(timezone="Asia/Seoul", market_calendar=SimpleNamespace(holidays=()))
        path = Path(self.tmp.name) / "report.json"
        path.write_text(json.dumps({"status": "not_started"}))
        with patch("sys.argv", ["generate_e7_post_recovery_progress"]), \
                patch.object(cli, "load_settings", return_value=settings), \
                patch.object(cli, "now_local", return_value=self.interval.start.replace(hour=7)), \
                patch.object(cli, "get_market_session_status", return_value="overnight"), \
                patch.object(cli, "_runtime_running", return_value=False), \
                patch.object(cli, "build_post_recovery_progress", return_value={}) as build, \
                patch.object(cli, "write_post_recovery_progress", return_value=(path, True)), \
                redirect_stdout(StringIO()):
            code = cli.main()
        self.assertEqual(code, 2)
        self.assertFalse(build.called)

    def test_weekend_source_rows_are_not_counted_as_valid_days(self):
        self.populate()
        saturday = self.interval.start + timedelta(days=5)
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE serving_decision_ledger SET event_time=? WHERE decision_id='decision-0'",
                               (saturday.isoformat(),))
            connection.execute("UPDATE serving_predictions SET event_time=? WHERE prediction_id='prediction-0'",
                               (saturday.isoformat(),))
        result = self.produce()
        self.assertIn("non_trading_day_source_rows", result.report["blocking_reasons"])
        self.assertEqual(result.report["future_trading_days"], 10)
        self.assertIsNone(result.report["source_acceptance"])

    def test_failed_report_cache_cannot_be_edited_and_reused(self):
        payload = self.service.build_post_recovery_progress(
            self.db, acceptance_contract=self.contract,
            generated_at=self.interval.start - timedelta(days=1),
        )
        root = Path(self.tmp.name) / "post-recovery"
        path, _ = self.service.write_post_recovery_progress(payload, report_root=root)
        stored = json.loads(path.read_text())
        stored["status"] = "ready_for_official_evaluation"
        path.write_text(json.dumps(stored))
        with self.assertRaisesRegex(ValueError, "drift"):
            self.service.write_post_recovery_progress(payload, report_root=root)

    def test_cross_day_price_fallback_cannot_silently_shrink_population(self):
        self.populate()
        with sqlite3.connect(self.db) as connection:
            connection.execute("DELETE FROM curated_minute_bars WHERE symbol='S0' AND bar_time>=? AND bar_time<?",
                               (self.interval.start.isoformat(),
                                (self.interval.start + timedelta(days=1)).replace(hour=0, minute=0).isoformat()))
        result = self.produce()
        self.assertIn("cross_day_bar", result.report["blocking_reasons"])
        self.assertEqual(result.report["status"], "invalid_evidence")
        self.assertIsNone(result.report["source_acceptance"])

    def test_bad_price_outside_exact_interval_never_enters_price_loader(self):
        self.populate()
        with sqlite3.connect(self.db) as connection:
            connection.execute("INSERT INTO curated_minute_bars VALUES ('S0', ?, 'bad-price', 101, 99, 100, 100, 1)",
                               (self.interval.end.isoformat(),))
        try:
            result = self.produce()
        except ValueError:
            self.fail("outside-interval price entered the loader")
        self.assertEqual(result.report["status"], "ready_for_official_evaluation")

    def test_new_failure_is_preserved_beside_immutable_normal_report(self):
        self.populate()
        now = self.interval.end + timedelta(hours=1)
        root = Path(self.tmp.name) / "post-recovery"
        first = self.service.build_post_recovery_progress(
            self.db, acceptance_contract=self.contract, generated_at=now)
        first_path, _ = self.service.write_post_recovery_progress(first, report_root=root)
        original = first_path.read_bytes()
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE serving_predictions SET probability_up=0.61 WHERE prediction_id='prediction-0'")
        second = self.service.build_post_recovery_progress(
            self.db, acceptance_contract=self.contract, generated_at=now + timedelta(seconds=1))
        path, written = self.service.write_post_recovery_progress(second, report_root=root)
        self.assertEqual(second["status"], "invalid_evidence")
        self.assertTrue(written)
        self.assertNotEqual(path, first_path)
        self.assertEqual(json.loads(path.read_text())["status"], "invalid_evidence")
        self.assertEqual(first_path.read_bytes(), original)

    def test_previous_date_artifact_cannot_be_reused_at_new_date_path(self):
        now = self.interval.start - timedelta(days=2)
        root = Path(self.tmp.name) / "post-recovery"
        first = self.service.build_post_recovery_progress(self.db, acceptance_contract=self.contract, generated_at=now)
        path, _ = self.service.write_post_recovery_progress(first, report_root=root)
        second = self.service.build_post_recovery_progress(
            self.db, acceptance_contract=self.contract, generated_at=now + timedelta(days=1))
        next_path = path.parent / f"{(now + timedelta(days=1)).date().isoformat()}.json"
        next_path.write_bytes(path.read_bytes())
        with self.assertRaisesRegex(ValueError, "drift"):
            self.service.write_post_recovery_progress(second, report_root=root)


if __name__ == "__main__":
    unittest.main()
