"""Read-only live order monitoring helpers.

The helpers in this module do not transition orders or call a broker. They
summarize orders that already need attention so dashboards and reports can
surface them without changing live execution state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.storage.sqlite_store import LIVE_OPEN_ORDER_STATUSES


LIVE_ORDER_ATTENTION_STATUSES = ("unknown", "stuck")
PHASE2_MONITORING_PHASES = ("phase2", "phase2_canary", "phase2_conservative")


@dataclass(frozen=True, slots=True)
class LiveOrderAttention:
    order_id: str
    status: str
    symbol: str
    side: str
    qty: int
    filled_qty: int
    remaining_qty: int
    reference_time: str | None
    age_minutes: float | None


@dataclass(frozen=True, slots=True)
class LiveOrderAttentionSummary:
    trading_day: str
    checked_order_count: int
    open_order_count: int
    attention_count: int
    max_attention_age_minutes: float | None
    attention_orders: tuple[LiveOrderAttention, ...]

    @property
    def ok(self) -> bool:
        return self.attention_count == 0


@dataclass(frozen=True, slots=True)
class LivePhase2ParentOrder:
    order_id: str
    status: str
    phase: str
    symbol: str
    side: str
    qty: int
    created_at: str | None


@dataclass(frozen=True, slots=True)
class LivePhase2ParentOrderLimitSummary:
    trading_day: str
    max_parent_orders_per_day: int
    checked_order_count: int
    parent_order_count: int
    blocked_parent_order_count: int
    remaining_parent_orders: int
    blocked_by_limit: bool
    parent_orders: tuple[LivePhase2ParentOrder, ...]

    @property
    def ok(self) -> bool:
        return not self.blocked_by_limit


def build_live_order_attention_summary_from_store(
    store: Any,
    *,
    trading_day: str,
    now: datetime,
    attention_statuses: tuple[str, ...] = LIVE_ORDER_ATTENTION_STATUSES,
) -> LiveOrderAttentionSummary:
    attention_status_set = {status.strip().lower() for status in attention_statuses}
    open_status_set = {status.strip().lower() for status in LIVE_OPEN_ORDER_STATUSES}
    rows = list(store.fetch_live_orders_for_trading_day(trading_day))
    attention_orders: list[LiveOrderAttention] = []
    open_order_count = 0
    for row in rows:
        status = str(_row_value(row, "status", "")).strip().lower()
        if status in open_status_set:
            open_order_count += 1
        if status not in attention_status_set:
            continue
        reference_time = _first_order_time(row, "last_synced_at", "submitted_at", "created_at")
        attention_orders.append(
            LiveOrderAttention(
                order_id=str(_row_value(row, "order_id", "")),
                status=status,
                symbol=str(_row_value(row, "symbol", "")),
                side=str(_row_value(row, "side", "")),
                qty=int(_row_value(row, "qty", 0) or 0),
                filled_qty=int(_row_value(row, "filled_qty", 0) or 0),
                remaining_qty=int(_row_value(row, "remaining_qty", 0) or 0),
                reference_time=reference_time.isoformat() if reference_time is not None else None,
                age_minutes=_age_minutes(reference_time, now),
            )
        )
    ages = [item.age_minutes for item in attention_orders if item.age_minutes is not None]
    return LiveOrderAttentionSummary(
        trading_day=trading_day,
        checked_order_count=len(rows),
        open_order_count=open_order_count,
        attention_count=len(attention_orders),
        max_attention_age_minutes=max(ages) if ages else None,
        attention_orders=tuple(attention_orders),
    )


def build_live_phase2_parent_order_limit_summary_from_store(
    store: Any,
    *,
    trading_day: str,
    max_parent_orders_per_day: int = 1,
    phase_names: tuple[str, ...] = PHASE2_MONITORING_PHASES,
) -> LivePhase2ParentOrderLimitSummary:
    phase_set = {phase.strip().lower() for phase in phase_names}
    rows = list(store.fetch_live_orders_for_trading_day(trading_day))
    parent_orders: list[LivePhase2ParentOrder] = []
    blocked_parent_order_count = 0
    for row in rows:
        phase = str(_row_value(row, "phase", "")).strip().lower()
        if phase not in phase_set or not _is_parent_order(row):
            continue
        status = str(_row_value(row, "status", "")).strip().lower()
        if status == "blocked":
            blocked_parent_order_count += 1
            continue
        parent_orders.append(
            LivePhase2ParentOrder(
                order_id=str(_row_value(row, "order_id", "")),
                status=status,
                phase=phase,
                symbol=str(_row_value(row, "symbol", "")),
                side=str(_row_value(row, "side", "")),
                qty=int(_row_value(row, "qty", 0) or 0),
                created_at=str(_row_value(row, "created_at", "") or "") or None,
            )
        )
    limit = max(int(max_parent_orders_per_day), 0)
    parent_order_count = len(parent_orders)
    return LivePhase2ParentOrderLimitSummary(
        trading_day=trading_day,
        max_parent_orders_per_day=limit,
        checked_order_count=len(rows),
        parent_order_count=parent_order_count,
        blocked_parent_order_count=blocked_parent_order_count,
        remaining_parent_orders=max(limit - parent_order_count, 0),
        blocked_by_limit=parent_order_count >= limit if limit > 0 else True,
        parent_orders=tuple(parent_orders),
    )


def live_order_attention_summary_to_dict(summary: LiveOrderAttentionSummary) -> dict[str, Any]:
    status = "empty" if summary.checked_order_count == 0 else "ok" if summary.ok else "attention"
    return {
        "status": status,
        "trading_day": summary.trading_day,
        "checked_order_count": summary.checked_order_count,
        "open_order_count": summary.open_order_count,
        "attention_count": summary.attention_count,
        "max_attention_age_minutes": summary.max_attention_age_minutes,
        "attention_orders": [
            {
                "order_id": item.order_id,
                "status": item.status,
                "symbol": item.symbol,
                "side": item.side,
                "qty": item.qty,
                "filled_qty": item.filled_qty,
                "remaining_qty": item.remaining_qty,
                "reference_time": item.reference_time,
                "age_minutes": item.age_minutes,
            }
            for item in summary.attention_orders
        ],
        "error": None,
    }


def live_phase2_parent_order_limit_summary_to_dict(summary: LivePhase2ParentOrderLimitSummary) -> dict[str, Any]:
    status = "empty" if summary.checked_order_count == 0 else "blocked" if summary.blocked_by_limit else "available"
    return {
        "status": status,
        "trading_day": summary.trading_day,
        "max_parent_orders_per_day": summary.max_parent_orders_per_day,
        "checked_order_count": summary.checked_order_count,
        "parent_order_count": summary.parent_order_count,
        "blocked_parent_order_count": summary.blocked_parent_order_count,
        "remaining_parent_orders": summary.remaining_parent_orders,
        "blocked_by_limit": summary.blocked_by_limit,
        "parent_orders": [
            {
                "order_id": item.order_id,
                "status": item.status,
                "phase": item.phase,
                "symbol": item.symbol,
                "side": item.side,
                "qty": item.qty,
                "created_at": item.created_at,
            }
            for item in summary.parent_orders
        ],
        "error": None,
    }


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        if isinstance(row, dict):
            return row.get(key, default)
        return default


def _is_parent_order(row: Any) -> bool:
    parent_order_id = _row_value(row, "parent_order_id")
    return parent_order_id is None or str(parent_order_id) == ""


def _first_order_time(row: Any, *keys: str) -> datetime | None:
    for key in keys:
        parsed = _parse_datetime(_row_value(row, key))
        if parsed is not None:
            return parsed
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _age_minutes(reference_time: datetime | None, now: datetime) -> float | None:
    if reference_time is None:
        return None
    compare_now = now
    compare_reference = reference_time
    if compare_reference.tzinfo is None and compare_now.tzinfo is not None:
        compare_reference = compare_reference.replace(tzinfo=compare_now.tzinfo)
    elif compare_reference.tzinfo is not None and compare_now.tzinfo is None:
        compare_now = compare_now.replace(tzinfo=compare_reference.tzinfo)
    return max(round((compare_now - compare_reference).total_seconds() / 60, 1), 0.0)
