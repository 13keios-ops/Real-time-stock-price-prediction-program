"""Read-only system clock probes for live readiness.

The probe makes one quote read, then evaluates the HTTP Date response header.
It does not expose raw headers in its returned payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.kis_probe_errors import build_sanitized_kis_probe_error
from app.services.live_phase_readiness import build_system_clock_check_from_http_date_headers
from app.services.system_clock import DEFAULT_MAX_CLOCK_SKEW_SECONDS


DEFAULT_CLOCK_PROBE_SYMBOL = "005930"
DEFAULT_CLOCK_PROBE_MARKET_CODE = "J"


def probe_kis_system_clock_check(
    readonly_client: Any,
    *,
    symbol: str = DEFAULT_CLOCK_PROBE_SYMBOL,
    market_code: str = DEFAULT_CLOCK_PROBE_MARKET_CODE,
    local_time: datetime | None = None,
    max_skew_seconds: float = DEFAULT_MAX_CLOCK_SKEW_SECONDS,
    reference_source: str = "kis_rest_http_date",
) -> dict[str, Any]:
    """Build a readiness-compatible system_clock check from a read-only quote call."""

    observed_at = local_time or datetime.now().astimezone()
    try:
        readonly_client.get_current_price(symbol=symbol, market_code=market_code)
    except Exception as exc:  # pragma: no cover - exact client failures vary by network.
        error_details = build_sanitized_kis_probe_error(exc)
        return {
            "key": "system_clock",
            "status": "failed",
            "passed": False,
            "summary": "system clock probe failed before HTTP Date header could be read",
            "details": {
                "source": reference_source,
                "probe": "kis_readonly_current_price",
                "symbol": symbol,
                "market_code": market_code,
                **error_details,
            },
        }

    check = build_system_clock_check_from_http_date_headers(
        readonly_client.last_response_headers,
        local_time=observed_at,
        reference_source=reference_source,
        max_skew_seconds=max_skew_seconds,
    )
    if check.get("status") == "invalid_fixture":
        check["summary"] = "system clock HTTP Date header invalid"
    details = dict(check.get("details", {})) if isinstance(check.get("details"), dict) else {}
    details.update(
        {
            "probe": "kis_readonly_current_price",
            "symbol": symbol,
            "market_code": market_code,
        }
    )
    check["details"] = details
    return check


def build_system_clock_reference_comparison(
    paper_check: dict[str, Any],
    live_check: dict[str, Any],
    *,
    max_reference_delta_seconds: float = 1.0,
) -> dict[str, Any]:
    """Compare sanitized paper/live HTTP Date references without exposing headers."""

    paper_details = paper_check.get("details") if isinstance(paper_check.get("details"), dict) else {}
    live_details = live_check.get("details") if isinstance(live_check.get("details"), dict) else {}
    paper_reference = _parse_optional_datetime(paper_details.get("reference_time"))
    live_reference = _parse_optional_datetime(live_details.get("reference_time"))
    details: dict[str, Any] = {
        "paper_status": paper_check.get("status"),
        "live_status": live_check.get("status"),
        "paper_passed": bool(paper_check.get("passed", False)),
        "live_passed": bool(live_check.get("passed", False)),
        "paper_source": paper_details.get("source"),
        "live_source": live_details.get("source"),
        "reference_precision_seconds": max(
            float(paper_details.get("reference_precision_seconds") or 0.0),
            float(live_details.get("reference_precision_seconds") or 0.0),
        )
        or None,
        "max_reference_delta_seconds": max_reference_delta_seconds,
    }
    blocking_reasons: list[str] = []
    if paper_reference is None:
        blocking_reasons.append("paper_reference_time_missing")
    if live_reference is None:
        blocking_reasons.append("live_reference_time_missing")
    if paper_reference is not None and live_reference is not None:
        delta_seconds = abs((paper_reference - live_reference).total_seconds())
        details["reference_delta_seconds"] = round(delta_seconds, 3)
        if delta_seconds > max_reference_delta_seconds:
            blocking_reasons.append("paper_live_reference_delta_too_large")
    if not bool(paper_check.get("passed", False)):
        blocking_reasons.append("paper_clock_check_not_passed")
    if not bool(live_check.get("passed", False)):
        blocking_reasons.append("live_clock_check_not_passed")

    passed = not blocking_reasons
    details["blocking_reasons"] = blocking_reasons
    return {
        "key": "system_clock_reference_comparison",
        "status": "ok" if passed else "blocked",
        "passed": passed,
        "summary": "paper/live KIS HTTP Date references are aligned" if passed else "paper/live KIS HTTP Date references need attention",
        "details": details,
    }


def _parse_optional_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed
