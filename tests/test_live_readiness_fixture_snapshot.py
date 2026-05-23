import json
import subprocess
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.live_kill_switch import LiveKillSwitch
from app.services.live_readiness_fixture import build_readiness_fixture_snapshot


class LiveReadinessFixtureSnapshotTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _work_dir(self) -> Path:
        return self._root() / ".tmp-tests" / "live-readiness-fixture-snapshot" / str(uuid.uuid4())

    def _write_json(self, path: Path, payload: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _premarket_report(self) -> dict:
        return {
            "status": "ok",
            "checks": [
                {"key": "database", "status": "ok", "details": {"journal_mode": "wal"}},
                {"key": "disk_space", "status": "ok", "details": {"free_bytes": 100}},
                {"key": "dashboard", "status": "ok", "details": {"running": True}},
                {"key": "storage_migration_state", "status": "ok", "details": {"apply": False}},
                {"key": "kis_credentials", "status": "ok"},
            ],
        }

    def test_snapshot_includes_only_locally_evidenced_checks(self) -> None:
        now = datetime.now(timezone.utc)
        work_dir = self._work_dir()
        state = LiveKillSwitch(work_dir / "kill-switch.json").write_state(
            enabled=False,
            reason="unit test off",
            actor="test",
            now=now,
            stale_after=now + timedelta(hours=1),
        )
        system_clock_check = {
            "key": "system_clock",
            "status": "ok",
            "passed": True,
            "summary": "system clock evaluated from HTTP Date header",
            "details": {"skew_seconds": 0.5, "source": "kis_rest_http_date"},
        }
        token_refresh_check = {
            "key": "token_refresh",
            "status": "ok",
            "passed": True,
            "summary": "KIS token refresh succeeded",
            "details": {"mode": "paper", "seconds_to_expiry": 3600.0},
        }
        ws_recovery_check = {
            "key": "ws_recovery",
            "status": "ok",
            "passed": True,
            "summary": "synthetic WebSocket reconnect recovery check passed",
            "details": {"evidence_type": "synthetic_fault_injection", "network_called": False},
        }
        account_snapshot_check = {
            "key": "account_snapshot",
            "status": "ok",
            "passed": True,
            "summary": "KIS account snapshot refreshed",
            "details": {"mode": "paper", "position_row_count": 0, "summary_row_count": 1},
        }
        market_status_check = {
            "key": "market_status",
            "status": "ok",
            "passed": True,
            "summary": "market status snapshot allows requested symbols",
            "details": {"source": "manual_snapshot", "symbol_count": 1, "blocked_symbols": {}},
        }

        fixture = build_readiness_fixture_snapshot(
            premarket_report=self._premarket_report(),
            token_refresh_check=token_refresh_check,
            ws_recovery_check=ws_recovery_check,
            account_snapshot_check=account_snapshot_check,
            market_status_check=market_status_check,
            system_clock_check=system_clock_check,
            kill_switch_state=state,
        )

        self.assertTrue(fixture["token_refresh"]["passed"])
        self.assertTrue(fixture["ws_recovery"]["passed"])
        self.assertTrue(fixture["account_snapshot"]["passed"])
        self.assertTrue(fixture["market_status"]["passed"])
        self.assertTrue(fixture["database"]["passed"])
        self.assertTrue(fixture["disk_space"]["passed"])
        self.assertTrue(fixture["dashboard"]["passed"])
        self.assertTrue(fixture["storage_migration_state"]["passed"])
        self.assertTrue(fixture["system_clock"]["passed"])
        self.assertTrue(fixture["kill_switch"]["passed"])

    def test_snapshot_marks_missing_kill_switch_as_failed(self) -> None:
        state = LiveKillSwitch(self._work_dir() / "missing-kill-switch.json").read_state()

        fixture = build_readiness_fixture_snapshot(kill_switch_state=state)

        self.assertEqual(fixture["kill_switch"]["status"], "failed")
        self.assertFalse(fixture["kill_switch"]["passed"])
        self.assertEqual(fixture["kill_switch"]["details"]["state_status"], "missing")

    def test_script_output_feeds_live_readiness_dry_run(self) -> None:
        root = self._root()
        work_dir = self._work_dir()
        premarket_path = self._write_json(work_dir / "premarket.json", self._premarket_report())
        system_clock_path = self._write_json(
            work_dir / "system-clock.json",
            {
                "key": "system_clock",
                "status": "ok",
                "passed": True,
                "summary": "system clock evaluated from HTTP Date header",
                "details": {"skew_seconds": 0.5, "source": "kis_rest_http_date"},
            },
        )
        token_refresh_path = self._write_json(
            work_dir / "token-refresh.json",
            {
                "key": "token_refresh",
                "status": "ok",
                "passed": True,
                "summary": "KIS token refresh succeeded",
                "details": {"mode": "paper", "seconds_to_expiry": 3600.0},
            },
        )
        ws_recovery_path = self._write_json(
            work_dir / "ws-recovery.json",
            {
                "key": "ws_recovery",
                "status": "ok",
                "passed": True,
                "summary": "synthetic WebSocket reconnect recovery check passed",
                "details": {"evidence_type": "synthetic_fault_injection", "network_called": False},
            },
        )
        account_snapshot_path = self._write_json(
            work_dir / "account-snapshot.json",
            {
                "key": "account_snapshot",
                "status": "ok",
                "passed": True,
                "summary": "KIS account snapshot refreshed",
                "details": {"mode": "paper", "position_row_count": 0, "summary_row_count": 1},
            },
        )
        market_status_path = self._write_json(
            work_dir / "market-status.json",
            {
                "key": "market_status",
                "status": "ok",
                "passed": True,
                "summary": "market status snapshot allows requested symbols",
                "details": {"source": "manual_snapshot", "symbol_count": 1, "blocked_symbols": {}},
            },
        )
        now = datetime.now(timezone.utc)
        kill_switch_path = work_dir / "kill-switch.json"
        LiveKillSwitch(kill_switch_path).write_state(
            enabled=False,
            reason="unit test off",
            actor="test",
            now=now,
            stale_after=now + timedelta(hours=1),
        )
        fixture_path = work_dir / "fixture.json"

        build_result = subprocess.run(
            [
                "bash",
                "scripts/build_live_readiness_fixture_snapshot.sh",
                "--premarket-report-path",
                str(premarket_path),
                "--token-refresh-check-path",
                str(token_refresh_path),
                "--ws-recovery-check-path",
                str(ws_recovery_path),
                "--account-snapshot-check-path",
                str(account_snapshot_path),
                "--market-status-check-path",
                str(market_status_path),
                "--system-clock-check-path",
                str(system_clock_path),
                "--kill-switch-path",
                str(kill_switch_path),
                "--output-path",
                str(fixture_path),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        fixture = json.loads(build_result.stdout)
        self.assertTrue(fixture["system_clock"]["passed"])

        readiness_result = subprocess.run(
            [
                "bash",
                "scripts/run_live_readiness_dry_run.sh",
                "--premarket-report-path",
                str(premarket_path),
                "--fixture-path",
                str(fixture_path),
                "--report-path",
                str(work_dir / "readiness.json"),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        readiness = json.loads(readiness_result.stdout)

        self.assertEqual(readiness["status"], "ok")
        self.assertTrue(readiness["override_checks"]["system_clock"])
        self.assertTrue(readiness["override_checks"]["kill_switch"])
        self.assertTrue(readiness["override_checks"]["token_refresh"])
        self.assertTrue(readiness["override_checks"]["ws_recovery"])
        self.assertTrue(readiness["override_checks"]["account_snapshot"])
        self.assertTrue(readiness["override_checks"]["market_status"])
        self.assertTrue(readiness["override_checks"]["database"])
        self.assertEqual(readiness["blocking_reasons"], [])


if __name__ == "__main__":
    unittest.main()
