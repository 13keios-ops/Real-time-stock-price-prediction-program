import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from scripts.recheck_paper_kis_mismatch import (
    DEFAULT_ATTEMPT_OUTPUT_PATH,
    DEFAULT_OUTPUT_PATH,
    build_command_plan,
    choose_default_output_path,
    is_non_trading_day_status,
    is_protected_runtime_status,
    summarize_trace_payload,
    build_remediation_diagnosis,
    main,
)


class PaperKisMismatchRecheckTests(unittest.TestCase):
    def evidence(self):
        account = {"as_of": "2026-09-28T20:25:01+09:00", "market_session_status": "post-close",
                   "comparison": {"status": "aligned", "positions_match": True, "balance_match": True,
                                  "total_asset_match": True, "mismatch_count": 0,
                                  "cash_gap": -1800.0, "total_asset_gap": 8400.0,
                                  "unknown_local_submission_count": 0}}
        account["comparison"]["latest_broker_fetch_time"] = "2026-09-28T20:25:01+09:00"
        broker = {"ok": True, "status": "ok", "order_fill_pagination_complete": True,
                  "synced_at": "2026-09-28T20:25:00+09:00",
                  "confirmed_evidence_required": True, "applied_fill_events": 0, "applied_fill_qty": 0}
        trace = {"generated_at": "2026-09-28T20:25:02+09:00", "symbol_summaries": []}
        return account, broker, trace

    def diagnose(self, account, broker, trace, *, completed=True):
        return build_remediation_diagnosis(account, broker, trace, trade_date="2026-09-28",
                                          sync_completed=completed, trace_completed=True, sync_attempted=True)

    def test_cash_only_mismatch_is_not_reported_as_no_mismatches(self):
        account, broker, trace = self.evidence()
        account["comparison"].update(balance_match=False, cash_gap=-20000.0, status="needs_review")
        result = self.diagnose(account, broker, trace)
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("cash", result["gap_categories"])
        self.assertFalse(result["automatic_account_alignment"])

    def test_tolerated_cash_and_mark_gaps_are_observed_not_aligned_away(self):
        result = self.diagnose(*self.evidence())
        self.assertEqual(result["status"], "aligned_with_tolerated_gaps")
        self.assertEqual(result["accounting_action"], "no_accounting_change")
        self.assertIn("cost_settlement_or_mark_timing_unresolved", result["remaining_investigation"])

    def test_confirmed_missing_fill_is_reported_as_recovery_only_after_reconciliation(self):
        account, broker, trace = self.evidence()
        broker.update(applied_fill_events=1, applied_fill_qty=3)
        result = self.diagnose(account, broker, trace)
        self.assertEqual(result["accounting_action"], "confirmed_fill_sync_applied")
        self.assertEqual(result["applied_fill_qty"], 3)
        account["comparison"].update(positions_match=False, mismatch_count=1, status="needs_review")
        self.assertEqual(self.diagnose(account, broker, trace)["status"], "needs_review")

    def test_failed_query_cannot_use_cached_aligned_account_as_recovery(self):
        account, broker, trace = self.evidence()
        broker.update(applied_fill_events=1, applied_fill_qty=3)
        result = self.diagnose(account, broker, trace, completed=False)
        self.assertEqual(result["status"], "blocked_broker_evidence")
        self.assertEqual(result["accounting_action"], "accounting_change_unverified")
        self.assertIsNone(result["applied_fill_qty"])

    def test_current_network_failure_report_proves_no_fill_was_applied(self):
        account, broker, trace = self.evidence()
        broker.update(ok=False, status="network_error", applied_fill_events=0, applied_fill_qty=0)
        result = self.diagnose(account, broker, trace, completed=False)
        self.assertEqual(result["accounting_action"], "no_accounting_change")
        self.assertEqual(result["status"], "blocked_broker_evidence")

    def test_stale_or_unknown_evidence_cannot_be_declared_aligned(self):
        account, broker, trace = self.evidence()
        account["as_of"] = "2026-09-27T20:25:01+09:00"
        self.assertEqual(self.diagnose(account, broker, trace)["status"], "stale_evidence")
        account["as_of"] = "2026-09-28T20:25:01+09:00"
        account["comparison"]["unknown_local_submission_count"] = 1
        result = self.diagnose(account, broker, trace)
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("unconfirmed_submission", result["gap_categories"])

    def test_existing_eligible_day_runs_only_readonly_trace_and_diagnosis(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root / ".tmp-tests", prefix="recheck-diagnose-") as tmp:
            project = Path(tmp)
            reports = project / "runtime-data/reports/reconciliation"
            reports.mkdir(parents=True)
            today = datetime.now().astimezone().date().isoformat()
            (reports / "latest-paper-account-history.json").write_text(json.dumps({
                "days": [{"trade_date": today, "eligible_for_phase0_gate": True, "matched": False}]}))
            with patch("scripts.recheck_paper_kis_mismatch.load_live_runtime_status",
                       return_value={"current_session_status": "post-close", "process_running": False}):
                with patch("scripts.recheck_paper_kis_mismatch.run_step",
                           return_value={"name": "trace_paper_kis_mismatch", "returncode": 0}) as step:
                    with patch("builtins.print"):
                        main(["--project-root", str(project)])
            self.assertEqual(step.call_count, 1)
            self.assertEqual(step.call_args.args[0], "trace_paper_kis_mismatch")
            payload = json.loads((reports / "latest-paper-kis-mismatch-recheck.json").read_text())
            self.assertEqual(payload["mode"], "diagnose_existing_evidence")
            self.assertTrue(payload["safety"]["broker_calls_skipped"])
            self.assertEqual(len(payload["generated_at"].split(".")[1].split("+")[0]), 6)

    def test_protected_runtime_blocks_preopen_and_running_process(self) -> None:
        self.assertTrue(is_protected_runtime_status({"current_session_status": "pre-open"}))
        self.assertTrue(is_protected_runtime_status({"current_session_status": "regular-session"}))
        self.assertTrue(is_protected_runtime_status({"current_session_status": "weekend", "process_running": True}))
        self.assertFalse(is_protected_runtime_status({"current_session_status": "weekend", "process_running": False}))

    def test_non_trading_day_blocks_weekend_and_holiday(self) -> None:
        self.assertTrue(is_non_trading_day_status({"current_session_status": "weekend"}))
        self.assertTrue(is_non_trading_day_status({"session_status": "holiday"}))
        self.assertFalse(is_non_trading_day_status({"current_session_status": "post-close"}))

    def test_shell_wrapper_preserves_expected_exit_without_false_missing_implementation(self) -> None:
        root = Path(__file__).resolve().parents[1]
        temp_root = root / ".tmp-tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="mismatch-wrapper-", dir=temp_root) as tmp:
            output_path = Path(tmp) / "attempt.json"
            result = subprocess.run(
                [
                    "bash",
                    "scripts/recheck_paper_kis_mismatch.sh",
                    "--dry-run",
                    "--output-path",
                    str(output_path),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertIn(result.returncode, {0, 2})
            self.assertNotIn("No bash implementation registered", result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn(payload["status"], {"dry_run", "blocked"})

    def test_attempts_do_not_use_authoritative_latest_output_by_default(self) -> None:
        self.assertEqual(
            choose_default_output_path(
                dry_run=False,
                protected_blocked=False,
                non_trading_blocked=False,
            ),
            DEFAULT_OUTPUT_PATH,
        )
        for kwargs in (
            {"dry_run": True, "protected_blocked": False, "non_trading_blocked": False},
            {"dry_run": False, "protected_blocked": True, "non_trading_blocked": False},
            {"dry_run": False, "protected_blocked": False, "non_trading_blocked": True},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(
                    choose_default_output_path(**kwargs),
                    DEFAULT_ATTEMPT_OUTPUT_PATH,
                )


    def test_command_plan_is_sync_reconcile_then_trace(self) -> None:
        plan = build_command_plan(Path("/repo"), limit_per_table=12)

        self.assertEqual([name for name, _command in plan], [
            "sync_broker_paper_orders",
            "reconcile_paper_accounts",
            "trace_paper_kis_mismatch",
        ])
        self.assertEqual(plan[-1][1][-2:], ["--limit-per-table", "12"])
        self.assertIn("--broker-sync-confirmed-only", plan[0][1])
        self.assertIn("--require-fresh-broker-account", plan[1][1])

    def test_stale_broker_report_and_failed_trace_are_not_current_evidence(self):
        account, broker, trace = self.evidence()
        broker["synced_at"] = "2026-09-27T20:25:00+09:00"
        self.assertEqual(self.diagnose(account, broker, trace)["status"], "stale_evidence")
        account, broker, trace = self.evidence()
        result = build_remediation_diagnosis(account, broker, trace, trade_date="2026-09-28",
            sync_completed=False, trace_completed=False, sync_attempted=False)
        self.assertEqual(result["status"], "stale_evidence")
        self.assertEqual(result["root_cause_scope_counts"], {})

    def test_diagnosis_does_not_claim_cached_fill_was_applied_now(self):
        account, broker, trace = self.evidence()
        broker.update(applied_fill_events=1, applied_fill_qty=3)
        result = build_remediation_diagnosis(account, broker, trace, trade_date="2026-09-28",
            sync_completed=False, trace_completed=True, sync_attempted=False)
        self.assertEqual(result["accounting_action"], "no_accounting_change")
        self.assertEqual(result["applied_fill_qty"], 0)

    def test_no_submission_observation_is_not_phase0_success(self):
        account, broker, trace = self.evidence()
        account["comparison"].update(status="aligned_waiting_first_submission", cash_gap=0, total_asset_gap=0)
        broker.update(status="no_submissions", order_fill_pagination_complete=None)
        self.assertEqual(self.diagnose(account, broker, trace)["status"], "no_submission_observation")

    def test_new_reconciliation_timestamp_cannot_hide_stale_account_cache(self):
        account, broker, trace = self.evidence()
        account["comparison"]["latest_broker_fetch_time"] = "2026-09-27T20:25:01+09:00"
        self.assertEqual(self.diagnose(account, broker, trace)["status"], "stale_evidence")

    def test_committed_sync_is_reported_even_if_following_reconciliation_fails(self):
        account, broker, trace = self.evidence()
        broker.update(applied_fill_events=1, applied_fill_qty=3)
        result = build_remediation_diagnosis(account, broker, trace, trade_date="2026-09-28",
            sync_attempted=True, sync_completed=True, reconciliation_completed=False, trace_completed=False)
        self.assertEqual(result["accounting_action"], "confirmed_fill_sync_applied")
        self.assertEqual(result["applied_fill_qty"], 3)
        self.assertNotIn(result["status"], {"aligned", "aligned_with_tolerated_gaps"})

    def test_previous_partial_report_in_same_second_is_not_current_recovery(self):
        account, broker, trace = self.evidence()
        broker.update(ok=False, status="accounting_sync_failed", applied_fill_events=1,
                      applied_fill_qty=3, synced_at="2026-09-28T20:25:00.100000+09:00")
        result = build_remediation_diagnosis(account, broker, trace, trade_date="2026-09-28",
            sync_attempted=True, sync_completed=False, trace_completed=False,
            execution_started_at="2026-09-28T20:25:00.900000+09:00")
        self.assertEqual(result["accounting_action"], "accounting_change_unverified")
        self.assertIsNone(result["applied_fill_qty"])

    def test_summarize_trace_payload_counts_root_cause_scopes(self) -> None:
        summary = summarize_trace_payload(
            {
                "assessment": {"status": "needs_review", "summary": "two mismatches"},
                "mismatch_count": 2,
                "broker_sync": {"status": "ok", "open_order_count": 0},
                "symbols": ["035420", "247540"],
                "symbol_summaries": [
                    {
                        "symbol": "035420",
                        "root_cause_scope": "kis_account_snapshot_vs_order_fill_ledger_divergence",
                        "likely_issue": "broker_account_flat_but_order_fill_net_positive",
                    },
                    {
                        "symbol": "247540",
                        "root_cause_scope": "kis_account_snapshot_vs_order_fill_ledger_divergence",
                        "likely_issue": "broker_account_has_residual_qty_not_in_order_fill_net",
                    },
                ],
            }
        )

        self.assertEqual(summary["assessment_status"], "needs_review")
        self.assertEqual(summary["mismatch_count"], 2)
        self.assertEqual(
            summary["root_cause_scope_counts"],
            {"kis_account_snapshot_vs_order_fill_ledger_divergence": 2},
        )
        self.assertEqual(summary["broker_open_order_count"], 0)


if __name__ == "__main__":
    unittest.main()
