import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.live_phase_readiness import (
    build_fault_injection_dry_run_report,
    build_system_clock_check_from_http_date_headers,
    create_phase_approval,
    create_readiness_run,
    create_readiness_run_from_premarket_report,
)
from app.storage.sqlite_store import SQLiteRuntimeStore


class LivePhaseReadinessTests(unittest.TestCase):
    def _now(self) -> datetime:
        return datetime(2026, 5, 15, 9, 0, tzinfo=timezone.utc)

    def _store(self) -> SQLiteRuntimeStore:
        root = Path(__file__).resolve().parents[1]
        return SQLiteRuntimeStore(root / ".tmp-tests" / "live-phase-readiness" / str(uuid.uuid4()) / "dev.db")

    def test_phase_approval_hash_is_stable_and_active_approval_can_be_fetched(self) -> None:
        now = self._now()
        approval = create_phase_approval(
            phase="phase2_conservative",
            trading_day="2026-05-15",
            approved_at=now,
            approved_by="account_owner",
            expires_at=now + timedelta(hours=7),
            scope="one_symbol_small",
            max_symbols=1,
            max_parent_orders=1,
            max_notional=100_000.0,
            daily_loss_limit_pct=2.0,
            per_symbol_loss_limit_pct=2.0,
            slippage_budget_bps=20.0,
            approval_basis="unit_test",
            operator_decision_ref="docs/cowork-reports/operator-decision.md",
        )
        same_approval = create_phase_approval(
            phase="phase2_conservative",
            trading_day="2026-05-15",
            approved_at=now,
            approved_by="account_owner",
            expires_at=now + timedelta(hours=7),
            scope="one_symbol_small",
            max_symbols=1,
            max_parent_orders=1,
            max_notional=100_000.0,
            daily_loss_limit_pct=2.0,
            per_symbol_loss_limit_pct=2.0,
            slippage_budget_bps=20.0,
            approval_basis="unit_test",
            operator_decision_ref="docs/cowork-reports/operator-decision.md",
        )
        store = self._store()

        store.insert_live_phase_approval(approval)
        active_rows = store.fetch_active_live_phase_approvals(
            phase="phase2_conservative",
            trading_day="2026-05-15",
            as_of=now + timedelta(minutes=1),
        )
        expired_rows = store.fetch_active_live_phase_approvals(
            phase="phase2_conservative",
            trading_day="2026-05-15",
            as_of=now + timedelta(days=1),
        )

        self.assertEqual(approval.approval_hash, same_approval.approval_hash)
        self.assertEqual(active_rows[0]["approval_hash"], approval.approval_hash)
        self.assertEqual(expired_rows, [])

    def test_readiness_run_blocks_when_required_check_fails(self) -> None:
        run = create_readiness_run(
            phase="phase1_readonly",
            trading_day="2026-05-15",
            checked_at=self._now(),
            checks={
                "token_refresh": True,
                "ws_recovery": True,
                "account_snapshot": False,
                "market_status": True,
                "system_clock": True,
                "kill_switch": True,
                "database": True,
                "disk_space": True,
                "dashboard": True,
                "storage_migration_state": True,
            },
            blocking_reasons=["account_snapshot_stale"],
            report_path="runtime-data/reports/live-readiness/latest.json",
        )

        self.assertFalse(run.passed)
        self.assertEqual(run.status, "blocked")
        self.assertIn("readiness_hash", run.checks_json)

    def test_readiness_run_requires_all_check_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "checks missing required keys"):
            create_readiness_run(
                phase="phase1_readonly",
                trading_day="2026-05-15",
                checked_at=self._now(),
                checks={"token_refresh": True},
                report_path="runtime-data/reports/live-readiness/latest.json",
            )

    def test_premarket_report_adapter_is_conservative_without_fault_injection_overrides(self) -> None:
        report = {
            "status": "ok",
            "report_path": "runtime-data/reports/codex/ops/premarket-readiness/latest.json",
            "warnings": [],
            "blockers": [],
            "checks": [
                {"key": "kis_credentials", "status": "ok"},
                {"key": "database", "status": "ok"},
                {"key": "dashboard", "status": "ok"},
                {"key": "storage_migration_state", "status": "ok"},
                {"key": "disk_space", "status": "ok"},
            ],
        }

        run = create_readiness_run_from_premarket_report(
            phase="phase1_readonly",
            trading_day="2026-05-15",
            checked_at=self._now(),
            premarket_report=report,
            report_path="runtime-data/reports/live-readiness/latest.json",
        )

        self.assertFalse(run.passed)
        self.assertTrue(run.token_refresh_ok)
        self.assertTrue(run.database_ok)
        self.assertTrue(run.checks_json["checks"]["disk_space"])
        self.assertTrue(run.checks_json["checks"]["dashboard"])
        self.assertTrue(run.checks_json["checks"]["storage_migration_state"])
        self.assertFalse(run.checks_json["checks"]["system_clock"])
        self.assertFalse(run.ws_recovery_ok)
        self.assertIn("ws_recovery_not_verified_by_premarket_report", run.checks_json["blocking_reasons"])
        self.assertIn("system_clock_not_verified_by_premarket_report", run.checks_json["blocking_reasons"])
        self.assertEqual(run.checks_json["extra_detail"]["source"], "codex_ops_premarket_readiness")

    def test_premarket_report_adapter_allows_explicit_fault_injection_overrides(self) -> None:
        report = {
            "status": "ok",
            "report_path": "runtime-data/reports/codex/ops/premarket-readiness/latest.json",
            "warnings": [],
            "blockers": [],
            "checks": [
                {"key": "kis_credentials", "status": "ok"},
                {"key": "database", "status": "ok"},
                {"key": "dashboard", "status": "ok"},
                {"key": "storage_migration_state", "status": "ok"},
                {"key": "disk_space", "status": "ok"},
            ],
        }

        run = create_readiness_run_from_premarket_report(
            phase="phase1_readonly",
            trading_day="2026-05-15",
            checked_at=self._now(),
            premarket_report=report,
            report_path="runtime-data/reports/live-readiness/latest.json",
            override_checks={
                "ws_recovery": True,
                "account_snapshot": True,
                "market_status": True,
                "system_clock": True,
                "kill_switch": True,
            },
        )

        self.assertTrue(run.passed)
        self.assertEqual(run.status, "ok")
        self.assertEqual(run.checks_json["blocking_reasons"], [])

    def test_premarket_report_adapter_rejects_unknown_override_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown readiness check override"):
            create_readiness_run_from_premarket_report(
                phase="phase1_readonly",
                trading_day="2026-05-15",
                checked_at=self._now(),
                premarket_report={"status": "ok", "checks": []},
                report_path="runtime-data/reports/live-readiness/latest.json",
                override_checks={"latency_probe": True},
            )

    def test_fault_injection_dry_run_report_passes_only_with_explicit_ok_fixtures(self) -> None:
        premarket_report = {
            "status": "ok",
            "report_path": "runtime-data/reports/codex/ops/premarket-readiness/latest.json",
            "warnings": [],
            "blockers": [],
            "checks": [
                {"key": "kis_credentials", "status": "ok"},
                {"key": "database", "status": "ok"},
                {"key": "dashboard", "status": "ok"},
                {"key": "storage_migration_state", "status": "ok"},
                {"key": "disk_space", "status": "ok"},
            ],
        }
        fixture = {
            "token_refresh": {"status": "ok"},
            "ws_recovery": {"status": "passed"},
            "account_snapshot": "healthy",
            "market_status": True,
            "system_clock": "ok",
            "kill_switch": "ready",
            "database": "ok",
            "disk_space": "ok",
            "dashboard": "ok",
            "storage_migration_state": "ok",
        }

        report = build_fault_injection_dry_run_report(
            phase="phase1_readonly",
            trading_day="2026-05-15",
            checked_at=self._now(),
            premarket_report=premarket_report,
            fixture_results=fixture,
            report_path="runtime-data/reports/live-readiness/latest.json",
        )

        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["readiness_run"]["passed"])

    def test_phase2_readiness_rejects_synthetic_ws_recovery_evidence(self) -> None:
        premarket_report = {
            "status": "ok",
            "report_path": "runtime-data/reports/codex/ops/premarket-readiness/latest.json",
            "warnings": [],
            "blockers": [],
            "checks": [],
        }
        fixture = {
            "token_refresh": True,
            "ws_recovery": {
                "status": "ok",
                "passed": True,
                "details": {"evidence_type": "synthetic_fault_injection", "network_called": False},
            },
            "account_snapshot": True,
            "market_status": True,
            "system_clock": True,
            "kill_switch": True,
            "database": True,
            "disk_space": True,
            "dashboard": True,
            "storage_migration_state": True,
        }

        report = build_fault_injection_dry_run_report(
            phase="phase2_conservative",
            trading_day="2026-05-15",
            checked_at=self._now(),
            premarket_report=premarket_report,
            fixture_results=fixture,
            report_path="runtime-data/reports/live-readiness/latest.json",
        )

        ws_check = next(item for item in report["fixture_checks"] if item["key"] == "ws_recovery")
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(ws_check["status"], "invalid_evidence")
        self.assertIn("ws_recovery_real_evidence_required", ws_check["details"]["blocking_reasons"])

    def test_fault_injection_dry_run_blocks_stale_timestamped_evidence(self) -> None:
        premarket_report = {
            "status": "ok",
            "report_path": "runtime-data/reports/codex/ops/premarket-readiness/latest.json",
            "warnings": [],
            "blockers": [],
            "checks": [],
        }
        fixture = {
            "account_snapshot": {
                "status": "ok",
                "passed": True,
                "details": {"checked_at": (self._now() - timedelta(hours=2)).isoformat()},
            },
            "ws_recovery": True,
            "token_refresh": True,
            "market_status": True,
            "system_clock": True,
            "kill_switch": True,
            "database": True,
            "disk_space": True,
            "dashboard": True,
            "storage_migration_state": True,
        }

        report = build_fault_injection_dry_run_report(
            phase="phase1_readonly",
            trading_day="2026-05-15",
            checked_at=self._now(),
            premarket_report=premarket_report,
            fixture_results=fixture,
            report_path="runtime-data/reports/live-readiness/latest.json",
        )

        token_check = next(item for item in report["fixture_checks"] if item["key"] == "account_snapshot")
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(token_check["status"], "stale_evidence")
        self.assertEqual(token_check["details"]["max_evidence_age_seconds"], 3600.0)
        self.assertIn("readiness_evidence_stale", token_check["details"]["blocking_reasons"])

    def test_fault_injection_dry_run_allows_token_refresh_with_longer_key_specific_freshness(self) -> None:
        premarket_report = {
            "status": "ok",
            "report_path": "runtime-data/reports/codex/ops/premarket-readiness/latest.json",
            "warnings": [],
            "blockers": [],
            "checks": [],
        }
        fixture = {
            "token_refresh": {
                "status": "ok",
                "passed": True,
                "details": {"checked_at": (self._now() - timedelta(hours=2)).isoformat()},
            },
            "ws_recovery": True,
            "account_snapshot": True,
            "market_status": True,
            "system_clock": True,
            "kill_switch": True,
            "database": True,
            "disk_space": True,
            "dashboard": True,
            "storage_migration_state": True,
        }

        report = build_fault_injection_dry_run_report(
            phase="phase1_readonly",
            trading_day="2026-05-15",
            checked_at=self._now(),
            premarket_report=premarket_report,
            fixture_results=fixture,
            report_path="runtime-data/reports/live-readiness/latest.json",
        )

        token_check = next(item for item in report["fixture_checks"] if item["key"] == "token_refresh")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(token_check["details"]["max_evidence_age_seconds"], 14400.0)
        self.assertEqual(token_check["details"]["evidence_age_seconds"], 7200.0)

    def test_phase2_readiness_accepts_real_ws_recovery_evidence(self) -> None:
        premarket_report = {
            "status": "ok",
            "report_path": "runtime-data/reports/codex/ops/premarket-readiness/latest.json",
            "warnings": [],
            "blockers": [],
            "checks": [],
        }
        fixture = {
            "token_refresh": True,
            "ws_recovery": {
                "status": "ok",
                "passed": True,
                "details": {"evidence_type": "real_kis_ws_observed", "network_called": True},
            },
            "account_snapshot": True,
            "market_status": True,
            "system_clock": True,
            "kill_switch": True,
            "database": True,
            "disk_space": True,
            "dashboard": True,
            "storage_migration_state": True,
        }

        report = build_fault_injection_dry_run_report(
            phase="phase2_conservative",
            trading_day="2026-05-15",
            checked_at=self._now(),
            premarket_report=premarket_report,
            fixture_results=fixture,
            report_path="runtime-data/reports/live-readiness/latest.json",
        )

        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["override_checks"]["ws_recovery"])
        self.assertEqual(report["blocking_reasons"], [])
        self.assertEqual(set(report["override_checks"]), set(fixture))
        self.assertEqual(report["readiness_run"]["checks_json"]["extra_detail"]["source"], "fault_injection_dry_run")

    def test_fault_injection_dry_run_report_evaluates_system_clock_http_date_fixture(self) -> None:
        premarket_report = {
            "status": "ok",
            "report_path": "runtime-data/reports/codex/ops/premarket-readiness/latest.json",
            "warnings": [],
            "blockers": [],
            "checks": [
                {"key": "kis_credentials", "status": "ok"},
                {"key": "database", "status": "ok"},
                {"key": "dashboard", "status": "ok"},
                {"key": "storage_migration_state", "status": "ok"},
                {"key": "disk_space", "status": "ok"},
            ],
        }
        fixture = {
            "token_refresh": "ok",
            "ws_recovery": "ok",
            "account_snapshot": "ok",
            "market_status": "ok",
            "system_clock": {
                "local_time": "2026-05-20T09:00:01+00:00",
                "http_date": "Wed, 20 May 2026 09:00:00 GMT",
                "max_skew_seconds": 2.0,
            },
            "kill_switch": "ok",
            "database": "ok",
            "disk_space": "ok",
            "dashboard": "ok",
            "storage_migration_state": "ok",
        }

        report = build_fault_injection_dry_run_report(
            phase="phase1_readonly",
            trading_day="2026-05-20",
            checked_at=self._now(),
            premarket_report=premarket_report,
            fixture_results=fixture,
            report_path="runtime-data/reports/live-readiness/latest.json",
        )

        self.assertEqual(report["status"], "ok")
        system_clock = next(item for item in report["fixture_checks"] if item["key"] == "system_clock")
        self.assertEqual(system_clock["status"], "ok")
        self.assertEqual(system_clock["details"]["source"], "kis_rest_http_date")
        self.assertEqual(system_clock["details"]["skew_seconds"], 1.0)

    def test_system_clock_check_from_http_date_headers_can_feed_readiness_without_raw_header(self) -> None:
        check = build_system_clock_check_from_http_date_headers(
            {"date": "Wed, 20 May 2026 09:00:00 GMT", "gt_uid": "fixture-gateway-id"},
            local_time=datetime(2026, 5, 20, 9, 0, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(check["status"], "ok")
        self.assertNotIn("Wed, 20 May 2026", json.dumps(check))
        premarket_report = {"status": "ok", "warnings": [], "blockers": [], "checks": []}
        fixture = {
            "token_refresh": "ok",
            "ws_recovery": "ok",
            "account_snapshot": "ok",
            "market_status": "ok",
            "system_clock": check,
            "kill_switch": "ok",
            "database": "ok",
            "disk_space": "ok",
            "dashboard": "ok",
            "storage_migration_state": "ok",
        }

        report = build_fault_injection_dry_run_report(
            phase="phase1_readonly",
            trading_day="2026-05-20",
            checked_at=self._now(),
            premarket_report=premarket_report,
            fixture_results=fixture,
            report_path="runtime-data/reports/live-readiness/latest.json",
        )

        system_clock = next(item for item in report["fixture_checks"] if item["key"] == "system_clock")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(system_clock["details"]["source"], "kis_rest_http_date")
        self.assertEqual(system_clock["details"]["reference_time"], "2026-05-20T09:00:00+00:00")

    def test_fault_injection_dry_run_report_blocks_system_clock_skew_fixture(self) -> None:
        premarket_report = {"status": "ok", "warnings": [], "blockers": [], "checks": []}
        fixture = {
            "token_refresh": "ok",
            "ws_recovery": "ok",
            "account_snapshot": "ok",
            "market_status": "ok",
            "system_clock": {
                "local_time": "2026-05-20T09:00:03+00:00",
                "http_date": "Wed, 20 May 2026 09:00:00 GMT",
                "max_skew_seconds": 2.0,
            },
            "kill_switch": "ok",
            "database": "ok",
            "disk_space": "ok",
            "dashboard": "ok",
            "storage_migration_state": "ok",
        }

        report = build_fault_injection_dry_run_report(
            phase="phase1_readonly",
            trading_day="2026-05-20",
            checked_at=self._now(),
            premarket_report=premarket_report,
            fixture_results=fixture,
            report_path="runtime-data/reports/live-readiness/latest.json",
        )

        self.assertEqual(report["status"], "blocked")
        self.assertIn("system_clock_fault_dry_run_failed", report["blocking_reasons"])
        system_clock = next(item for item in report["fixture_checks"] if item["key"] == "system_clock")
        self.assertEqual(system_clock["status"], "failed")
        self.assertEqual(system_clock["details"]["blocking_reasons"], ["system_clock_skew_exceeded"])

    def test_fault_injection_dry_run_report_blocks_missing_fixture_checks(self) -> None:
        premarket_report = {
            "status": "ok",
            "report_path": "runtime-data/reports/codex/ops/premarket-readiness/latest.json",
            "warnings": [],
            "blockers": [],
            "checks": [
                {"key": "kis_credentials", "status": "ok"},
                {"key": "database", "status": "ok"},
                {"key": "dashboard", "status": "ok"},
                {"key": "storage_migration_state", "status": "ok"},
                {"key": "disk_space", "status": "ok"},
            ],
        }

        report = build_fault_injection_dry_run_report(
            phase="phase1_readonly",
            trading_day="2026-05-15",
            checked_at=self._now(),
            premarket_report=premarket_report,
            fixture_results={"ws_recovery": "ok"},
            report_path="runtime-data/reports/live-readiness/latest.json",
        )

        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["readiness_run"]["passed"])
        self.assertIn("account_snapshot_not_verified_by_fault_dry_run", report["blocking_reasons"])
        self.assertIn("token_refresh_not_verified_by_fault_dry_run", report["blocking_reasons"])
        self.assertIn("system_clock_not_verified_by_fault_dry_run", report["blocking_reasons"])
        missing = [item for item in report["fixture_checks"] if item["status"] == "not_verified"]
        self.assertGreaterEqual(len(missing), 1)


if __name__ == "__main__":
    unittest.main()
