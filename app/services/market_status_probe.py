"""Readiness checks for manual market-status snapshots."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.services.market_status import evaluate_market_status_batch
from app.storage.contracts import MarketStatusSnapshot


ALLOWED_MANUAL_MARKET_STATUS_SOURCES = (
    "manual_operator_snapshot",
    "manual_krx_snapshot",
    "manual_kis_snapshot",
)


def market_status_snapshot_from_payload(payload: dict[str, Any]) -> MarketStatusSnapshot:
    """Parse a repository-local market-status snapshot payload."""

    status_json = payload.get("status_json", {})
    if not isinstance(status_json, dict):
        raise ValueError("status_json must be an object")
    symbols_payload = status_json.get("symbols")
    if not isinstance(symbols_payload, dict) or not symbols_payload:
        raise ValueError("status_json.symbols must be a non-empty object")
    source = _required_str(payload, "source")
    if source not in ALLOWED_MANUAL_MARKET_STATUS_SOURCES:
        allowed = ", ".join(ALLOWED_MANUAL_MARKET_STATUS_SOURCES)
        raise ValueError(f"source must be one of: {allowed}")
    symbol_set_hash = _required_str(payload, "symbol_set_hash")
    expected_symbol_set_hash = compute_symbol_set_hash(symbols_payload.keys())
    if symbol_set_hash != expected_symbol_set_hash:
        raise ValueError(f"symbol_set_hash must match sorted symbols hash: {expected_symbol_set_hash}")
    return MarketStatusSnapshot(
        snapshot_id=_required_str(payload, "snapshot_id"),
        trading_day=_required_str(payload, "trading_day"),
        created_at=_parse_aware_datetime(_required_str(payload, "created_at"), "created_at"),
        source=source,
        symbol_set_hash=symbol_set_hash,
        status_json=status_json,
        stale_after=_parse_aware_datetime(_required_str(payload, "stale_after"), "stale_after"),
    )


def build_market_status_check(
    snapshot: MarketStatusSnapshot,
    *,
    symbols: list[str],
    checked_at: datetime | None = None,
    allowed_sessions: set[str] | None = None,
) -> dict[str, Any]:
    """Build a readiness-compatible market_status check from an explicit snapshot."""

    observed_at = checked_at or datetime.now(timezone.utc)
    normalized_symbols = [symbol.strip() for symbol in symbols if symbol.strip()]
    if not normalized_symbols:
        return {
            "key": "market_status",
            "status": "failed",
            "passed": False,
            "summary": "market status symbol list is empty",
            "details": {
                "checked_at": observed_at.isoformat(),
                "snapshot_id": snapshot.snapshot_id,
                "source": snapshot.source,
                "trading_day": snapshot.trading_day,
            },
        }
    decisions = evaluate_market_status_batch(
        snapshot,
        normalized_symbols,
        now=observed_at,
        allowed_sessions=allowed_sessions,
    )
    blocked_symbols = {
        symbol: list(decision.blocking_reasons)
        for symbol, decision in decisions.items()
        if not decision.allowed
    }
    passed = not blocked_symbols
    return {
        "key": "market_status",
        "status": "ok" if passed else "failed",
        "passed": passed,
        "summary": "market status snapshot allows requested symbols"
        if passed
        else "market status snapshot blocks one or more symbols",
        "details": {
            "checked_at": observed_at.isoformat(),
            "snapshot_id": snapshot.snapshot_id,
            "source": snapshot.source,
            "symbol_set_hash": snapshot.symbol_set_hash,
            "source_generated_at": snapshot.status_json["source_generated_at"],
            "trading_day": snapshot.trading_day,
            "market_session": snapshot.status_json["market_session"],
            "stale_after": snapshot.stale_after.isoformat(),
            "symbol_count": len(normalized_symbols),
            "allowed_count": len(normalized_symbols) - len(blocked_symbols),
            "blocked_symbols": blocked_symbols,
            "allowed_sessions": sorted(allowed_sessions) if allowed_sessions else ["regular"],
        },
    }


def compute_symbol_set_hash(symbols: Any) -> str:
    normalized_symbols = sorted({str(symbol).strip() for symbol in symbols if str(symbol).strip()})
    digest = hashlib.sha256("\n".join(normalized_symbols).encode("utf-8")).hexdigest()[:16]
    return f"symbols-sha256-{digest}"


def failed_market_status_check(
    *,
    summary: str,
    checked_at: datetime | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    observed_at = checked_at or datetime.now(timezone.utc)
    details: dict[str, Any] = {"checked_at": observed_at.isoformat()}
    if error_type:
        details["error_type"] = error_type
    return {
        "key": "market_status",
        "status": "failed",
        "passed": False,
        "summary": summary,
        "details": details,
    }


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _parse_aware_datetime(value: str, label: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include timezone")
    return parsed
