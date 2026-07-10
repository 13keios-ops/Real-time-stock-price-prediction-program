"""Fail-closed Phase 1b KIS read-only observation orchestration."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from app.brokers.kis_auth import KisTokenManager, get_kis_profile
from app.brokers.kis_readonly import get_kis_readonly_client
from app.config.settings import AppSettings
from app.services.kis_account_probe import probe_kis_account_snapshot_check
from app.services.kis_account_shape_comparison import compare_kis_account_snapshot_checks
from app.services.kis_probe_errors import build_sanitized_kis_probe_error
from app.services.kis_token_probe import probe_kis_token_refresh_check
from app.services.system_clock import DEFAULT_MAX_CLOCK_SKEW_SECONDS
from app.services.system_clock_probe import DEFAULT_CLOCK_PROBE_MARKET_CODE, DEFAULT_CLOCK_PROBE_SYMBOL, probe_kis_system_clock_check


PHASE1B_NAME = "phase1b_live_readonly"
_PROTECTED_SESSION_STATUSES = frozenset({"pre-open", "regular-session"})
_REQUIRED_PREFLIGHT_CHECKS = (
    "paper_mode_preserved",
    "live_orders_disabled",
    "paper_account_credentials_present",
    "live_quote_credentials_present",
    "live_account_credentials_present",
    "readonly_order_surface_absent",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_phase1b_readonly_preflight(
    settings: AppSettings,
    *,
    readonly_client_factory: Callable[..., Any] = get_kis_readonly_client,
) -> dict[str, Any]:
    """Check Phase 1b prerequisites without issuing a KIS network request."""

    readonly_surface_ok = False
    factory_error_type: str | None = None
    try:
        readonly_client = readonly_client_factory(settings, mode="live", timeout_seconds=1)
        readonly_surface_ok = not any(
            hasattr(readonly_client, method_name)
            for method_name in ("submit_cash_order", "cancel_order")
        )
    except Exception as exc:
        factory_error_type = type(exc).__name__

    paper = settings.kis_paper
    live = settings.kis_live
    checks = {
        "paper_mode_preserved": settings.trading_mode == "paper",
        "live_orders_disabled": not settings.allow_live_orders,
        "paper_account_credentials_present": bool(
            paper.app_key and paper.app_secret and paper.account_no and paper.product_code
        ),
        "live_quote_credentials_present": bool(live.app_key and live.app_secret),
        "live_account_credentials_present": bool(
            live.app_key and live.app_secret and live.account_no and live.product_code
        ),
        "readonly_order_surface_absent": readonly_surface_ok,
    }
    blockers = [key for key in _REQUIRED_PREFLIGHT_CHECKS if not checks[key]]
    detail: dict[str, Any] = {
        "trading_mode": settings.trading_mode,
        "allow_live_orders": settings.allow_live_orders,
        "credentials_reported_as_presence_only": True,
        "network_calls_executed": 0,
    }
    if factory_error_type is not None:
        detail["readonly_factory_error_type"] = factory_error_type
    return {
        "schema_version": 1,
        "phase": PHASE1B_NAME,
        "status": "ready" if not blockers else "blocked",
        "passed": not blockers,
        "checks": checks,
        "blocking_reasons": blockers,
        "detail": detail,
        "safety": {
            "access": "preflight-only",
            "order_methods_exposed": not readonly_surface_ok,
            "order_method_calls": 0,
            "raw_response_included": False,
            "account_identifier_included": False,
            "credential_values_included": False,
        },
    }


def run_phase1b_readonly_observation(
    settings: AppSettings,
    *,
    symbol: str = DEFAULT_CLOCK_PROBE_SYMBOL,
    market_code: str = DEFAULT_CLOCK_PROBE_MARKET_CODE,
    timeout_seconds: int = 10,
    max_skew_seconds: float = DEFAULT_MAX_CLOCK_SKEW_SECONDS,
    checked_at: datetime | None = None,
    session_status: str | None = None,
    readonly_client_factory: Callable[..., Any] = get_kis_readonly_client,
    profile_factory: Callable[..., Any] = get_kis_profile,
    token_manager_factory: Callable[..., Any] = KisTokenManager,
    clock_time_factory: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    """Run the bounded Phase 1b observation after a network-free preflight."""

    observed_at = checked_at or datetime.now(timezone.utc)
    preflight = build_phase1b_readonly_preflight(
        settings,
        readonly_client_factory=readonly_client_factory,
    )
    network_calls_executed = 0
    normalized_session = str(session_status or "").strip().lower()
    if normalized_session:
        preflight["detail"]["market_session_status"] = normalized_session
    if normalized_session in _PROTECTED_SESSION_STATUSES:
        return _build_result(
            observed_at=observed_at,
            preflight=preflight,
            execution_started=False,
            network_calls_executed=network_calls_executed,
            artifacts={},
            additional_blockers=["protected_market_session"],
        )
    if not preflight["passed"]:
        return _build_result(
            observed_at=observed_at,
            preflight=preflight,
            execution_started=False,
            network_calls_executed=network_calls_executed,
            artifacts={},
            additional_blockers=["phase1b_preflight_blocked"],
        )

    try:
        profile = profile_factory(settings, "live")
        token_manager = token_manager_factory(profile)
    except Exception as exc:
        token_check = {
            "key": "token_refresh",
            "status": "failed",
            "passed": False,
            "summary": "KIS live token client creation failed",
            "details": {
                "mode": "live",
                **build_sanitized_kis_probe_error(exc),
            },
        }
    else:
        network_calls_executed += 1
        token_check = probe_kis_token_refresh_check(
            token_manager,
            mode="live",
            force_refresh=True,
            checked_at=observed_at,
        )
    artifacts: dict[str, dict[str, Any]] = {"token_refresh_live": token_check}
    if not token_check["passed"]:
        artifacts.update(_not_run_artifacts("live_token_refresh_failed"))
        return _build_result(
            observed_at=observed_at,
            preflight=preflight,
            execution_started=network_calls_executed > 0,
            network_calls_executed=network_calls_executed,
            artifacts=artifacts,
            additional_blockers=(
                None
                if network_calls_executed > 0
                else ["live_token_client_creation_failed"]
            ),
        )

    paper_client, paper_factory_error = _build_readonly_client(
        readonly_client_factory,
        settings,
        mode="paper",
        timeout_seconds=timeout_seconds,
    )
    live_client, live_factory_error = _build_readonly_client(
        readonly_client_factory,
        settings,
        mode="live",
        timeout_seconds=timeout_seconds,
    )
    if paper_client is not None:
        network_calls_executed += 1
        paper_account = probe_kis_account_snapshot_check(
            paper_client,
            mode="paper",
            checked_at=observed_at,
            max_pages=1,
        )
    else:
        paper_account = _failed_check("account_snapshot", "paper", paper_factory_error)
    if live_client is not None:
        network_calls_executed += 1
        live_account = probe_kis_account_snapshot_check(
            live_client,
            mode="live",
            checked_at=observed_at,
            max_pages=1,
        )
    else:
        live_account = _failed_check("account_snapshot", "live", live_factory_error)
    artifacts["account_snapshot_paper"] = paper_account
    artifacts["account_snapshot_live"] = live_account

    if live_client is not None and live_account["passed"]:
        network_calls_executed += 1
        live_clock = probe_kis_system_clock_check(
            live_client,
            symbol=symbol,
            market_code=market_code,
            local_time=clock_time_factory(),
            max_skew_seconds=max_skew_seconds,
            reference_source="kis_rest_http_date_live",
        )
    else:
        live_clock = _not_run_check("system_clock", "live_account_snapshot_not_passed")
    artifacts["system_clock_live"] = live_clock

    artifacts["account_shape_comparison"] = compare_kis_account_snapshot_checks(
        paper_account,
        live_account,
        checked_at=observed_at,
    )
    return _build_result(
        observed_at=observed_at,
        preflight=preflight,
        execution_started=True,
        network_calls_executed=network_calls_executed,
        artifacts=artifacts,
    )


def build_phase1b_readiness_fixture_overrides(
    observation: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Convert a sanitized Phase 1b observation into readiness overrides."""

    artifacts_value = observation.get("artifacts")
    artifacts = artifacts_value if isinstance(artifacts_value, dict) else {}
    checked_at = str(observation.get("checked_at") or "")
    execution_started = bool(observation.get("execution_started", False))
    observation_blockers = _phase1b_observation_envelope_blockers(observation)
    token = _phase1b_artifact_override(
        artifacts,
        artifact_key="token_refresh_live",
        readiness_key="token_refresh",
        checked_at=checked_at,
        observation_blockers=observation_blockers,
    )
    clock = _phase1b_artifact_override(
        artifacts,
        artifact_key="system_clock_live",
        readiness_key="system_clock",
        checked_at=checked_at,
        observation_blockers=observation_blockers,
    )

    account_parts = {
        "paper_account": artifacts.get("account_snapshot_paper"),
        "live_account": artifacts.get("account_snapshot_live"),
        "shape_comparison": artifacts.get("account_shape_comparison"),
    }
    account_blockers: list[str] = list(observation_blockers)
    for label, value in account_parts.items():
        if not isinstance(value, dict) or not bool(value.get("passed", False)):
            account_blockers.append(f"{label}_not_passed")
    account_details: dict[str, Any] = {
        "source": "phase1b_paper_live_shape_comparison",
        "checked_at": checked_at or None,
        "observation_status": observation.get("status"),
        "observation_blocking_reasons": list(observation.get("blocking_reasons") or []),
        "observation_envelope_blocking_reasons": list(observation_blockers),
        "paper_account_status": _phase1b_status(account_parts["paper_account"]),
        "live_account_status": _phase1b_status(account_parts["live_account"]),
        "shape_comparison_status": _phase1b_status(account_parts["shape_comparison"]),
        "blocking_reasons": account_blockers,
    }
    account_passed = not account_blockers
    account = {
        "key": "account_snapshot",
        "status": "ok" if account_passed else "not_verified" if not execution_started else "failed",
        "passed": account_passed,
        "summary": (
            "Phase 1b paper/live account snapshot shapes are compatible"
            if account_passed
            else "Phase 1b paper/live account snapshot evidence is incomplete"
        ),
        "details": account_details,
    }
    return {
        "token_refresh": token,
        "account_snapshot": account,
        "system_clock": clock,
    }


