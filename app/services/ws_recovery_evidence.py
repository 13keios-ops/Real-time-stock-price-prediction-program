"""Shared evidence types for KIS WebSocket recovery readiness.

Synthetic fault injection is useful for offline readiness plumbing, but submit
phases require evidence observed from a real KIS WebSocket session.
"""

from __future__ import annotations


REAL_KIS_WS_OBSERVED_EVIDENCE = "real_kis_ws_observed"
REAL_KIS_WS_RECOVERY_EVIDENCE = "real_kis_ws_recovery"
KIS_WS_OBSERVED_EVIDENCE = "kis_ws_observed"

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
