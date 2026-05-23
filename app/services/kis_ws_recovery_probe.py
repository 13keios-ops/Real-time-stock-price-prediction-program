"""Synthetic KIS WebSocket recovery checks for live readiness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from app.brokers.kis_quote_ws import KisWebSocketReconnectMetrics


def build_synthetic_ws_recovery_check(
    *,
    checked_at: datetime | None = None,
    stable_frame_reset_threshold: int = 2,
    reconnect_storm_threshold: int = 3,
) -> dict[str, object]:
    """Exercise reconnect metrics without opening a network WebSocket."""

    start = checked_at or datetime.now(timezone.utc)
    clock = _sequence_clock(
        start,
        start + timedelta(seconds=1),
        start + timedelta(seconds=2),
        start + timedelta(seconds=3),
    )
    metrics = KisWebSocketReconnectMetrics(
        stable_frame_reset_threshold=stable_frame_reset_threshold,
        reconnect_storm_threshold=reconnect_storm_threshold,
        clock=clock,
    )
    dropped = metrics.record_disconnected("synthetic_drop")
    connected = metrics.record_connected()
    first_frame = metrics.record_frame()
    stable = metrics.record_frame()
    passed = (
        stable is not None
        and stable.state == "stable"
        and stable.stable_connection_seen
        and stable.consecutive_reconnects == 0
        and stable.cumulative_reconnects == 1
        and not stable.reconnect_storm
        and first_frame is None
    )
    return {
        "key": "ws_recovery",
        "status": "ok" if passed else "failed",
        "passed": passed,
        "summary": "synthetic WebSocket reconnect recovery check passed" if passed else "synthetic WebSocket reconnect recovery check failed",
        "details": {
            "evidence_type": "synthetic_fault_injection",
            "network_called": False,
            "checked_at": start.isoformat(),
            "stable_frame_reset_threshold": stable_frame_reset_threshold,
            "reconnect_storm_threshold": reconnect_storm_threshold,
            "dropped": _safe_snapshot(dropped),
            "connected": _safe_snapshot(connected),
            "stable": _safe_snapshot(stable) if stable is not None else None,
        },
    }


def _sequence_clock(*values: datetime) -> Callable[[], datetime]:
    iterator = iter(values)
    last = values[-1]

    def _clock() -> datetime:
        nonlocal last
        try:
            last = next(iterator)
        except StopIteration:
            pass
        return last

    return _clock


def _safe_snapshot(snapshot) -> dict[str, object]:
    payload = snapshot.to_dict()
    payload["last_error"] = "synthetic" if payload.get("last_error") else ""
    return payload
