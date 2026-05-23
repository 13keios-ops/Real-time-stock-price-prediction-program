"""Pure live position accounting from recorded live fills.

This module converts already-recorded ``live_fills`` into internal position
snapshots. It does not call a broker, place orders, or update risk gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.storage.contracts import LivePosition


@dataclass(frozen=True, slots=True)
class LivePositionAccountingResult:
    position: LivePosition
    fill_count: int
    over_sell_qty: int
    invalid_side_count: int
    total_commission: float
    total_tax: float
    total_fee: float


def build_live_position_from_fills(
    *,
    symbol: str,
    trading_day: str,
    fills: list[Any],
    last_price: float,
    updated_at: datetime,
    broker_qty: int | None = None,
    source: str = "internal_live_fills",
) -> LivePositionAccountingResult:
    """Build one long-only weighted-average position from live fills.

    The current production strategy is long-only. If sell fills exceed the
    internally held quantity, the excess is recorded in detail_json as
    ``over_sell_qty`` and the computed position is flattened to zero.
    """
    ordered_fills = sorted(fills, key=lambda fill: _fill_time(fill, updated_at))
    qty = 0
    cost_basis = 0.0
    realized_pnl = 0.0
    over_sell_qty = 0
    invalid_side_count = 0
    opened_at: datetime | None = None
    total_commission = 0.0
    total_tax = 0.0
    total_fee = 0.0

    for fill in ordered_fills:
        fill_qty = max(int(_field(fill, "fill_qty", 0) or 0), 0)
        fill_price = max(float(_field(fill, "fill_price", 0.0) or 0.0), 0.0)
        commission = max(float(_field(fill, "commission", 0.0) or 0.0), 0.0)
        tax = max(float(_field(fill, "tax", 0.0) or 0.0), 0.0)
        fee = max(float(_field(fill, "fee", 0.0) or 0.0), 0.0)
        total_costs = commission + tax + fee
        total_commission += commission
        total_tax += tax
        total_fee += fee
        if fill_qty <= 0:
            continue
        side = _normalize_side(_field(fill, "side", ""))
        if side == "buy":
            if qty == 0:
                opened_at = _parse_datetime(_field(fill, "event_time")) or updated_at
            cost_basis += fill_qty * fill_price + total_costs
            qty += fill_qty
        elif side == "sell":
            sell_qty = min(fill_qty, qty)
            over_sell_qty += max(fill_qty - qty, 0)
            if sell_qty <= 0:
                continue
            avg_cost = cost_basis / qty if qty > 0 else 0.0
            allocated_cost = avg_cost * sell_qty
            proportional_costs = total_costs * (sell_qty / fill_qty)
            realized_pnl += sell_qty * fill_price - proportional_costs - allocated_cost
            cost_basis = max(cost_basis - allocated_cost, 0.0)
            qty -= sell_qty
            if qty == 0:
                cost_basis = 0.0
                opened_at = None
        else:
            invalid_side_count += 1

    effective_last_price = max(float(last_price or 0.0), 0.0)
    market_value = qty * effective_last_price
    unrealized_pnl = market_value - cost_basis if qty > 0 else 0.0
    avg_price = cost_basis / qty if qty > 0 else 0.0
    effective_broker_qty = qty if broker_qty is None else int(broker_qty)
    position = LivePosition(
        symbol=symbol,
        trading_day=trading_day,
        opened_at=opened_at,
        updated_at=updated_at,
        qty=qty,
        avg_price=avg_price,
        last_price=effective_last_price,
        market_value=market_value,
        cost_basis=cost_basis,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        day_realized_pnl=realized_pnl,
        broker_qty=effective_broker_qty,
        detail_json={
            "source": source,
            "raw_broker_position": {},
            "accounting": {
                "method": "long_only_weighted_average_from_live_fills",
                "fill_count": len(ordered_fills),
                "over_sell_qty": over_sell_qty,
                "invalid_side_count": invalid_side_count,
                "total_commission": total_commission,
                "total_tax": total_tax,
                "total_fee": total_fee,
                "broker_qty_mismatch": effective_broker_qty != qty,
            },
        },
    )
    return LivePositionAccountingResult(
        position=position,
        fill_count=len(ordered_fills),
        over_sell_qty=over_sell_qty,
        invalid_side_count=invalid_side_count,
        total_commission=total_commission,
        total_tax=total_tax,
        total_fee=total_fee,
    )


def build_live_positions_from_store(
    store: Any,
    *,
    trading_day: str,
    last_prices: dict[str, float],
    updated_at: datetime,
    broker_quantities: dict[str, int] | None = None,
) -> tuple[LivePositionAccountingResult, ...]:
    rows = list(store.fetch_live_fills_for_trading_day(trading_day))
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        symbol = str(_field(row, "symbol", ""))
        if not symbol:
            continue
        grouped.setdefault(symbol, []).append(row)
    return tuple(
        build_live_position_from_fills(
            symbol=symbol,
            trading_day=trading_day,
            fills=fills,
            last_price=float(last_prices.get(symbol, 0.0)),
            updated_at=updated_at,
            broker_qty=(broker_quantities or {}).get(symbol),
            source="sqlite_live_fills",
        )
        for symbol, fills in sorted(grouped.items())
    )


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    try:
        return value[name]
    except (KeyError, IndexError, TypeError):
        return getattr(value, name, default)


def _normalize_side(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"02", "buy", "b"}:
        return "buy"
    if normalized in {"01", "sell", "s"}:
        return "sell"
    return normalized


def _fill_time(fill: Any, fallback: datetime) -> datetime:
    return _parse_datetime(_field(fill, "event_time")) or fallback


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
