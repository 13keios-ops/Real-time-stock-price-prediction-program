import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.recheck_paper_kis_mismatch import (
    DEFAULT_ATTEMPT_OUTPUT_PATH,
    DEFAULT_OUTPUT_PATH,
    build_command_plan,
    choose_default_output_path,
    is_non_trading_day_status,
    is_protected_runtime_status,
    summarize_trace_payload,
)


class PaperKisMismatchRecheckTests(unittest.TestCase):
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
