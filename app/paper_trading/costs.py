"""Shared domestic-stock execution cost assumptions.

The current development universe contains ordinary KOSPI/KOSDAQ shares. For
2026 both markets have a 0.20% total sell-side levy, although the tax
components differ by market. Product-aware ETF/ETN taxation remains outside
this helper and must be added before those products enter the universe.

The 0.015% per-side commission and default 3bp per-side slippage are research
assumptions, not a broker fee statement or observed fill calibration. Compare
both against Phase 2 canary fills before using them as live execution evidence.
"""

from __future__ import annotations

import math


DOMESTIC_STOCK_COST_MODEL_VERSION = "krx-common-stock-2026-v1"
DEFAULT_COMMISSION_RATE = 0.00015
DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE = 0.0020
DEFAULT_RESEARCH_SLIPPAGE_BPS = 3.0
LEGACY_OR_CUSTOM_COST_MODEL_VERSION = "legacy_or_custom_unversioned"


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


def build_domestic_stock_cost_model_metadata(
    *,
    slippage_bps: float = DEFAULT_RESEARCH_SLIPPAGE_BPS,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    sell_tax_rate: float = DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE,
    round_trip_cost_pct: float | None = None,
) -> dict[str, object]:
    """Describe current assumptions and classify custom or legacy totals."""
    expected_round_trip_cost_pct = round(
        estimate_round_trip_cost_pct(
            slippage_bps=slippage_bps,
            commission_rate=commission_rate,
            sell_tax_rate=sell_tax_rate,
        ),
        12,
    )
    effective_round_trip_cost_pct = (
        expected_round_trip_cost_pct
        if round_trip_cost_pct is None
        else round(max(float(round_trip_cost_pct), 0.0), 12)
    )
    matches_current_assumptions = all(
        (
            math.isclose(
                float(slippage_bps),
                DEFAULT_RESEARCH_SLIPPAGE_BPS,
                rel_tol=0.0,
                abs_tol=1e-9,
            ),
            math.isclose(
                float(commission_rate),
                DEFAULT_COMMISSION_RATE,
                rel_tol=0.0,
                abs_tol=1e-12,
            ),
            math.isclose(
                float(sell_tax_rate),
                DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE,
                rel_tol=0.0,
                abs_tol=1e-12,
            ),
        )
    )
    matches_current_model = matches_current_assumptions and math.isclose(
        effective_round_trip_cost_pct,
        expected_round_trip_cost_pct,
        rel_tol=0.0,
        abs_tol=1e-9,
    )
    return {
        "version": (
            DOMESTIC_STOCK_COST_MODEL_VERSION
            if matches_current_model
            else LEGACY_OR_CUSTOM_COST_MODEL_VERSION
        ),
        "scope": "ordinary_kospi_kosdaq_shares_2026",
        "round_trip_cost_pct": effective_round_trip_cost_pct,
        "matches_current_model": matches_current_model,
        "matches_current_assumptions": matches_current_assumptions,
        "commission_rate_per_side": commission_rate,
        "commission_rate_status": "research_assumption_not_broker_statement",
        "sell_tax_rate": sell_tax_rate,
        "sell_tax_rate_status": "2026_statutory_total_for_current_common_stock_universe",
        "slippage_bps_per_side": slippage_bps,
        "slippage_status": "research_assumption_not_observed_fill_calibration",
        "requires_phase2_canary_validation": True,
    }
