"""Helpers for live phase approvals and readiness records.

Only the original six readiness checks have dedicated SQL columns. Newer
operational checks stay in checks_json until dashboard/report queries need a
deliberate schema migration.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable

from app.services.system_clock import (
    DEFAULT_MAX_CLOCK_SKEW_SECONDS,
    evaluate_clock_skew,
    evaluate_clock_skew_from_http_date_header,
    reference_time_from_http_date_header,
)
from app.services.ws_recovery_evidence import (
    REAL_WS_RECOVERY_EVIDENCE_TYPES,
    is_real_ws_recovery_evidence_type,
)
from app.storage.contracts import LivePhaseApproval, LiveReadinessRun


READINESS_CHECK_KEYS = (
    "token_refresh",
    "ws_recovery",
    "account_snapshot",
    "market_status",
    "system_clock",
    "kill_switch",
    "database",
    "disk_space",
    "dashboard",
    "storage_migration_state",
)
# These six checks already have dedicated LiveReadinessRun SQL columns.
# Newer operational checks stay in checks_json until a deliberate schema
# migration promotes them to first-class columns.
READINESS_SQL_COLUMN_KEYS = (
    "token_refresh",
    "ws_recovery",
    "account_snapshot",
    "market_status",
    "kill_switch",
    "database",
)
READINESS_OK_STATUSES = {"ok", "passed", "healthy", "ready"}
DEFAULT_READINESS_EVIDENCE_MAX_AGE_SECONDS = 3600.0
READINESS_EVIDENCE_MAX_AGE_SECONDS = {
    "token_refresh": 14400.0,
    "ws_recovery": 1800.0,
    "account_snapshot": 3600.0,
    "market_status": 3600.0,
    "system_clock": 1800.0,
}
READINESS_FRESH_EVIDENCE_KEYS = set(READINESS_EVIDENCE_MAX_AGE_SECONDS)
PHASE1A_PAPER_READONLY_REQUIRED_CHECK_KEYS = tuple(
    key for key in READINESS_CHECK_KEYS if key not in {"market_status", "kill_switch"}
)
PHASE1B_LIVE_READONLY_REQUIRED_CHECK_KEYS = PHASE1A_PAPER_READONLY_REQUIRED_CHECK_KEYS


def readiness_required_check_keys_for_phase(phase: str) -> tuple[str, ...]:
    normalized = _normalize_phase_name(phase)
    if normalized in {"phase1a", "phase1a_paper_readonly", "phase1_paper_readonly_rehearsal"}:
        return PHASE1A_PAPER_READONLY_REQUIRED_CHECK_KEYS
    if normalized in {"phase1b", "phase1b_live_readonly", "phase1_live_readonly_observation"}:
        return PHASE1B_LIVE_READONLY_REQUIRED_CHECK_KEYS
    return READINESS_CHECK_KEYS


def create_phase_approval(
    *,
    phase: str,
    trading_day: str,
    approved_at: datetime,
    approved_by: str,
    expires_at: datetime,
    scope: str,
    max_symbols: int,
    max_parent_orders: int,
    max_notional: float,
    daily_loss_limit_pct: float,
    per_symbol_loss_limit_pct: float,
    slippage_budget_bps: float,
    approval_basis: str,
    operator_decision_ref: str,
    extra_limits: dict[str, Any] | None = None,
    approval_id: str | None = None,
) -> LivePhaseApproval:
    limits = {
        "max_symbols": max_symbols,
        "max_parent_orders": max_parent_orders,
        "max_notional": max_notional,
        "daily_loss_limit_pct": daily_loss_limit_pct,
        "per_symbol_loss_limit_pct": per_symbol_loss_limit_pct,
        "slippage_budget_bps": slippage_budget_bps,
    }
    if extra_limits:
        limits.update(extra_limits)
    hash_payload = {
        "phase": phase,
        "trading_day": trading_day,
        "approved_at": approved_at.isoformat(),
        "approved_by": approved_by,
        "expires_at": expires_at.isoformat(),
        "scope": scope,
        "limits": limits,
        "approval_basis": approval_basis,
        "operator_decision_ref": operator_decision_ref,
    }
    approval_hash = _hash_payload(hash_payload)
    return LivePhaseApproval(
        approval_id=approval_id or f"approval-{approval_hash[:16]}",
        phase=phase,
        trading_day=trading_day,
        approved_at=approved_at,
        approved_by=approved_by,
        expires_at=expires_at,
        scope=scope,
        max_symbols=max_symbols,
        max_parent_orders=max_parent_orders,
        max_notional=max_notional,
        daily_loss_limit_pct=daily_loss_limit_pct,
        per_symbol_loss_limit_pct=per_symbol_loss_limit_pct,
        slippage_budget_bps=slippage_budget_bps,
        approval_hash=approval_hash,
        detail_json={
            "approval_basis": approval_basis,
            "limits": limits,
            "operator_decision_ref": operator_decision_ref,
        },
    )


def create_readiness_run(
    *,
    phase: str,
    trading_day: str,
    checked_at: datetime,
    checks: dict[str, bool],
    blocking_reasons: list[str] | None = None,
    report_path: str,
    readiness_id: str | None = None,
    extra_detail: dict[str, Any] | None = None,
    required_check_keys: Iterable[str] | None = None,
) -> LiveReadinessRun:
    missing = sorted(set(READINESS_CHECK_KEYS) - set(checks))
    if missing:
        raise ValueError(f"checks missing required keys: {', '.join(missing)}")
    required_keys = tuple(required_check_keys or READINESS_CHECK_KEYS)
    unknown_required = sorted(set(required_keys) - set(READINESS_CHECK_KEYS))
    if unknown_required:
        raise ValueError(f"unknown required readiness check keys: {', '.join(unknown_required)}")
    required_key_set = set(required_keys)
    optional_keys = tuple(key for key in READINESS_CHECK_KEYS if key not in required_key_set)
    normalized_checks = {key: bool(checks[key]) for key in READINESS_CHECK_KEYS}
    reasons = list(blocking_reasons or [])
    passed = all(normalized_checks[key] for key in required_keys) and not reasons
    status = "ok" if passed else "blocked"
    hash_payload = {
        "phase": phase,
        "trading_day": trading_day,
        "checked_at": checked_at.isoformat(),
        "checks": normalized_checks,
        "blocking_reasons": reasons,
        "report_path": report_path,
        "required_check_keys": list(required_keys),
        "optional_check_keys": list(optional_keys),
    }
    if extra_detail:
        hash_payload["extra_detail"] = extra_detail
    readiness_hash = _hash_payload(hash_payload)
    return LiveReadinessRun(
        readiness_id=readiness_id or f"readiness-{readiness_hash[:16]}",
        trading_day=trading_day,
        checked_at=checked_at,
        phase=phase,
        status=status,
        passed=passed,
        token_refresh_ok=normalized_checks["token_refresh"],
        ws_recovery_ok=normalized_checks["ws_recovery"],
        account_snapshot_ok=normalized_checks["account_snapshot"],
        market_status_ok=normalized_checks["market_status"],
        kill_switch_ok=normalized_checks["kill_switch"],
        database_ok=normalized_checks["database"],
        checks_json={
            "checks": normalized_checks,
            "required_check_keys": list(required_keys),
            "optional_check_keys": list(optional_keys),
            "blocking_reasons": reasons,
            "readiness_hash": readiness_hash,
            "extra_detail": extra_detail or {},
        },
        report_path=report_path,
    )


def create_readiness_run_from_premarket_report(
    *,
    phase: str,
    trading_day: str,
    checked_at: datetime,
    premarket_report: dict[str, Any],
    report_path: str,
    override_checks: dict[str, bool] | None = None,
    readiness_id: str | None = None,
) -> LiveReadinessRun:
    """Convert a Codex ops premarket report into a conservative readiness record.

    The premarket report can verify operational plumbing, but it does not prove
    WebSocket recovery, account snapshot freshness, market status, or kill switch
    by itself. Those checks stay false unless a caller provides explicit overrides
    from a separate runner.
    """

    check_statuses = _codex_ops_check_statuses(premarket_report)
    checks = {
        "token_refresh": check_statuses.get("kis_credentials") == "ok",
        "ws_recovery": False,
        "account_snapshot": False,
        "market_status": False,
        "system_clock": False,
        "kill_switch": False,
        "database": check_statuses.get("database") == "ok",
        "disk_space": check_statuses.get("disk_space") == "ok",
        "dashboard": check_statuses.get("dashboard") == "ok",
        "storage_migration_state": check_statuses.get("storage_migration_state") == "ok",
    }
    if override_checks:
        for key, value in override_checks.items():
            if key not in READINESS_CHECK_KEYS:
                raise ValueError(f"unknown readiness check override: {key}")
            checks[key] = bool(value)

    required_keys = readiness_required_check_keys_for_phase(phase)
    required_key_set = set(required_keys)
    optional_keys = tuple(key for key in READINESS_CHECK_KEYS if key not in required_key_set)
    reasons = [f"codex_ops_{key}_blocked" for key in premarket_report.get("blockers", [])]
    non_blocking_reasons: list[str] = []
    for key in ("token_refresh", "database", "disk_space", "dashboard", "storage_migration_state"):
        if not checks[key] and (not override_checks or key not in override_checks):
            reason = f"{key}_not_ok_in_premarket_report"
            if key in required_key_set:
                reasons.append(reason)
            else:
                non_blocking_reasons.append(reason)
    for key in ("ws_recovery", "account_snapshot", "market_status", "system_clock", "kill_switch"):
        if not checks[key] and (not override_checks or key not in override_checks):
            reason = f"{key}_not_verified_by_premarket_report"
            if key in required_key_set:
                reasons.append(reason)
            else:
                non_blocking_reasons.append(reason)
    if premarket_report.get("status") == "blocked":
        reasons.append("codex_ops_premarket_blocked")

    extra_detail = {
        "source": "codex_ops_premarket_readiness",
        "codex_ops_status": premarket_report.get("status"),
        "codex_ops_warnings": list(premarket_report.get("warnings", [])),
        "codex_ops_report_path": premarket_report.get("report_path"),
        "override_checks": sorted((override_checks or {}).keys()),
        "required_check_keys": list(required_keys),
        "optional_check_keys": list(optional_keys),
        "non_blocking_reasons": _dedupe(non_blocking_reasons),
    }
    return create_readiness_run(
        phase=phase,
        trading_day=trading_day,
        checked_at=checked_at,
        checks=checks,
        blocking_reasons=_dedupe(reasons),
        report_path=report_path,
        readiness_id=readiness_id,
        extra_detail=extra_detail,
        required_check_keys=required_keys,
    )


def build_fault_injection_dry_run_report(
    *,
    phase: str,
    trading_day: str,
    checked_at: datetime,
    premarket_report: dict[str, Any],
    fixture_results: dict[str, Any],
    report_path: str,
    source: str = "fixture-dry-run",
) -> dict[str, Any]:
    """Build a readiness report from explicit dry-run fault fixtures.

    This function does not create real faults. A check only passes when its
    fixture explicitly says ok/passed/healthy/ready. Missing fixtures stay
    unverified so the resulting readiness run remains blocked.
    """

    fixture_checks = {
        key: _enforce_evidence_freshness(
            key,
            _normalize_fault_fixture(key, fixture_results.get(key)),
            checked_at=checked_at,
        )
        for key in READINESS_CHECK_KEYS
    }
    fixture_checks["ws_recovery"] = _enforce_ws_recovery_evidence_for_phase(
        phase,
        fixture_checks["ws_recovery"],
    )
    checks = {key: check["passed"] for key, check in fixture_checks.items()}
    required_keys = readiness_required_check_keys_for_phase(phase)
    required_key_set = set(required_keys)
    optional_keys = tuple(key for key in READINESS_CHECK_KEYS if key not in required_key_set)
    reasons = [f"codex_ops_{key}_blocked" for key in premarket_report.get("blockers", [])]
    non_blocking_reasons: list[str] = []
    if premarket_report.get("status") == "blocked":
        reasons.append("codex_ops_premarket_blocked")
    for key, check in fixture_checks.items():
        if check["passed"]:
            continue
        if check["status"] == "not_verified":
            reason = f"{key}_not_verified_by_fault_dry_run"
        else:
            reason = f"{key}_fault_dry_run_failed"
        if key in required_key_set:
            reasons.append(reason)
        else:
            non_blocking_reasons.append(reason)
    extra_detail = {
        "source": "fault_injection_dry_run",
        "codex_ops_status": premarket_report.get("status"),
        "codex_ops_warnings": list(premarket_report.get("warnings", [])),
        "codex_ops_report_path": premarket_report.get("report_path"),
        "fixture_source": source,
        "required_check_keys": list(required_keys),
        "optional_check_keys": list(optional_keys),
        "non_blocking_reasons": _dedupe(non_blocking_reasons),
    }
    readiness = create_readiness_run(
        phase=phase,
        trading_day=trading_day,
        checked_at=checked_at,
        checks=checks,
        blocking_reasons=_dedupe(reasons),
        report_path=report_path,
        extra_detail=extra_detail,
        required_check_keys=required_keys,
    )
    status = "ok" if readiness.passed else "blocked"
    return {
        "schema_version": 1,
        "job_type": "live-readiness-fault-dry-run",
        "source": source,
        "status": status,
        "generated_at": checked_at.isoformat(),
        "phase": phase,
        "trading_day": trading_day,
        "report_path": report_path,
        "premarket_status": premarket_report.get("status"),
        "premarket_report_path": premarket_report.get("report_path"),
        "fixture_checks": list(fixture_checks.values()),
        "override_checks": checks,
        "readiness_run": readiness.to_record(),
        "blocking_reasons": list(readiness.checks_json["blocking_reasons"]),
        "non_blocking_reasons": list(readiness.checks_json["extra_detail"].get("non_blocking_reasons", [])),
    }


def _codex_ops_check_statuses(report: dict[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for item in report.get("checks", []):
        if isinstance(item, dict) and "key" in item:
            statuses[str(item["key"])] = str(item.get("status", "unknown"))
    return statuses


def build_system_clock_check_from_http_date_headers(
    headers: dict[str, Any],
    *,
    local_time: datetime,
    reference_source: str = "kis_rest_http_date",
    max_skew_seconds: float = DEFAULT_MAX_CLOCK_SKEW_SECONDS,
) -> dict[str, Any]:
    try:
        decision = evaluate_clock_skew_from_http_date_header(
            headers,
            local_time=local_time,
            source=reference_source,
            max_skew_seconds=max_skew_seconds,
        )
    except ValueError as exc:
        return {
            "key": "system_clock",
            "status": "invalid_fixture",
            "passed": False,
            "summary": f"system clock HTTP Date header invalid: {exc}",
            "details": {"source": reference_source},
        }
    if decision is None:
        return {
            "key": "system_clock",
            "status": "not_verified",
            "passed": False,
            "summary": "system clock HTTP Date header missing",
            "details": {"source": reference_source},
        }
    return {
        "key": "system_clock",
        "status": "ok" if decision.allowed else "failed",
        "passed": decision.allowed,
        "summary": "system clock evaluated from HTTP Date header",
        "details": {
            "source": reference_source,
            "skew_seconds": decision.skew_seconds,
            "max_skew_seconds": decision.max_skew_seconds,
            "reference_precision_seconds": 1.0,
            "precision_note": "HTTP Date has one-second precision; skew values imply an approximately sub-second bound, not millisecond precision.",
            "local_time": decision.local_time.isoformat(),
            "reference_time": decision.reference_time.isoformat(),
            "blocking_reasons": list(decision.blocking_reasons),
        },
    }


def _normalize_fault_fixture(key: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {
            "key": key,
            "status": "not_verified",
            "passed": False,
            "summary": "fixture was not provided",
            "details": {},
        }
    if isinstance(value, bool):
        status = "ok" if value else "failed"
        return {
            "key": key,
            "status": status,
            "passed": value,
            "summary": "boolean fixture result",
            "details": {},
        }
    if isinstance(value, str):
        normalized = value.strip().lower()
        return {
            "key": key,
            "status": normalized or "unknown",
            "passed": normalized in READINESS_OK_STATUSES,
            "summary": "string fixture result",
            "details": {},
        }
    if isinstance(value, dict):
        if key == "system_clock":
            clock_fixture = _normalize_system_clock_fixture(key, value)
            if clock_fixture is not None:
                return clock_fixture
        normalized = str(value.get("status", "unknown")).strip().lower()
        return {
            "key": key,
            "status": normalized,
            "passed": normalized in READINESS_OK_STATUSES,
            "summary": str(value.get("summary", "dict fixture result")),
            "details": dict(value.get("details", {})) if isinstance(value.get("details", {}), dict) else {},
        }
    return {
        "key": key,
        "status": "invalid_fixture",
        "passed": False,
        "summary": f"unsupported fixture type: {type(value).__name__}",
        "details": {},
    }


def _enforce_ws_recovery_evidence_for_phase(phase: str, check: dict[str, Any]) -> dict[str, Any]:
    if not bool(check.get("passed", False)) or not _requires_real_ws_recovery_evidence(phase):
        return check
    details = dict(check.get("details", {})) if isinstance(check.get("details", {}), dict) else {}
    evidence_type = str(details.get("evidence_type", "")).strip()
    if is_real_ws_recovery_evidence_type(evidence_type):
        return check
    details["accepted_evidence_types"] = sorted(REAL_WS_RECOVERY_EVIDENCE_TYPES)
    details["blocking_reasons"] = ["ws_recovery_real_evidence_required"]
    return {
        "key": "ws_recovery",
        "status": "invalid_evidence",
        "passed": False,
        "summary": "ws_recovery synthetic evidence is not accepted for submit phases",
        "details": details,
    }


def _requires_real_ws_recovery_evidence(phase: str) -> bool:
    normalized = _normalize_phase_name(phase)
    return normalized.startswith("phase2") or normalized.startswith("phase3")


def _normalize_phase_name(phase: str) -> str:
    return phase.strip().lower().replace("-", "_").replace(" ", "_")


def _enforce_evidence_freshness(
    key: str,
    check: dict[str, Any],
    *,
    checked_at: datetime,
) -> dict[str, Any]:
    if key not in READINESS_FRESH_EVIDENCE_KEYS or not bool(check.get("passed", False)):
        return check
    details = dict(check.get("details", {})) if isinstance(check.get("details", {}), dict) else {}
    evidence_time = _evidence_time_from_details(key, details)
    if evidence_time is None:
        return check
    age_seconds = (checked_at - evidence_time).total_seconds()
    max_age_seconds = float(READINESS_EVIDENCE_MAX_AGE_SECONDS.get(key, DEFAULT_READINESS_EVIDENCE_MAX_AGE_SECONDS))
    details["max_evidence_age_seconds"] = max_age_seconds
    if age_seconds <= max_age_seconds:
        details["evidence_age_seconds"] = round(age_seconds, 3)
        check = dict(check)
        check["details"] = details
        return check
    details["evidence_age_seconds"] = round(age_seconds, 3)
    details["blocking_reasons"] = ["readiness_evidence_stale"]
    return {
        "key": key,
        "status": "stale_evidence",
        "passed": False,
        "summary": f"{key} evidence is stale",
        "details": details,
    }


def _evidence_time_from_details(key: str, details: dict[str, Any]) -> datetime | None:
    if key == "system_clock":
        return _parse_optional_fixture_datetime(details.get("local_time"))
    if key == "ws_recovery":
        if "checked_at" in details:
            return _parse_optional_fixture_datetime(details.get("checked_at"))
        stable = details.get("stable")
        if isinstance(stable, dict):
            return _parse_optional_fixture_datetime(stable.get("observed_at"))
        return None
    return _parse_optional_fixture_datetime(details.get("checked_at"))


def _parse_optional_fixture_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = _parse_fixture_datetime(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _normalize_system_clock_fixture(key: str, value: dict[str, Any]) -> dict[str, Any] | None:
    has_clock_shape = any(item in value for item in ("local_time", "reference_time", "http_date", "headers"))
    if not has_clock_shape:
        return None
    try:
        local_time = _parse_fixture_datetime(value["local_time"])
        reference_time = _system_clock_reference_time(value)
        max_skew_seconds = float(value.get("max_skew_seconds", DEFAULT_MAX_CLOCK_SKEW_SECONDS))
        decision = evaluate_clock_skew(
            local_time=local_time,
            reference_time=reference_time.reference_time,
            max_skew_seconds=max_skew_seconds,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "key": key,
            "status": "invalid_fixture",
            "passed": False,
            "summary": f"system clock fixture invalid: {exc}",
            "details": {},
        }
    return {
        "key": key,
        "status": "ok" if decision.allowed else "failed",
        "passed": decision.allowed,
        "summary": "system clock fixture evaluated against reference time",
        "details": {
            "source": reference_time.source,
            "skew_seconds": decision.skew_seconds,
            "max_skew_seconds": decision.max_skew_seconds,
            "reference_precision_seconds": 1.0 if reference_time.source == "kis_rest_http_date" else None,
            "precision_note": "HTTP Date has one-second precision; skew values imply an approximately sub-second bound, not millisecond precision."
            if reference_time.source == "kis_rest_http_date"
            else "",
            "local_time": decision.local_time.isoformat(),
            "reference_time": decision.reference_time.isoformat(),
            "blocking_reasons": list(decision.blocking_reasons),
        },
    }


def _system_clock_reference_time(value: dict[str, Any]):
    if "reference_time" in value:
        return _InlineClockReference(_parse_fixture_datetime(value["reference_time"]))
    headers = value.get("headers")
    if headers is None and "http_date" in value:
        headers = {"date": value["http_date"]}
    reference = reference_time_from_http_date_header(
        headers or {},
        source=str(value.get("reference_source", "kis_rest_http_date")),
    )
    if reference is None:
        raise ValueError("system_clock fixture requires reference_time or HTTP Date header")
    return reference


class _InlineClockReference:
    def __init__(self, reference_time: datetime) -> None:
        self.source = "inline_reference_time"
        self.reference_time = reference_time


def _parse_fixture_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"expected datetime string, got {type(value).__name__}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
