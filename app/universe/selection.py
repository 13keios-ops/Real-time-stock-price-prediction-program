"""Universe selection helpers for the baseline top-liquidity universe."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class UniverseCandidate:
    symbol: str
    name: str
    median_trading_value: float
    market: str
    tradable: bool = True


def select_top_liquidity_universe(candidates: list[UniverseCandidate], limit: int = 30) -> list[UniverseCandidate]:
    tradable = [candidate for candidate in candidates if candidate.tradable]
    ordered = sorted(tradable, key=lambda item: item.median_trading_value, reverse=True)
    return ordered[:limit]
