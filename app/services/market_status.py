"""Pure market-status decisions for live-order preflight checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.storage.contracts import MarketStatusSnapshot


DEFAULT_ALLOWED_SESSIONS = {"regular"}


@dataclass(frozen=True, slots=True)
class MarketStatusDecision:
    snapshot_id: str
    trading_day: str
    symbol: str
    allowed: bool
    blocking_reasons: tuple[str, ...]
    market_session: str
    stale: bool
    source: str
    source_generated_at: str
    symbol_status: dict[str, Any]


def evaluate_market_status(
    snapshot: MarketStatusSnapshot,
    symbol: str,
    *,
    now: datetime,
    allowed_sessions: set[str] | None = None,
) -> MarketStatusDecision:
    """Evaluate whether a symbol is tradable under a market-status snapshot."""

    normalized_symbol = symbol.strip()
    status_json = snapshot.status_json
    symbols = status_json["symbols"]
    source_generated_at = str(status_json["source_generated_at"])
    symbol_status = symbols.get(normalized_symbol)
    blocking_reasons: list[str] = []
    allowed_session_set = DEFAULT_ALLOWED_SESSIONS if allowed_sessions is None else allowed_sessions
    stale = now > snapshot.stale_after

    market_session = str(status_json["market_session"]).strip()
    if isinstance(symbol_status, dict) and "market_session" in symbol_status:
        market_session = str(symbol_status["market_session"]).strip()

    if stale:
        blocking_reasons.append("market_status_stale")
    if market_session not in allowed_session_set:
        blocking_reasons.append("market_session_not_allowed")

    if not isinstance(symbol_status, dict):
        blocking_reasons.append("symbol_status_missing")
        symbol_status = {}
    else:
        blocking_reasons.extend(_symbol_blocking_reasons(symbol_status))

    return MarketStatusDecision(
        snapshot_id=snapshot.snapshot_id,
        trading_day=snapshot.trading_day,
        symbol=normalized_symbol,
        allowed=not blocking_reasons,
        blocking_reasons=tuple(blocking_reasons),
        market_session=market_session,
        stale=stale,
        source=snapshot.source,
        source_generated_at=source_generated_at,
        symbol_status=dict(symbol_status),
    )


def evaluate_market_status_batch(
    snapshot: MarketStatusSnapshot,
    symbols: list[str],
    *,
    now: datetime,
    allowed_sessions: set[str] | None = None,
) -> dict[str, MarketStatusDecision]:
    return {
        symbol: evaluate_market_status(snapshot, symbol, now=now, allowed_sessions=allowed_sessions)
        for symbol in symbols
    }


def _symbol_blocking_reasons(symbol_status: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    tradable = symbol_status.get("tradable")
    if tradable is not True:
        reasons.append("tradable_unknown" if tradable is None else "not_tradable")
    if _flag(symbol_status, "suspended", "trading_suspended", "halted"):
        reasons.append("trading_suspended")
    if _flag(symbol_status, "management", "management_issue"):
        reasons.append("management_issue")
    if _flag(symbol_status, "investment_warning", "investment_caution"):
        reasons.append("investment_warning")
    if _flag(symbol_status, "upper_limit", "lower_limit", "near_price_limit"):
        reasons.append("price_limit_blocked")
    if _flag(symbol_status, "vi_active", "volatility_interruption"):
        reasons.append("vi_active")
    if _flag(symbol_status, "single_price_auction", "call_auction"):
        reasons.append("single_price_auction")
    if _flag(symbol_status, "corporate_action", "corporate_action_pending"):
        reasons.append("corporate_action")
    return reasons


def _flag(values: dict[str, Any], *keys: str) -> bool:
    return any(_as_bool(values.get(key)) for key in keys)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False