def _phase1b_observation_envelope_blockers(observation: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if observation.get("phase") != PHASE1B_NAME:
        blockers.append("phase1b_observation_phase_invalid")
    execution_started = bool(observation.get("execution_started", False))
    if not execution_started:
        blockers.append("phase1b_execution_not_started")
    if observation.get("execution_mode") != "read-only-observation":
        blockers.append("phase1b_execution_mode_invalid")
    network_calls = observation.get("network_calls_executed")
    valid_network_call_count = (
        isinstance(network_calls, int)
        and not isinstance(network_calls, bool)
        and (
            1 <= network_calls <= 4
            if execution_started
            else network_calls == 0
        )
    )
    if not valid_network_call_count:
        blockers.append("phase1b_network_call_count_invalid")
    if observation.get("status") != "ok" or not bool(observation.get("passed", False)):
        blockers.append("phase1b_observation_not_passed")

    preflight = observation.get("preflight")
    if not isinstance(preflight, dict) or not bool(preflight.get("passed", False)):
        blockers.append("phase1b_preflight_not_passed")
    safety = observation.get("safety")
    if not isinstance(safety, dict):
        blockers.append("phase1b_safety_missing")
    else:
        if safety.get("order_method_calls") != 0:
            blockers.append("phase1b_order_calls_not_zero")
        if bool(safety.get("allow_live_orders", True)):
            blockers.append("phase1b_live_orders_not_disabled")
        for key in (
            "raw_response_included",
            "account_identifier_included",
            "credential_values_included",
        ):
            if bool(safety.get(key, True)):
                blockers.append(f"phase1b_{key}")
        if safety.get("account_snapshot_max_pages_per_mode") != 1:
            blockers.append("phase1b_account_page_limit_invalid")
    return list(dict.fromkeys(blockers))

def _phase1b_artifact_override(
    artifacts: dict[str, Any],
    *,
    artifact_key: str,
    readiness_key: str,
    checked_at: str,
    observation_blockers: list[str],
) -> dict[str, Any]:
    artifact = artifacts.get(artifact_key)
    if not isinstance(artifact, dict):
        return {
            "key": readiness_key,
            "status": "not_verified",
            "passed": False,
            "summary": f"Phase 1b {readiness_key} evidence is missing",
            "details": {
                "source": "phase1b_readonly_observation",
                "checked_at": checked_at or None,
                "blocking_reasons": list(dict.fromkeys([f"{artifact_key}_missing", *observation_blockers])),
            },
        }
    override = deepcopy(artifact)
    override["key"] = readiness_key
    details_value = override.get("details")
    details = deepcopy(details_value) if isinstance(details_value, dict) else {}
    details.setdefault("source", "phase1b_readonly_observation")
    if readiness_key != "system_clock":
        details.setdefault("checked_at", checked_at or None)
    override["details"] = details
    override["passed"] = bool(override.get("passed", False))
    if observation_blockers:
        override["status"] = (
            "not_verified"
            if "phase1b_execution_not_started" in observation_blockers
            else "invalid_observation"
        )
        override["passed"] = False
        override["summary"] = f"Phase 1b {readiness_key} observation envelope is invalid"
        existing = details.get("blocking_reasons")
        existing_reasons = list(existing) if isinstance(existing, list) else []
        details["blocking_reasons"] = list(dict.fromkeys([*existing_reasons, *observation_blockers]))
    return override


def _phase1b_status(value: Any) -> str:
    return str(value.get("status") or "missing") if isinstance(value, dict) else "missing"


def _build_readonly_client(
    factory: Callable[..., Any],
    settings: AppSettings,
    *,
    mode: str,
    timeout_seconds: int,
) -> tuple[Any | None, dict[str, Any] | None]:
    try:
        return factory(settings, mode=mode, timeout_seconds=timeout_seconds), None
    except Exception as exc:
        return None, build_sanitized_kis_probe_error(exc)


def _failed_check(key: str, mode: str, error: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "key": key,
        "status": "failed",
        "passed": False,
        "summary": f"{mode} read-only client creation failed",
        "details": {
            "mode": mode,
            **(error or {"error_category": "client_error", "error_type": "UnknownError"}),
        },
    }


def _not_run_check(key: str, reason: str) -> dict[str, Any]:
    return {
        "key": key,
        "status": "not_run",
        "passed": False,
        "summary": "check not run after an earlier fail-closed blocker",
        "details": {"reason": reason},
    }


def _not_run_artifacts(reason: str) -> dict[str, dict[str, Any]]:
    paper = _not_run_check("account_snapshot", reason)
    paper["details"]["mode"] = "paper"
    live = _not_run_check("account_snapshot", reason)
    live["details"]["mode"] = "live"
    return {
        "account_snapshot_paper": paper,
        "account_snapshot_live": live,
        "system_clock_live": _not_run_check("system_clock", reason),
        "account_shape_comparison": {
            "schema_version": 1,
            "status": "not_run",
            "passed": False,
            "comparison": "kis_account_snapshot_shape_paper_vs_live",
            "blocking_reasons": [reason],
        },
    }


def _build_result(
    *,
    observed_at: datetime,
    preflight: dict[str, Any],
    execution_started: bool,
    network_calls_executed: int,
    artifacts: dict[str, dict[str, Any]],
    additional_blockers: list[str] | None = None,
) -> dict[str, Any]:
    required_artifacts = (
        "token_refresh_live",
        "account_snapshot_paper",
        "account_snapshot_live",
        "system_clock_live",
        "account_shape_comparison",
    )
    if execution_started:
        checks = {
            key: bool(artifacts.get(key, {}).get("passed", False))
            for key in required_artifacts
        }
        blockers = list(additional_blockers or [])
        blockers.extend(key for key, passed in checks.items() if not passed)
    else:
        checks = {}
        blockers = list(preflight.get("blocking_reasons", []))
        blockers.extend(additional_blockers or [])
    passed = execution_started and preflight["passed"] and all(checks.values()) and not additional_blockers
    return {
        "schema_version": 1,
        "phase": PHASE1B_NAME,
        "status": "ok" if passed else "blocked",
        "passed": passed,
        "checked_at": observed_at.isoformat(),
        "execution_mode": "read-only-observation" if execution_started else "preflight-blocked",
        "execution_started": execution_started,
        "network_calls_executed": network_calls_executed,
        "preflight": preflight,
        "checks": checks,
        "blocking_reasons": list(dict.fromkeys(blockers)),
        "artifacts": artifacts,
        "safety": {
            "order_method_calls": 0,
            "allow_live_orders": bool(preflight.get("detail", {}).get("allow_live_orders", True)),
            "raw_response_included": False,
            "account_identifier_included": False,
            "credential_values_included": False,
            "account_snapshot_max_pages_per_mode": 1,
            "planned_network_operations": [
                "live_token_refresh",
                "paper_account_snapshot",
                "live_account_snapshot",
                "live_current_price_for_system_clock",
            ],
        },
    }
