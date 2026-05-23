from pathlib import Path
import unittest

from app.services.codex_ops import (
    ACTION_APPLY_PATCH_TO_ROOT,
    ACTION_CHANGE_GATE_THRESHOLD,
    ACTION_CHANGE_LIVE_FLAG,
    ACTION_CREATE_COWORK_REPORT,
    ACTION_CREATE_PATCH_DRAFT,
    ACTION_READ_STATUS,
    ACTION_RESTART_LIVE_RUNTIME,
    ACTION_RUN_APP_READONLY_REPORT,
    ACTION_RUN_FULL_TEST,
    ACTION_RUN_ISOLATED_UNIT_TEST,
    ACTION_RUN_SNAPSHOT_RESEARCH,
    ACTION_RUN_STORAGE_MIGRATION_APPLY,
    ACTION_RUN_STORAGE_MIGRATION_PLAN,
    ACTION_SEND_LIVE_ORDER,
    ACTION_WRITE_REPORT,
    CODEX_OPS_PATCH_DRAFT_ROOT,
    PREMARKET_READINESS_CHECK_KEYS,
    JOB_COWORK_HANDOFF,
    JOB_INTRADAY_INCIDENT_TRIAGE,
    JOB_POSTCLOSE_RESEARCH,
    JOB_PREMARKET_READINESS,
    CodexOpsContext,
    backup_policy_for_job,
    build_premarket_readiness_report,
    evaluate_action,
    get_manifest,
    is_cleanup_protected_path,
    is_protected_session,
    report_root_for_job,
)


