"""Build conservative live-readiness fixture snapshots from existing reports."""

from __future__ import annotations

from typing import Any

from app.services.live_kill_switch import LiveKillSwitchState
from app.services.live_phase_readiness import READINESS_OK_STATUSES


PREMARKET_TO_READINESS_KEYS = {
    "database": "database",
    "disk_space": "disk_space",
    "dashboard": "dashboard",
    "storage_migration_state": "storage_migration_state",
}


def build_readiness_fixture_snapshot(
    *,
    premarket_report: dict[str, Any] | None = None,
    token_refresh_check: dict[str, Any] | None = None,
    ws_recovery_check: dict[str, Any] | None = None,
    account_snapshot_check: dict[str, Any] | None = None,
    market_status_check: dict[str, Any] | None = None,
    system_clock_check: dict[str, Any] | None = None,
    kill_switch_state: LiveKillSwitchState | None = None,
    source: str = "local-readiness-fixture-snapshot",
) -> dict[str, Any]:
    """Build fixture checks only for evidence already available locally."""

    fixture: dict[str, Any] = {
        "_meta": {
            "source": source,
            "notes": [
                "Only locally evidenced checks are included.",
                "token_refresh, ws_recovery, account_snapshot, and market_status stay absent unless supplied by separate evidence.",
            ],
        }
    }
    if premarket_report:
        fixture.update(_premarket_checks(premarket_report))
    if token_refresh_check:
        fixture["token_refresh"] = _keyed_check(token_refresh_check, "token_refresh")
    if ws_recovery_check:
        fixture["ws_recovery"] = _keyed_check(ws_recovery_check, "ws_recovery")
    if account_snapshot_check:
        fixture["account_snapshot"] = _keyed_check(account_snapshot_check, "account_snapshot")
    if market_status_check:
        fixture["market_status"] = _keyed_check(market_status_check, "market_status")
    if system_clock_check:
        fixture["system_clock"] = _keyed_check(system_clock_check, "system_clock")
    if kill_switch_state is not None:
        fixture["kill_switch"] = _kill_switch_check(kill_switch_state)
    return fixture


def _premarket_checks(report: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in report.get("checks", []):
        if not isinstance(item, dict):
            continue
        readiness_key = PREMARKET_TO_READINESS_KEYS.get(str(item.get("key", "")))
        if readiness_key is None:
            continue
        status = str(item.get("status", "unknown")).strip().lower()
        passed = status in READINESS_OK_STATUSES
        result[readiness_key] = {
            "status": "ok" if passed else status,
            "passed": passed,
            "summary": f"premarket {item.get('key')} status: {status}",
            "details": _safe_details(item.get("details", {})),
        }
    return result


def _keyed_check(check: dict[str, Any], expected_key: str) -> dict[str, Any]:
    if check.get("key") != expected_key:
        return {
            "key": expected_key,
            "status": "invalid_fixture",
            "passed": False,
            "summary": f"{expected_key} check payload must have key={expected_key}",
            "details": {},
        }
    return {
        "key": expected_key,
        "status": str(check.get("status", "unknown")).strip().lower(),
        "passed": bool(check.get("passed", False)),
        "summary": str(check.get("summary", f"{expected_key} check payload")),
        "details": _safe_details(check.get("details", {})),
    }


def _kill_switch_check(state: LiveKillSwitchState) -> dict[str, Any]:
    passed = state.status == "ok" and not state.enabled
    return {
        "status": "ok" if passed else "failed",
        "passed": passed,
        "summary": "kill switch is off and fresh" if passed else f"kill switch blocks submit: {state.submit_blocking_reason}",
        "details": {
            "state_status": state.status,
            "enabled": state.enabled,
            "scope": state.scope,
            "symbol": state.symbol,
            "updated_at": state.updated_at.isoformat() if state.updated_at else None,
            "stale_after": state.stale_after.isoformat() if state.stale_after else None,
        },
    }


def _safe_details(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _safe_value(item) for key, item in value.items()}


def _safe_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    return str(value)
