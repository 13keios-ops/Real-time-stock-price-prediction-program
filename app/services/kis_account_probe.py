"""Sanitized KIS account snapshot checks for live readiness."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.kis_probe_errors import build_sanitized_kis_probe_error
from app.services.live_phase_readiness import build_system_clock_check_from_http_date_headers
from app.services.system_clock import DEFAULT_MAX_CLOCK_SKEW_SECONDS


REQUIRED_ACCOUNT_SNAPSHOT_ATTRIBUTES = (
    "position_row_count",
    "summary_row_count",
    "cash_balance",
    "stock_evaluation_amount",
    "total_asset_amount",
)
ACCOUNT_SNAPSHOT_ROW_COUNT_ATTRIBUTES = ("position_row_count", "summary_row_count")
ACCOUNT_SNAPSHOT_NUMERIC_VALUE_ATTRIBUTES = (
    "cash_balance",
    "stock_evaluation_amount",
    "total_asset_amount",
)



def build_system_clock_check_from_account_snapshot_headers(
    readonly_client: Any,
    *,
    mode: str,
    checked_at: datetime | None = None,
    max_skew_seconds: float = DEFAULT_MAX_CLOCK_SKEW_SECONDS,
    reference_source: str = "kis_rest_http_date_account_snapshot",
) -> dict[str, Any]:
    """Build a system_clock check from the account snapshot response headers.

    This reuses the HTTP Date header from an already-issued read-only account
    query so readiness can avoid an additional quote request when quote rate
    limits are the blocker.
    """

    observed_at = checked_at or datetime.now(timezone.utc)
    headers = getattr(readonly_client, "last_response_headers", {})
    check = build_system_clock_check_from_http_date_headers(
        headers,
        local_time=observed_at,
        reference_source=reference_source,
        max_skew_seconds=max_skew_seconds,
    )
    if check.get("status") == "invalid_fixture":
        check["summary"] = "account snapshot HTTP Date header invalid"
    elif check.get("status") == "not_verified":
        check["summary"] = "account snapshot HTTP Date header missing"
    details = dict(check.get("details", {})) if isinstance(check.get("details"), dict) else {}
    details.update(
        {
            "mode": mode,
            "probe": "kis_readonly_account_snapshot",
            "derived_from": "account_snapshot",
        }
    )
    check["details"] = details
    return check


def probe_kis_account_snapshot_check(
    readonly_client: Any,
    *,
    mode: str,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a readiness-compatible account_snapshot check without account identifiers."""

    observed_at = checked_at or datetime.now(timezone.utc)
    try:
        snapshot = readonly_client.get_account_balance()
    except Exception as exc:  # pragma: no cover - network/client failures vary.
        error_details = build_sanitized_kis_probe_error(exc)
        return {
            "key": "account_snapshot",
            "status": "failed",
            "passed": False,
            "summary": "KIS account snapshot refresh failed",
            "details": {
                "mode": mode,
                "checked_at": observed_at.isoformat(),
                **error_details,
            },
        }

    missing_attributes = [attribute for attribute in REQUIRED_ACCOUNT_SNAPSHOT_ATTRIBUTES if not hasattr(snapshot, attribute)]
    invalid_type_attributes = _invalid_type_attributes(snapshot, missing_attributes)
    position_count = _safe_non_negative_int(getattr(snapshot, "position_row_count", None))
    summary_count = _safe_non_negative_int(getattr(snapshot, "summary_row_count", None))
    passed = (
        summary_count is not None
        and position_count is not None
        and summary_count >= 1
        and not missing_attributes
        and not invalid_type_attributes
    )
    if missing_attributes:
        summary = "KIS account snapshot shape invalid"
    elif invalid_type_attributes:
        summary = "KIS account snapshot value type invalid"
    elif summary_count < 1:
        summary = "KIS account snapshot missing summary row"
    else:
        summary = "KIS account snapshot refreshed"
    if missing_attributes:
        shape_status = "missing_required_attributes"
    elif invalid_type_attributes:
        shape_status = "invalid_value_types"
    else:
        shape_status = "ok"
    return {
        "key": "account_snapshot",
        "status": "ok" if passed else "failed",
        "passed": passed,
        "summary": summary,
        "details": {
            "mode": mode,
            "checked_at": observed_at.isoformat(),
            "shape_status": shape_status,
            "required_attributes": list(REQUIRED_ACCOUNT_SNAPSHOT_ATTRIBUTES),
            "missing_attributes": missing_attributes,
            "invalid_type_attributes": invalid_type_attributes,
            "position_row_count": position_count,
            "summary_row_count": summary_count,
            "cash_balance_present": getattr(snapshot, "cash_balance", None) is not None,
            "stock_evaluation_present": getattr(snapshot, "stock_evaluation_amount", None) is not None,
            "total_asset_present": getattr(snapshot, "total_asset_amount", None) is not None,
        },
    }


def _invalid_type_attributes(snapshot: Any, missing_attributes: list[str]) -> list[dict[str, str]]:
    missing = set(missing_attributes)
    invalid: list[dict[str, str]] = []
    for attribute in ACCOUNT_SNAPSHOT_ROW_COUNT_ATTRIBUTES:
        if attribute in missing:
            continue
        value = getattr(snapshot, attribute, None)
        if not _is_non_bool_int(value) or int(value) < 0:
            invalid.append(
                {
                    "attribute": attribute,
                    "expected": "non-negative int",
                    "actual_type": type(value).__name__,
                }
            )
    for attribute in ACCOUNT_SNAPSHOT_NUMERIC_VALUE_ATTRIBUTES:
        if attribute in missing:
            continue
        value = getattr(snapshot, attribute, None)
        if not _is_non_bool_number(value):
            invalid.append(
                {
                    "attribute": attribute,
                    "expected": "number",
                    "actual_type": type(value).__name__,
                }
            )
    return invalid


def _safe_non_negative_int(value: Any) -> int | None:
    if not _is_non_bool_int(value):
        return None
    count = int(value)
    if count < 0:
        return None
    return count


def _is_non_bool_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_non_bool_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