class CodexOpsManifestTests(unittest.TestCase):
    def test_protected_session_detects_market_state_and_runtime_flags(self) -> None:
        self.assertTrue(is_protected_session(CodexOpsContext(session_status="regular-session")))
        self.assertTrue(is_protected_session(CodexOpsContext(session_status="post-close", live_runtime_should_run=True)))
        self.assertTrue(is_protected_session(CodexOpsContext(session_status="post-close", live_runtime_running=True)))
        self.assertFalse(is_protected_session(CodexOpsContext(session_status="overnight")))
        self.assertFalse(is_protected_session(CodexOpsContext(session_status="post-close")))

    def test_premarket_readiness_allows_reports_but_blocks_patch_and_apply(self) -> None:
        context = CodexOpsContext(session_status="pre-open")

        report_decision = evaluate_action(
            JOB_PREMARKET_READINESS,
            ACTION_WRITE_REPORT,
            context,
            target_path=report_root_for_job(JOB_PREMARKET_READINESS) / "2026-05-15.json",
        )
        patch_decision = evaluate_action(
            JOB_PREMARKET_READINESS,
            ACTION_CREATE_PATCH_DRAFT,
            context,
            target_path=CODEX_OPS_PATCH_DRAFT_ROOT / "incident.diff",
        )
        apply_decision = evaluate_action(JOB_PREMARKET_READINESS, ACTION_RUN_STORAGE_MIGRATION_APPLY, context)

        self.assertTrue(report_decision.allowed)
        self.assertFalse(patch_decision.allowed)
        self.assertIn("patch_draft_not_allowed_for_job", patch_decision.blocking_reasons)
        self.assertFalse(apply_decision.allowed)
        self.assertIn("action_requires_operator_approval", apply_decision.blocking_reasons)

    def test_intraday_incident_allows_isolated_draft_but_blocks_root_and_runtime_actions(self) -> None:
        context = CodexOpsContext(session_status="regular-session")

        draft_decision = evaluate_action(
            JOB_INTRADAY_INCIDENT_TRIAGE,
            ACTION_CREATE_PATCH_DRAFT,
            context,
            target_path=CODEX_OPS_PATCH_DRAFT_ROOT / "2026-05-15" / "fix.diff",
        )
        root_patch_decision = evaluate_action(
            JOB_INTRADAY_INCIDENT_TRIAGE,
            ACTION_APPLY_PATCH_TO_ROOT,
            context,
        )
        restart_decision = evaluate_action(JOB_INTRADAY_INCIDENT_TRIAGE, ACTION_RESTART_LIVE_RUNTIME, context)
        app_decision = evaluate_action(JOB_INTRADAY_INCIDENT_TRIAGE, ACTION_RUN_APP_READONLY_REPORT, context)

        self.assertTrue(draft_decision.allowed)
        self.assertFalse(root_patch_decision.allowed)
        self.assertIn("action_requires_operator_approval", root_patch_decision.blocking_reasons)
        self.assertFalse(restart_decision.allowed)
        self.assertIn("action_requires_operator_approval", restart_decision.blocking_reasons)
        self.assertFalse(app_decision.allowed)
        self.assertIn("action_not_allowed_for_job", app_decision.blocking_reasons)

    def test_postclose_research_allows_snapshot_research_and_full_tests_outside_protection(self) -> None:
        context = CodexOpsContext(session_status="post-close")

        self.assertTrue(evaluate_action(JOB_POSTCLOSE_RESEARCH, ACTION_RUN_SNAPSHOT_RESEARCH, context).allowed)
        self.assertTrue(evaluate_action(JOB_POSTCLOSE_RESEARCH, ACTION_RUN_FULL_TEST, context).allowed)
        self.assertTrue(evaluate_action(JOB_POSTCLOSE_RESEARCH, ACTION_RUN_APP_READONLY_REPORT, context).allowed)
        self.assertFalse(evaluate_action(JOB_POSTCLOSE_RESEARCH, ACTION_SEND_LIVE_ORDER, context).allowed)
        self.assertFalse(evaluate_action(JOB_POSTCLOSE_RESEARCH, ACTION_CHANGE_LIVE_FLAG, context).allowed)
        self.assertFalse(evaluate_action(JOB_POSTCLOSE_RESEARCH, ACTION_CHANGE_GATE_THRESHOLD, context).allowed)

    def test_protected_session_blocks_heavy_actions_even_when_job_allows_them_postclose(self) -> None:
        context = CodexOpsContext(session_status="regular-session")

        full_test = evaluate_action(JOB_POSTCLOSE_RESEARCH, ACTION_RUN_FULL_TEST, context)
        snapshot_research = evaluate_action(JOB_POSTCLOSE_RESEARCH, ACTION_RUN_SNAPSHOT_RESEARCH, context)
        isolated_unit = evaluate_action(JOB_POSTCLOSE_RESEARCH, ACTION_RUN_ISOLATED_UNIT_TEST, context)
        migration_plan = evaluate_action(JOB_POSTCLOSE_RESEARCH, ACTION_RUN_STORAGE_MIGRATION_PLAN, context)

        self.assertFalse(full_test.allowed)
        self.assertIn("action_not_allowed_during_protected_session", full_test.blocking_reasons)
        self.assertFalse(snapshot_research.allowed)
        self.assertIn("action_not_allowed_during_protected_session", snapshot_research.blocking_reasons)
        self.assertTrue(isolated_unit.allowed)
        self.assertTrue(migration_plan.allowed)

    def test_report_and_patch_paths_are_constrained(self) -> None:
        context = CodexOpsContext(session_status="post-close")

        bad_report = evaluate_action(
            JOB_PREMARKET_READINESS,
            ACTION_WRITE_REPORT,
            context,
            target_path=Path("runtime-data/reports/codex/ops/other-job/result.json"),
        )
        bad_patch = evaluate_action(
            JOB_INTRADAY_INCIDENT_TRIAGE,
            ACTION_CREATE_PATCH_DRAFT,
            context,
            target_path=Path("app/services/patch.diff"),
        )
        cowork_report = evaluate_action(
            JOB_COWORK_HANDOFF,
            ACTION_CREATE_COWORK_REPORT,
            context,
            target_path=Path("docs/cowork-reports/handoff.md"),
        )

        self.assertIn("report_path_outside_job_root", bad_report.blocking_reasons)
        self.assertIn("patch_draft_path_outside_codex_ops", bad_patch.blocking_reasons)
        self.assertTrue(cowork_report.allowed)

    def test_patch_drafts_are_cleanup_protected_but_excluded_from_backup(self) -> None:
        policy = backup_policy_for_job(JOB_INTRADAY_INCIDENT_TRIAGE)

        self.assertTrue(is_cleanup_protected_path(CODEX_OPS_PATCH_DRAFT_ROOT / "incident.diff"))
        self.assertFalse(is_cleanup_protected_path(Path(".tmp-tests/other/incident.diff")))
        self.assertIn(str(report_root_for_job(JOB_INTRADAY_INCIDENT_TRIAGE)), policy["include"])
        self.assertIn(str(CODEX_OPS_PATCH_DRAFT_ROOT), policy["exclude"])

    def test_all_known_manifests_are_available_and_unknown_job_fails(self) -> None:
        for job_type in (
            JOB_PREMARKET_READINESS,
            JOB_POSTCLOSE_RESEARCH,
            JOB_INTRADAY_INCIDENT_TRIAGE,
            JOB_COWORK_HANDOFF,
        ):
            self.assertEqual(get_manifest(job_type).job_type, job_type)
        with self.assertRaises(ValueError):
            get_manifest("unknown-job")

    def test_unknown_action_is_blocked(self) -> None:
        decision = evaluate_action(
            JOB_PREMARKET_READINESS,
            "unknown-action",
            CodexOpsContext(session_status="post-close"),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("action_unknown", decision.blocking_reasons)
        self.assertIn("action_not_allowed_for_job", decision.blocking_reasons)

    def test_read_status_is_safe_for_all_manifests(self) -> None:
        context = CodexOpsContext(session_status="regular-session")

        for job_type in (
            JOB_PREMARKET_READINESS,
            JOB_POSTCLOSE_RESEARCH,
            JOB_INTRADAY_INCIDENT_TRIAGE,
            JOB_COWORK_HANDOFF,
        ):
            with self.subTest(job_type=job_type):
                self.assertTrue(evaluate_action(job_type, ACTION_READ_STATUS, context).allowed)

    def test_premarket_report_schema_lists_all_required_checks(self) -> None:
        report = build_premarket_readiness_report(
            context=CodexOpsContext(session_status="weekend", live_runtime_should_run=False, live_runtime_running=False),
            live_runtime_status={
                "status": "stopped",
                "env_file_exists": True,
                "credentials_ready_for_quotes": True,
            },
            watchdog_status={"status": "running", "process_running": True, "heartbeat_stale": False},
            dashboard_status={"status": "running", "process_running": True},
            database_smoke={"status": "ok", "quick_check": "ok", "journal_mode": "wal"},
            storage_migration_state={"status": "planned", "apply": False},
            disk_free_bytes=20 * 1024 * 1024 * 1024,
            generated_at="2026-05-16 00:00:00 +0900",
            workspace_root="/repo",
            report_path="/repo/runtime-data/reports/codex/ops/premarket-readiness/latest.json",
        )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual([check["key"] for check in report["checks"]], list(PREMARKET_READINESS_CHECK_KEYS))
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["warnings"], [])

    def test_premarket_report_blocks_when_live_runtime_should_run_but_is_stopped(self) -> None:
        report = build_premarket_readiness_report(
            context=CodexOpsContext(session_status="pre-open", live_runtime_should_run=True, live_runtime_running=False),
            live_runtime_status={
                "status": "stopped",
                "env_file_exists": True,
                "credentials_ready_for_quotes": True,
            },
            watchdog_status={"status": "running", "process_running": True, "heartbeat_stale": False},
            dashboard_status={"status": "running", "process_running": True},
            database_smoke={"status": "ok", "quick_check": "ok", "journal_mode": "wal"},
            storage_migration_state={"status": "ok", "apply": False},
            disk_free_bytes=20 * 1024 * 1024 * 1024,
            generated_at="2026-05-16 00:00:00 +0900",
            workspace_root="/repo",
        )

        self.assertEqual(report["status"], "blocked")
        self.assertIn("live_runtime", report["blockers"])

    def test_premarket_report_warns_on_low_disk_and_missing_storage_state(self) -> None:
        report = build_premarket_readiness_report(
            context=CodexOpsContext(session_status="weekend"),
            live_runtime_status={
                "status": "stopped",
                "env_file_exists": True,
                "credentials_ready_for_quotes": True,
            },
            watchdog_status={"status": "running", "process_running": True, "heartbeat_stale": False},
            dashboard_status={"status": "running", "process_running": True},
            database_smoke={"status": "ok", "quick_check": "ok", "journal_mode": "wal"},
            storage_migration_state={},
            disk_free_bytes=8 * 1024 * 1024 * 1024,
            generated_at="2026-05-16 00:00:00 +0900",
            workspace_root="/repo",
        )

        self.assertEqual(report["status"], "watch")
        self.assertIn("storage_migration_state", report["warnings"])
        self.assertIn("disk_space", report["warnings"])

    def test_premarket_report_blocks_on_database_smoke_failure(self) -> None:
        report = build_premarket_readiness_report(
            context=CodexOpsContext(session_status="weekend"),
            live_runtime_status={
                "status": "stopped",
                "env_file_exists": True,
                "credentials_ready_for_quotes": True,
            },
            watchdog_status={"status": "running", "process_running": True, "heartbeat_stale": False},
            dashboard_status={"status": "running", "process_running": True},
            database_smoke={"status": "blocked", "error": "database is locked"},
            storage_migration_state={"status": "ok", "apply": False},
            disk_free_bytes=20 * 1024 * 1024 * 1024,
            generated_at="2026-05-16 00:00:00 +0900",
            workspace_root="/repo",
        )

        self.assertEqual(report["status"], "blocked")
        self.assertIn("database", report["blockers"])


if __name__ == "__main__":
    unittest.main()
