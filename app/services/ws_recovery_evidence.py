"""Shared evidence types for KIS WebSocket recovery readiness.

Synthetic fault injection is useful for offline readiness plumbing, but submit
phases require evidence observed from a real KIS WebSocket session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


REAL_KIS_WS_OBSERVED_EVIDENCE = "real_kis_ws_observed"
REAL_KIS_WS_RECOVERY_EVIDENCE = "real_kis_ws_recovery"
KIS_WS_OBSERVED_EVIDENCE = "kis_ws_observed"
WS_RECOVERY_MAX_AGE_SECONDS = 1800.0

REAL_WS_RECOVERY_EVIDENCE_TYPES = frozenset(
    {
        REAL_KIS_WS_OBSERVED_EVIDENCE,
        REAL_KIS_WS_RECOVERY_EVIDENCE,
        KIS_WS_OBSERVED_EVIDENCE,
    }
)

WS_RECOVERY_EVIDENCE_TYPE_DESCRIPTIONS = {
    REAL_KIS_WS_OBSERVED_EVIDENCE: "real KIS WebSocket session observed stable frames after connection",
    REAL_KIS_WS_RECOVERY_EVIDENCE: "real KIS WebSocket reconnect recovery observed after a drop",
    KIS_WS_OBSERVED_EVIDENCE: "legacy alias for a real KIS WebSocket observation",
}


def is_real_ws_recovery_evidence_type(evidence_type: str | None) -> bool:
    return (evidence_type or "").strip() in REAL_WS_RECOVERY_EVIDENCE_TYPES


def build_ws_recovery_check_from_data_quality(
    report: dict[str, Any],
    *,
    evaluated_at: datetime,
    max_age_seconds: float = WS_RECOVERY_MAX_AGE_SECONDS,
    source_report_path: str = "runtime-data/reports/data-quality/latest-kis-live-data-quality.json",
) -> dict[str, Any] | None:
    """Link complete, fresh runtime recovery lineage without making a network call."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    session = report.get("latest_session_observability")
    if not isinstance(session, dict):
        return None
    reconnects = session.get("websocket_reconnects")
    if not isinstance(reconnects, dict):
        return None
    reconnect_count = _non_negative_int(reconnects.get("count"))
    if reconnect_count == 0:
        return None

    blockers: list[str] = []
    if reconnect_count is None:
        reconnect_count = 0
        blockers.append("ws_reconnect_count_invalid")
    storm_count = _non_negative_int(reconnects.get("storm_count"))
    restore_count = _non_negative_int(reconnects.get("subscription_restore_count"))
    first_frame_count = _non_negative_int(reconnects.get("first_frame_after_restore_count"))
    connected_count = _non_negative_int(reconnects.get("connected_count"))
    if reconnects.get("status") != "observed_no_storm" or storm_count != 0:
        blockers.append("ws_reconnect_storm_detected")
    if restore_count != reconnect_count:
        blockers.append("ws_subscription_restore_incomplete")
    if first_frame_count != reconnect_count:
        blockers.append("ws_first_frame_after_restore_incomplete")
    if connected_count is None or connected_count < reconnect_count + 1:
        blockers.append("ws_connection_lineage_incomplete")

    gaps = session.get("raw_minute_gaps")
    if not isinstance(gaps, dict) or gaps.get("unexpected_common_gaps_detected") is not False:
        blockers.append("ws_unexpected_common_gaps_detected")

    coverage = report.get("latest_intraday_coverage")
    coverage = coverage if isinstance(coverage, dict) else {}
    if coverage.get("status") != "ok":
        blockers.append("ws_post_recovery_coverage_not_ok")
    trade_date = str(report.get("latest_trade_date") or "")
    lineage_dates = {
        trade_date,
        str(reconnects.get("trade_date") or ""),
        str(gaps.get("trade_date") or "") if isinstance(gaps, dict) else "",
        str(coverage.get("trade_date") or ""),
    }
    if "" in lineage_dates or len(lineage_dates) != 1:
        blockers.append("ws_recovery_trade_date_lineage_mismatch")

    recovered_at = _parse_observed_at(reconnects.get("last_first_frame_after_restore_at"))
    observed_through = _parse_observed_at(coverage.get("latest_raw_minute"))
    if recovered_at is None:
        blockers.append("ws_recovery_timestamp_missing")
    if observed_through is None or recovered_at is None or observed_through < recovered_at:
        blockers.append("ws_post_recovery_frame_lineage_missing")
    age_seconds = None if observed_through is None else (evaluated_at - observed_through).total_seconds()
    if age_seconds is None or age_seconds < 0:
        blockers.append("ws_recovery_evidence_time_invalid")
    elif age_seconds > max_age_seconds:
        blockers.append("ws_recovery_evidence_stale")

    passed = not blockers
    return {
        "key": "ws_recovery",
        "status": "ok" if passed else "failed",
        "passed": passed,
        "summary": (
            "fresh real KIS WebSocket reconnect recovery evidence is complete"
            if passed
            else "real KIS WebSocket reconnect recovery evidence is incomplete or stale"
        ),
        "details": {
            "source": "kis_live_data_quality",
            "source_report_path": source_report_path,
            "evidence_type": REAL_KIS_WS_RECOVERY_EVIDENCE,
            "network_called": False,
            "source_network_observed": True,
            "trade_date": trade_date or None,
            "checked_at": observed_through.isoformat() if observed_through else None,
            "last_first_frame_after_restore_at": recovered_at.isoformat() if recovered_at else None,
            "evidence_age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
            "max_evidence_age_seconds": float(max_age_seconds),
            "reconnect_count": reconnect_count,
            "storm_count": storm_count,
            "connected_count": connected_count,
            "subscription_restore_count": restore_count,
            "first_frame_after_restore_count": first_frame_count,
            "unexpected_common_gaps_detected": (
                gaps.get("unexpected_common_gaps_detected") if isinstance(gaps, dict) else None
            ),
            "blocking_reasons": list(dict.fromkeys(blockers)),
        },
    }


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _parse_observed_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        observed_at = datetime.fromisoformat(value.strip().replace(",", "."))
    except ValueError:
        return None
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        observed_at = observed_at.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return observed_at
