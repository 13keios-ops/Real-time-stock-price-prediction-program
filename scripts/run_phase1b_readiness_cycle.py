#!/usr/bin/env python3
"""Run the complete off-session Phase 1b read-only readiness sequence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.services.ws_recovery_evidence import build_ws_recovery_check_from_data_quality
from app.utils.time import get_market_session_status, now_local


DEFAULT_PREFLIGHT_OUTPUT_PATH = Path(
    "runtime-data/reports/live-readiness/phase1b/latest-cycle-preflight.json"
)
DEFAULT_EXECUTE_OUTPUT_PATH = Path(
    "runtime-data/reports/live-readiness/phase1b/latest-cycle-execute.json"
)
_PROTECTED_SESSIONS = frozenset({"pre-open", "regular-session"})
Runner = Callable[..., subprocess.CompletedProcess[str]]


class CycleStepError(RuntimeError):
    def __init__(self, step: str, reason: str, *, returncode: int | None = None) -> None:
        super().__init__(f"{step}: {reason}")
        self.step = step
        self.reason = reason
        self.returncode = returncode


def run_phase1b_readiness_cycle(
    *,
    project_root: Path,
    output_path: Path,
    execute: bool,
    refresh_dashboard: bool,
    session_status: str,
    runner: Runner = subprocess.run,
    python_executable: str = sys.executable,
) -> dict[str, Any]:
    """Run fresh local evidence, bounded observation, and Phase 1b readiness."""

    root = project_root.expanduser().resolve()
    output = _resolve_inside_repo(output_path, root, "output_path")
    if refresh_dashboard and not execute:
        raise ValueError("refresh_dashboard requires execute=True")
    session = str(session_status or "unknown").strip().lower()
    generated_at = datetime.now().astimezone().isoformat()
    if session in _PROTECTED_SESSIONS:
        payload = _summary_payload(
            status="blocked",
            passed=False,
            generated_at=generated_at,
            session_status=session,
            execute=execute,
            refresh_dashboard=refresh_dashboard,
            steps=[],
            blocking_reasons=["protected_market_session"],
            non_blocking_reasons=[],
        )
        _write_json_atomic(output, payload)
        return payload

    scripts = root / "scripts"
    phase_dir = root / "runtime-data" / "reports" / "live-readiness" / "phase1b"
    premarket_path = (
        root
        / "runtime-data"
        / "reports"
        / "codex"
        / "ops"
        / "premarket-readiness"
        / "latest-premarket-readiness.json"
    )
    ws_path = root / "runtime-data" / "reports" / "live-readiness" / "ws-recovery-check.json"
    data_quality_path = root / "runtime-data" / "reports" / "data-quality" / "latest-kis-live-data-quality.json"
    fixture_path = root / "runtime-data" / "reports" / "live-readiness" / "local-fixture-snapshot.json"
    steps: list[dict[str, Any]] = []
    try:
        premarket = _run_json_step(
            "premarket_readiness",
            [
                "bash",
                str(scripts / "run_codex_ops_job.sh"),
                "--job-type",
                "premarket-readiness",
                "--report-path",
                str(premarket_path),
            ],
            root=root,
            runner=runner,
        )
        _require_output_file(premarket_path, "premarket_readiness")
        steps.append(_step_summary("premarket_readiness", premarket))

        ws_recovery = build_ws_recovery_check_from_data_quality(
            _load_json_object(data_quality_path),
            evaluated_at=datetime.fromisoformat(generated_at),
            source_report_path=str(data_quality_path.relative_to(root)),
        )
        if ws_recovery is None:
            ws_recovery = _run_json_step(
                "ws_recovery",
                ["bash", str(scripts / "probe_kis_ws_recovery.sh"), "--output-path", str(ws_path)],
                root=root,
                runner=runner,
            )
        else:
            _write_json_atomic(ws_path, ws_recovery)
        _require_output_file(ws_path, "ws_recovery")
        steps.append(_step_summary("ws_recovery", ws_recovery))

        observation_command = [
            "bash",
            str(scripts / "run_phase1b_readonly_observation.sh"),
            "--output-dir",
            str(phase_dir),
        ]
        if execute:
            observation_command.append("--execute")
        observation = _run_json_step(
            "phase1b_observation",
            observation_command,
            root=root,
            runner=runner,
        )
        observation_path = _resolve_report_path(
            observation.get("report_path"),
            root,
            "phase1b_observation",
        )
        _require_output_file(observation_path, "phase1b_observation")
        steps.append(_step_summary("phase1b_observation", observation))
        if execute and bool(observation.get("execution_started", False)):
            readiness_path = phase_dir / "latest-readiness.json"
        elif execute:
            readiness_path = phase_dir / "latest-readiness-attempt.json"
        else:
            readiness_path = phase_dir / "latest-readiness-preflight.json"

        fixture = _run_json_step(
            "fixture_snapshot",
            [
                "bash",
                str(scripts / "build_live_readiness_fixture_snapshot.sh"),
                "--premarket-report-path",
                str(premarket_path),
                "--ws-recovery-check-path",
                str(ws_path),
                "--output-path",
                str(fixture_path),
            ],
            root=root,
            runner=runner,
        )
        _require_output_file(fixture_path, "fixture_snapshot")
        steps.append(_step_summary("fixture_snapshot", fixture))

        readiness = _run_json_step(
            "phase1b_readiness",
            [
                "bash",
                str(scripts / "run_live_readiness_dry_run.sh"),
                "--phase",
                "phase1b_live_readonly",
                "--premarket-report-path",
                str(premarket_path),
                "--fixture-path",
                str(fixture_path),
                "--phase1b-observation-path",
                str(observation_path),
                "--report-path",
                str(readiness_path),
            ],
            root=root,
            runner=runner,
        )
        _require_output_file(readiness_path, "phase1b_readiness")
        steps.append(_step_summary("phase1b_readiness", readiness))

        if refresh_dashboard:
            dashboard = _run_json_step(
                "dashboard_refresh",
                [python_executable, "-m", "app", "--build-dashboard"],
                root=root,
                runner=runner,
            )
            steps.append(_step_summary("dashboard_refresh", dashboard))
    except CycleStepError as exc:
        payload = _summary_payload(
            status="failed",
            passed=False,
            generated_at=generated_at,
            session_status=session,
            execute=execute,
            refresh_dashboard=refresh_dashboard,
            steps=steps,
            blocking_reasons=[f"{exc.step}_failed"],
            non_blocking_reasons=[],
        )
        payload["failed_step"] = exc.step
        payload["failure_reason"] = exc.reason
        payload["returncode"] = exc.returncode
        _write_json_atomic(output, payload)
        return payload

    readiness_run = readiness.get("readiness_run")
    readiness_record = readiness_run if isinstance(readiness_run, dict) else {}
    observation_safety_value = observation.get("safety")
    observation_safety = observation_safety_value if isinstance(observation_safety_value, dict) else {}
    payload = _summary_payload(
        status=str(readiness.get("status") or "blocked"),
        passed=bool(readiness_record.get("passed", False)),
        generated_at=generated_at,
        session_status=session,
        execute=execute,
        refresh_dashboard=refresh_dashboard,
        steps=steps,
        blocking_reasons=list(readiness.get("blocking_reasons") or []),
        non_blocking_reasons=list(readiness.get("non_blocking_reasons") or []),
    )
    payload.update(
        {
            "observation_execution_started": bool(observation.get("execution_started", False)),
            "observation_network_calls_executed": observation.get("network_calls_executed"),
            "observation_report_path": str(observation_path),
            "readiness_report_path": str(readiness_path),
            "fixture_path": str(fixture_path),
            "premarket_report_path": str(premarket_path),
            "ws_recovery_check_path": str(ws_path),
            "safety": {
                "order_method_calls": observation_safety.get("order_method_calls"),
                "raw_response_included": observation_safety.get("raw_response_included"),
                "account_identifier_included": observation_safety.get("account_identifier_included"),
                "credential_values_included": observation_safety.get("credential_values_included"),
            },
        }
    )
    _write_json_atomic(output, payload)
    return payload


def _run_json_step(
    step: str,
    command: Sequence[str],
    *,
    root: Path,
    runner: Runner,
) -> dict[str, Any]:
    try:
        result = runner(
            list(command),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise CycleStepError(step, "command_failed", returncode=exc.returncode) from exc
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CycleStepError(step, "invalid_json_output") from exc
    if not isinstance(payload, dict):
        raise CycleStepError(step, "json_output_not_object")
    return payload


def _step_summary(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("status") or "ok")
    return {
        "name": name,
        "status": status,
        "passed": bool(payload.get("passed", status == "ok")),
    }


def _summary_payload(
    *,
    status: str,
    passed: bool,
    generated_at: str,
    session_status: str,
    execute: bool,
    refresh_dashboard: bool,
    steps: list[dict[str, Any]],
    blocking_reasons: list[str],
    non_blocking_reasons: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "job_type": "phase1b-readiness-cycle",
        "status": status,
        "passed": passed,
        "generated_at": generated_at,
        "phase": "phase1b_live_readonly",
        "market_session_status": session_status,
        "execution_requested": execute,
        "execution_mode": "bounded-live-readonly" if execute else "network-free-preflight",
        "dashboard_refresh_requested": refresh_dashboard,
        "steps": steps,
        "blocking_reasons": blocking_reasons,
        "non_blocking_reasons": non_blocking_reasons,
    }


def _resolve_report_path(value: Any, root: Path, step: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise CycleStepError(step, "report_path_missing")
    try:
        return _resolve_inside_repo(Path(value), root, "report_path")
    except SystemExit as exc:
        raise CycleStepError(step, "report_path_outside_repository") from exc


def _resolve_inside_repo(value: Path, root: Path, label: str) -> Path:
    path = value.expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"{label} must stay inside repository root: {resolved}") from exc
    return resolved


def _require_output_file(path: Path, step: str) -> None:
    if not path.is_file():
        raise CycleStepError(step, "expected_output_file_missing")


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--output-path")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run the bounded live read-only observation. Default remains network-free.",
    )
    parser.add_argument(
        "--refresh-dashboard",
        action="store_true",
        help="Refresh the dashboard after an explicit bounded observation.",
    )
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    if args.refresh_dashboard and not args.execute:
        parser.error("--refresh-dashboard requires --execute")
    project_root = Path(args.project_root).expanduser().resolve()
    default_output = DEFAULT_EXECUTE_OUTPUT_PATH if args.execute else DEFAULT_PREFLIGHT_OUTPUT_PATH
    output_path = _resolve_inside_repo(
        Path(args.output_path) if args.output_path else default_output,
        project_root,
        "output_path",
    )
    settings = load_settings(project_root=project_root)
    session_status = get_market_session_status(
        settings.market_calendar,
        now_local(settings.timezone),
    )
    payload = run_phase1b_readiness_cycle(
        project_root=project_root,
        output_path=output_path,
        execute=args.execute,
        refresh_dashboard=args.refresh_dashboard,
        session_status=session_status,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_blocked and not payload["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
