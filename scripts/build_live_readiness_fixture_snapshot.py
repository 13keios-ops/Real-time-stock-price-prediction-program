#!/usr/bin/env python3
"""Build a conservative live-readiness fixture file from local evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.live_kill_switch import LiveKillSwitch
from app.services.live_readiness_fixture import build_readiness_fixture_snapshot


DEFAULT_PREMARKET_REPORT_PATH = Path("runtime-data/reports/codex/ops/premarket-readiness/latest-premarket-readiness.json")
DEFAULT_TOKEN_REFRESH_CHECK_PATH = Path("runtime-data/reports/live-readiness/token-refresh-check.json")
DEFAULT_WS_RECOVERY_CHECK_PATH = Path("runtime-data/reports/live-readiness/ws-recovery-check.json")
DEFAULT_ACCOUNT_SNAPSHOT_CHECK_PATH = Path("runtime-data/reports/live-readiness/account-snapshot-check.json")
DEFAULT_MARKET_STATUS_CHECK_PATH = Path("runtime-data/reports/live-readiness/market-status-check.json")
DEFAULT_SYSTEM_CLOCK_CHECK_PATH = Path("runtime-data/reports/live-readiness/system-clock-check.json")
DEFAULT_KILL_SWITCH_PATH = Path("runtime-data/reports/live-risk/kill-switch.json")
DEFAULT_OUTPUT_PATH = Path("runtime-data/reports/live-readiness/local-fixture-snapshot.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--premarket-report-path", default=str(DEFAULT_PREMARKET_REPORT_PATH))
    parser.add_argument("--token-refresh-check-path", default=str(DEFAULT_TOKEN_REFRESH_CHECK_PATH))
    parser.add_argument("--ws-recovery-check-path", default=str(DEFAULT_WS_RECOVERY_CHECK_PATH))
    parser.add_argument("--account-snapshot-check-path", default=str(DEFAULT_ACCOUNT_SNAPSHOT_CHECK_PATH))
    parser.add_argument("--market-status-check-path", default=str(DEFAULT_MARKET_STATUS_CHECK_PATH))
    parser.add_argument("--system-clock-check-path", default=str(DEFAULT_SYSTEM_CLOCK_CHECK_PATH))
    parser.add_argument("--kill-switch-path", default=str(DEFAULT_KILL_SWITCH_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    premarket_report_path = _resolve_inside_repo(args.premarket_report_path, project_root, "premarket_report_path")
    token_refresh_check_path = _resolve_inside_repo(args.token_refresh_check_path, project_root, "token_refresh_check_path")
    ws_recovery_check_path = _resolve_inside_repo(args.ws_recovery_check_path, project_root, "ws_recovery_check_path")
    account_snapshot_check_path = _resolve_inside_repo(args.account_snapshot_check_path, project_root, "account_snapshot_check_path")
    market_status_check_path = _resolve_inside_repo(args.market_status_check_path, project_root, "market_status_check_path")
    system_clock_check_path = _resolve_inside_repo(args.system_clock_check_path, project_root, "system_clock_check_path")
    kill_switch_path = _resolve_inside_repo(args.kill_switch_path, project_root, "kill_switch_path")
    output_path = _resolve_inside_repo(args.output_path, project_root, "output_path")

    premarket_report = _load_json(premarket_report_path)
    token_refresh_check = _load_json(token_refresh_check_path)
    ws_recovery_check = _load_json(ws_recovery_check_path)
    account_snapshot_check = _load_json(account_snapshot_check_path)
    market_status_check = _load_json(market_status_check_path)
    system_clock_check = _load_json(system_clock_check_path)
    kill_switch_state = LiveKillSwitch(kill_switch_path).read_state()
    fixture = build_readiness_fixture_snapshot(
        premarket_report=premarket_report,
        token_refresh_check=token_refresh_check,
        ws_recovery_check=ws_recovery_check,
        account_snapshot_check=account_snapshot_check,
        market_status_check=market_status_check,
        system_clock_check=system_clock_check,
        kill_switch_state=kill_switch_state,
    )
    fixture["_meta"]["paths"] = {
        "premarket_report_path": _display_path(premarket_report_path, project_root),
        "token_refresh_check_path": _display_path(token_refresh_check_path, project_root),
        "ws_recovery_check_path": _display_path(ws_recovery_check_path, project_root),
        "account_snapshot_check_path": _display_path(account_snapshot_check_path, project_root),
        "market_status_check_path": _display_path(market_status_check_path, project_root),
        "system_clock_check_path": _display_path(system_clock_check_path, project_root),
        "kill_switch_path": _display_path(kill_switch_path, project_root),
        "output_path": _display_path(output_path, project_root),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


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
