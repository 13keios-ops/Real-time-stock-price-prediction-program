"""System clock skew evaluation for live-operation readiness.

The helpers here do not call the network. They compare a local timestamp with a
trusted reference timestamp supplied by another layer, such as a broker response
or an operator-provided clock check.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any


DEFAULT_MAX_CLOCK_SKEW_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class ClockSkewDecision:
    allowed: bool
    skew_seconds: float
    max_skew_seconds: float
    local_time: datetime
    reference_time: datetime
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClockReferenceTimestamp:
    source: str
    reference_time: datetime
    raw_value: str


def evaluate_clock_skew(
    *,
    local_time: datetime,
    reference_time: datetime,
    max_skew_seconds: float = DEFAULT_MAX_CLOCK_SKEW_SECONDS,
) -> ClockSkewDecision:
    normalized_local = _normalize_datetime(local_time)
    normalized_reference = _normalize_datetime(reference_time)
    limit = max(float(max_skew_seconds), 0.0)
    skew_seconds = round(abs((normalized_local - normalized_reference).total_seconds()), 6)
    reasons: list[str] = []
    if skew_seconds > limit:
        reasons.append("system_clock_skew_exceeded")
    return ClockSkewDecision(
        allowed=not reasons,
        skew_seconds=skew_seconds,
        max_skew_seconds=limit,
        local_time=normalized_local,
        reference_time=normalized_reference,
        blocking_reasons=tuple(reasons),
    )


def reference_time_from_http_date_header(
    headers: Mapping[str, Any] | Iterable[tuple[str, Any]],
    *,
    source: str = "kis_rest_http_date",
) -> ClockReferenceTimestamp | None:
    """Extract a trusted reference timestamp from an HTTP Date header.

    KIS REST clients already expose response headers as lower-case dictionaries,
    but tests and future adapters may pass case-preserving mappings. This helper
    stays offline and only parses caller-provided headers.
    """

    raw_value = _header_value(headers, "date")
    if raw_value is None or str(raw_value).strip() == "":
        return None
    try:
        parsed = parsedate_to_datetime(str(raw_value))
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError(f"invalid HTTP Date header for clock reference: {raw_value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"HTTP Date header must include a timezone: {raw_value}")
    return ClockReferenceTimestamp(
        source=source,
        reference_time=_normalize_datetime(parsed),
        raw_value=str(raw_value),
    )


def evaluate_clock_skew_from_http_date_header(
    headers: Mapping[str, Any] | Iterable[tuple[str, Any]],
    *,
    local_time: datetime,
    source: str = "kis_rest_http_date",
    max_skew_seconds: float = DEFAULT_MAX_CLOCK_SKEW_SECONDS,
) -> ClockSkewDecision | None:
    reference = reference_time_from_http_date_header(headers, source=source)
    if reference is None:
        return None
    return evaluate_clock_skew(
        local_time=local_time,
        reference_time=reference.reference_time,
        max_skew_seconds=max_skew_seconds,
    )


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _header_value(headers: Mapping[str, Any] | Iterable[tuple[str, Any]], wanted: str) -> Any | None:
    wanted_lower = wanted.lower()
    if isinstance(headers, Mapping):
        for key in (wanted, wanted_lower, wanted.upper(), wanted.title()):
            if key in headers:
                return headers[key]
        items = headers.items()
    else:
        items = headers
    for key, value in items:
        if str(key).lower() == wanted_lower:
            return value
    return None
