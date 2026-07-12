"""Shared domestic-stock execution cost assumptions.

The current development universe contains ordinary KOSPI/KOSDAQ shares. For
2026 both markets have a 0.20% total sell-side levy, although the tax
components differ by market. Product-aware ETF/ETN taxation remains outside
this helper and must be added before those products enter the universe.
"""

from __future__ import annotations


DOMESTIC_STOCK_COST_MODEL_VERSION = "krx-common-stock-2026-v1"
DEFAULT_COMMISSION_RATE = 0.00015
DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE = 0.0020


def calculate_domestic_stock_fill_tax(
    *,
    side: str,
    gross_notional: float,
    sell_tax_rate: float = DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE,
) -> float:
    """Return the sell-only levy for an ordinary domestic-stock fill."""
    if str(side).strip().lower() != "sell":
        return 0.0
    return max(float(gross_notional), 0.0) * max(float(sell_tax_rate), 0.0)


def estimate_round_trip_cost_pct(
    *,
    slippage_bps: float,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    sell_tax_rate: float = DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE,
) -> float:
    """Estimate round-trip cost as percentage points of entry notional."""
    return (
        (max(float(slippage_bps), 0.0) * 2.0) / 100.0
        + (max(float(commission_rate), 0.0) * 2.0 * 100.0)
        + (max(float(sell_tax_rate), 0.0) * 100.0)
    )
