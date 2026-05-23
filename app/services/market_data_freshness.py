"""Pure market-data freshness checks for live order preflight."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MarketDataFreshnessDecision:
    allowed: bool
    blocking_reasons: tuple[str, ...]
    ages_seconds: dict[str, float | None]


def evaluate_market_data_freshness(
    *,
    now: datetime,
    latest_trade_at: datetime | None,
    latest_orderbook_at: datetime | None,
    latest_bar_at: datetime | None,
    latest_prediction_at: datetime | None,
    max_trade_age_seconds: float = 30.0,
    max_orderbook_age_seconds: float = 30.0,
    max_bar_age_seconds: float = 120.0,
    max_prediction_age_seconds: float = 120.0,
    require_trade: bool = True,
    require_orderbook: bool = True,
    require_bar: bool = True,
    require_prediction: bool = True,
    future_tolerance_seconds: float = 2.0,
) -> MarketDataFreshnessDecision:
    reasons: list[str] = []
    ages: dict[str, float | None] = {}
    checks = (
        ("trade_tick", latest_trade_at, max_trade_age_seconds, require_trade),
        ("orderbook_tick", latest_orderbook_at, max_orderbook_age_seconds, require_orderbook),
        ("minute_bar", latest_bar_at, max_bar_age_seconds, require_bar),
        ("prediction", latest_prediction_at, max_prediction_age_seconds, require_prediction),
    )
    for key, observed_at, max_age_seconds, required in checks:
        reason, age_seconds = _freshness_reason(
            key=key,
            now=now,
            observed_at=observed_at,
            max_age_seconds=max_age_seconds,
            required=required,
            future_tolerance_seconds=future_tolerance_seconds,
        )
        ages[key] = age_seconds
        if reason:
            reasons.append(reason)
    return MarketDataFreshnessDecision(
        allowed=not reasons,
        blocking_reasons=tuple(reasons),
        ages_seconds=ages,
    )


def _freshness_reason(
    *,
    key: str,
    now: datetime,
    observed_at: datetime | None,
    max_age_seconds: float,
    required: bool,
    future_tolerance_seconds: float,
) -> tuple[str | None, float | None]:
    if observed_at is None:
        return (f"{key}_missing" if required else None), None
    age_seconds = (now - observed_at).total_seconds()
    if age_seconds < -future_tolerance_seconds:
        return f"{key}_from_future", age_seconds
    if age_seconds > max_age_seconds:
        return f"{key}_stale", age_seconds
    return None, age_seconds
