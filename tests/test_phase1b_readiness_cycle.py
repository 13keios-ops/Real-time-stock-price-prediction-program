from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from scripts.run_phase1b_readiness_cycle import run_phase1b_readiness_cycle


class _FakeRunner:
    def __init__(self, root: Path, *, readiness_passed: bool) -> None:
        self.root = root
        self.readiness_passed = readiness_passed
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(command))
        name = Path(command[1]).name if command[0] == "bash" else "dashboard_refresh"
        if name == "run_codex_ops_job.sh":
            path = Path(command[command.index("--report-path") + 1])
            payload = {"status": "ok", "passed": True}
            self._write(path, payload)
        elif name == "probe_kis_ws_recovery.sh":
            path = Path(command[command.index("--output-path") + 1])
            payload = {"status": "ok", "passed": True}
            self._write(path, payload)
        elif name == "run_phase1b_readonly_observation.sh":
            output_dir = Path(command[command.index("--output-dir") + 1])
            executing = "--execute" in command
            filename = (
                "latest-phase1b-readonly-observation.json"
                if executing
                else "latest-phase1b-readonly-preflight.json"
            )
            path = output_dir / filename
            payload = {
                "status": "ok" if executing else "blocked",
                "passed": executing,
                "execution_started": executing,
                "network_calls_executed": 4 if executing else 0,
                "report_path": str(path),
                "safety": {
                    "order_method_calls": 0,
                    "raw_response_included": False,
                    "account_identifier_included": False,
                    "credential_values_included": False,
                },
            }
            self._write(path, payload)
        elif name == "build_live_readiness_fixture_snapshot.sh":
            path = Path(command[command.index("--output-path") + 1])
            payload = {"status": "ok", "passed": True}
            self._write(path, payload)
        elif name == "run_live_readiness_dry_run.sh":
            path = Path(command[command.index("--report-path") + 1])
            payload = {
                "status": "ok" if self.readiness_passed else "blocked",
                "blocking_reasons": [] if self.readiness_passed else ["token_refresh_not_verified"],
                "non_blocking_reasons": ["market_status_not_verified"],
                "readiness_run": {"passed": self.readiness_passed},
            }
            self._write(path, payload)
        elif name == "dashboard_refresh":
            payload = {"status": "ok", "passed": True}
        else:
            raise AssertionError(f"unexpected command: {command}")
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    @staticmethod
    def _write(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


class Phase1bReadinessCycleTests(unittest.TestCase):
    def _work_dir(self) -> Path:
        path = Path(".tmp-tests") / "phase1b-readiness-cycle" / str(uuid4())
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    def test_default_cycle_is_network_free_and_keeps_readiness_blocked(self) -> None:
        root = self._work_dir()
        runner = _FakeRunner(root, readiness_passed=False)
        output_path = root / "runtime-data" / "reports" / "live-readiness" / "phase1b" / "cycle.json"

        payload = run_phase1b_readiness_cycle(
            project_root=root,
            output_path=output_path,
            execute=False,
            refresh_dashboard=False,
            session_status="weekend",
            runner=runner,
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["execution_mode"], "network-free-preflight")
        self.assertFalse(payload["observation_execution_started"])
        self.assertEqual(payload["observation_network_calls_executed"], 0)
        self.assertEqual(payload["safety"]["order_method_calls"], 0)
        self.assertTrue(payload["readiness_report_path"].endswith("latest-readiness-preflight.json"))
        flattened = [part for call in runner.calls for part in call]
        self.assertNotIn("--execute", flattened)
        self.assertEqual(len(runner.calls), 5)
        self.assertTrue(output_path.is_file())

    def test_execute_cycle_runs_bounded_observation_and_optional_dashboard(self) -> None:
        root = self._work_dir()
        runner = _FakeRunner(root, readiness_passed=True)
        output_path = root / "runtime-data" / "reports" / "live-readiness" / "phase1b" / "cycle.json"

        payload = run_phase1b_readiness_cycle(
            project_root=root,
            output_path=output_path,
            execute=True,
            refresh_dashboard=True,
            session_status="post-close",
            runner=runner,
            python_executable=sys.executable,
        )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["execution_mode"], "bounded-live-readonly")
        self.assertTrue(payload["observation_execution_started"])
        self.assertEqual(payload["observation_network_calls_executed"], 4)
        self.assertTrue(payload["readiness_report_path"].endswith("latest-readiness.json"))
        self.assertIn("--execute", [part for call in runner.calls for part in call])
        self.assertEqual(runner.calls[-1][-2:], ["app", "--build-dashboard"])
        self.assertEqual(len(runner.calls), 6)

    def test_cycle_prefers_real_ws_recovery_from_local_data_quality(self) -> None:
        root = self._work_dir()
        now = datetime.now().astimezone()
        observed_at = now - timedelta(minutes=1)
        trade_date = observed_at.date().isoformat()
        data_quality_path = (
            root
            / "runtime-data"
            / "reports"
            / "data-quality"
            / "latest-kis-live-data-quality.json"
        )
        _FakeRunner._write(
            data_quality_path,
            {
                "latest_trade_date": trade_date,
                "latest_intraday_coverage": {
                    "status": "ok",
                    "trade_date": trade_date,
                    "latest_raw_minute": observed_at.isoformat(),
                },
                "latest_session_observability": {
                    "websocket_reconnects": {
                        "status": "observed_no_storm",
                        "trade_date": trade_date,
                        "count": 1,
                        "storm_count": 0,
                        "connected_count": 2,
                        "subscription_restore_count": 1,
                        "first_frame_after_restore_count": 1,
                        "last_first_frame_after_restore_at": (
                            observed_at - timedelta(minutes=1)
                        ).isoformat(),
                        "reasons": {"timeout": 1},
                    },
                    "raw_minute_gaps": {
                        "trade_date": trade_date,
                        "unexpected_common_gaps_detected": False,
                    },
                },
            },
        )
        runner = _FakeRunner(root, readiness_passed=False)
        output_path = (
            root
            / "runtime-data"
            / "reports"
            / "live-readiness"
            / "phase1b"
            / "cycle.json"
        )

        run_phase1b_readiness_cycle(
            project_root=root,
            output_path=output_path,
            execute=False,
            refresh_dashboard=False,
            session_status="weekend",
            runner=runner,
        )

        command_names = [Path(call[1]).name for call in runner.calls if call[0] == "bash"]
        self.assertNotIn("probe_kis_ws_recovery.sh", command_names)
        ws_path = root / "runtime-data" / "reports" / "live-readiness" / "ws-recovery-check.json"
        ws_check = json.loads(ws_path.read_text(encoding="utf-8"))
        self.assertTrue(ws_check["passed"])
        self.assertEqual(ws_check["details"]["evidence_type"], "real_kis_ws_recovery")
        self.assertEqual(len(runner.calls), 4)

    def test_protected_session_blocks_before_any_step_or_network_call(self) -> None:
        root = self._work_dir()
        runner = _FakeRunner(root, readiness_passed=True)
        output_path = root / "runtime-data" / "reports" / "live-readiness" / "phase1b" / "cycle.json"

        payload = run_phase1b_readiness_cycle(
            project_root=root,
            output_path=output_path,
            execute=True,
            refresh_dashboard=True,
            session_status="regular-session",
            runner=runner,
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["blocking_reasons"], ["protected_market_session"])
        self.assertEqual(runner.calls, [])
        self.assertTrue(output_path.is_file())

    def test_dashboard_refresh_requires_explicit_bounded_execution(self) -> None:
        root = self._work_dir()
        runner = _FakeRunner(root, readiness_passed=True)
        output_path = root / "runtime-data" / "reports" / "live-readiness" / "phase1b" / "cycle.json"

        with self.assertRaisesRegex(ValueError, "requires execute=True"):
            run_phase1b_readiness_cycle(
                project_root=root,
                output_path=output_path,
                execute=False,
                refresh_dashboard=True,
                session_status="weekend",
                runner=runner,
            )

        self.assertEqual(runner.calls, [])
    def test_step_failure_does_not_leak_command_output(self) -> None:
        root = self._work_dir()
        output_path = root / "runtime-data" / "reports" / "live-readiness" / "phase1b" / "cycle.json"

        def failing_runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.CalledProcessError(
                7,
                command,
                output="secret-token-value",
                stderr="secret-account-value",
            )

        payload = run_phase1b_readiness_cycle(
            project_root=root,
            output_path=output_path,
            execute=False,
            refresh_dashboard=False,
            session_status="weekend",
            runner=failing_runner,
        )

        encoded = json.dumps(payload)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["failed_step"], "premarket_readiness")
        self.assertEqual(payload["failure_reason"], "command_failed")
        self.assertNotIn("secret-token-value", encoded)
        self.assertNotIn("secret-account-value", encoded)
        self.assertTrue(output_path.is_file())

if __name__ == "__main__":
    unittest.main()
