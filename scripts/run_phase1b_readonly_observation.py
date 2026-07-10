#!/usr/bin/env python3
"""Prepare or execute the bounded Phase 1b KIS read-only observation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.services.phase1b_readonly_observation import (
    build_phase1b_readiness_fixture_overrides,
    build_phase1b_readonly_preflight,
    run_phase1b_readonly_observation,
)
from app.utils.time import get_market_session_status, now_local


DEFAULT_OUTPUT_DIR = Path("runtime-data/reports/live-readiness/phase1b")
ARTIFACT_FILENAMES = {
    "token_refresh_live": "token-refresh-live.json",
    "account_snapshot_paper": "account-snapshot-paper.json",
    "account_snapshot_live": "account-snapshot-live.json",
    "system_clock_live": "system-clock-live.json",
    "account_shape_comparison": "account-shape-paper-live.json",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--symbol", default="005930")
    parser.add_argument("--market-code", default="J")
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument("--max-skew-seconds", type=float, default=2.0)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run bounded live read-only network probes after preflight. Default is network-free preflight.",
    )
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    output_dir = _resolve_inside_repo(args.output_dir, project_root, "output_dir")
    settings = load_settings(project_root=project_root)
    checked_at = datetime.now(timezone.utc)
    session_status = get_market_session_status(
        settings.market_calendar,
        now_local(settings.timezone),
    )

    if args.execute:
        payload = run_phase1b_readonly_observation(
            settings,
            symbol=args.symbol,
            market_code=args.market_code,
            timeout_seconds=args.timeout_seconds,
            max_skew_seconds=args.max_skew_seconds,
            checked_at=checked_at,
            session_status=session_status,
        )
        summary_name = (
            "latest-phase1b-readonly-observation.json"
            if payload.get("execution_started")
            else "latest-phase1b-readonly-attempt.json"
        )
    else:
        preflight = build_phase1b_readonly_preflight(settings)
        preflight["detail"]["market_session_status"] = session_status
        payload = {
            "schema_version": 1,
            "phase": "phase1b_live_readonly",
            "status": preflight["status"],
            "passed": preflight["passed"],
            "checked_at": checked_at.isoformat(),
            "market_session_status": session_status,
            "execution_mode": "network-free-preflight",
            "execution_started": False,
            "network_calls_executed": 0,
            "preflight": preflight,
            "blocking_reasons": list(preflight["blocking_reasons"]),
            "safety": {
                "order_method_calls": 0,
                "raw_response_included": False,
                "account_identifier_included": False,
                "credential_values_included": False,
            },
        }
        summary_name = "latest-phase1b-readonly-preflight.json"

    payload["readiness_fixture_overrides"] = build_phase1b_readiness_fixture_overrides(payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths: dict[str, str] = {}
    for key, artifact in payload.get("artifacts", {}).items():
        filename = ARTIFACT_FILENAMES.get(key)
        if filename is None:
            continue
        artifact_path = output_dir / filename
        _write_json(artifact_path, artifact)
        artifact_paths[key] = _display_path(artifact_path, project_root)
    if artifact_paths:
        payload["artifact_paths"] = artifact_paths
    summary_path = output_dir / summary_name
    payload["report_path"] = _display_path(summary_path, project_root)
    _write_json(summary_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_blocked and not payload["passed"]:
        return 1
    return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_inside_repo(value: str, repo_root: Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise SystemExit(f"{label} must stay inside repository root: {resolved}") from exc
    return resolved


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
