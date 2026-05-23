"""Pure mappers and narrow DB applicator for live broker execution sync.

This module updates live order status and records cumulative-fill deltas only.
Position, portfolio, tax, and settlement accounting are intentionally handled by
later slices so Phase 2 cannot mistake order sync for complete live accounting.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.brokers.kis_response_redaction import redact_kis_payload
from app.services.live_order_manager import ALLOWED_TRANSITIONS, LiveOrderTransitionError
from app.storage.contracts import LiveFill, LiveOrderEvent
from app.storage.runtime_writer import RuntimeWriter


LIVE_FINAL_ORDER_STATUSES = {"filled", "cancelled", "cancelled_partial", "expired", "rejected"}
LIVE_INFLIGHT_ORDER_STATUSES = {"accepted", "open", "partially_filled", "unknown", "stuck", "cancel_requested"}


@dataclass(frozen=True, slots=True)
class LiveBrokerOrderSnapshot:
    matched: bool
    order_date: str
    broker_branch_no: str
    broker_order_no: str
    symbol: str
    side: str
    order_qty: int
    filled_qty: int
    remaining_qty: int
    avg_fill_price: float
    reject_qty: int
    cancel_confirm_qty: int
    cancel_yn: bool
    expired: bool = False
    raw_output: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LiveOrderSyncDecision:
    status: str
    matched: bool
    filled_qty: int
    remaining_qty: int
    avg_fill_price: float
    delta_fill_qty: int
    applied_fill_qty: int
    broker_order_no: str
    broker_branch_no: str
    raw_output: dict[str, Any]

    @property
    def final(self) -> bool:
        return self.status in LIVE_FINAL_ORDER_STATUSES

    @property
    def inflight(self) -> bool:
        return self.status in LIVE_INFLIGHT_ORDER_STATUSES


@dataclass(frozen=True, slots=True)
class LiveFillApplyResult:
    decision: LiveOrderSyncDecision
    fill_id: str
    fill_inserted: bool
    delta_fill_qty: int
    order_filled_qty: int
    live_fill_qty_sum: int
    consistent: bool


@dataclass(frozen=True, slots=True)
class LiveFillConsistency:
    order_id: str
    order_filled_qty: int
    live_fill_qty_sum: int
    consistent: bool


@dataclass(frozen=True, slots=True)
class LiveFillConsistencySummary:
    trading_day: str
    checked_order_count: int
    mismatch_count: int
    mismatches: tuple[LiveFillConsistency, ...]

    @property
    def ok(self) -> bool:
        return self.mismatch_count == 0


def snapshot_from_kis_daily_order_fill(record: Any, *, matched: bool = True) -> LiveBrokerOrderSnapshot:
    raw_output = _as_dict(_field(record, "raw_output", {}))
    expired = _flag(raw_output, "expired", "expire_yn", "ord_expired", "order_expired")
    return LiveBrokerOrderSnapshot(
        matched=matched,
        order_date=str(_field(record, "order_date", "")),
        broker_branch_no=str(_field(record, "broker_branch_no", "")),
        broker_order_no=str(_field(record, "broker_order_no", "")),
        symbol=str(_field(record, "symbol", "")),
        side=_to_side_text(str(_field(record, "side", ""))),
        order_qty=max(int(_field(record, "order_qty", 0) or 0), 0),
        filled_qty=max(int(_field(record, "filled_qty", 0) or 0), 0),
        remaining_qty=max(int(_field(record, "remaining_qty", 0) or 0), 0),
        avg_fill_price=max(float(_field(record, "avg_fill_price", 0.0) or 0.0), 0.0),
        reject_qty=max(int(_field(record, "reject_qty", 0) or 0), 0),
        cancel_confirm_qty=max(int(_field(record, "cancel_confirm_qty", 0) or 0), 0),
        cancel_yn=bool(_field(record, "cancel_yn", False)),
        expired=expired,
        raw_output=raw_output,
    )


def derive_live_order_status(snapshot: LiveBrokerOrderSnapshot) -> str:
    if not snapshot.matched:
        return "unknown"
    if snapshot.expired:
        return "expired"
    if snapshot.reject_qty >= max(snapshot.order_qty, 1):
        return "rejected"
    if snapshot.cancel_yn and snapshot.filled_qty > 0:
        return "cancelled_partial"
    if snapshot.cancel_yn or snapshot.cancel_confirm_qty > 0:
        return "cancelled"
    if snapshot.order_qty > 0 and snapshot.filled_qty >= snapshot.order_qty:
        return "filled"
    if snapshot.filled_qty > 0:
        return "partially_filled"
    if snapshot.remaining_qty > 0:
        return "open"
    return "accepted"


def build_live_order_sync_decision(
    snapshot: LiveBrokerOrderSnapshot,
    *,
    previous_applied_fill_qty: int = 0,
) -> LiveOrderSyncDecision:
    applied_before = max(int(previous_applied_fill_qty or 0), 0)
    delta_fill_qty = max(snapshot.filled_qty - applied_before, 0)
    return LiveOrderSyncDecision(
        status=derive_live_order_status(snapshot),
        matched=snapshot.matched,
        filled_qty=snapshot.filled_qty,
        remaining_qty=snapshot.remaining_qty,
        avg_fill_price=snapshot.avg_fill_price,
        delta_fill_qty=delta_fill_qty,
        applied_fill_qty=applied_before + delta_fill_qty,
        broker_order_no=snapshot.broker_order_no,
        broker_branch_no=snapshot.broker_branch_no,
        raw_output=snapshot.raw_output,
    )


class LiveExecutionSync:
    def __init__(self, writer: RuntimeWriter) -> None:
        if writer.sqlite_store is None:
            raise ValueError("LiveExecutionSync requires a SQLiteRuntimeStore")
        self.writer = writer
        self.store = writer.sqlite_store

    def apply_order_snapshot(
        self,
        *,
        order_id: str,
        snapshot: LiveBrokerOrderSnapshot,
        synced_at: datetime,
        previous_applied_fill_qty: int = 0,
    ) -> LiveOrderSyncDecision:
        decision = build_live_order_sync_decision(
            snapshot,
            previous_applied_fill_qty=previous_applied_fill_qty,
        )
        row = self.store.fetch_live_order(order_id)
        if row is None:
            raise KeyError(f"live order not found: {order_id}")
        if _row_synced_to_decision(row, decision):
            return decision
        path = _transition_path(str(row["status"]), decision.status)
        current_row = row
        for index, to_status in enumerate(path):
            final_step = index == len(path) - 1
            current_row = self._apply_status(
                current_row,
                to_status,
                synced_at=synced_at,
                decision=decision,
                update_quantities=final_step and decision.matched,
            )
        return decision

    def apply_order_snapshot_and_fill_delta(
        self,
        *,
        order_id: str,
        snapshot: LiveBrokerOrderSnapshot,
        synced_at: datetime,
        settlement_day: str,
        commission: float = 0.0,
        tax: float = 0.0,
        fee: float = 0.0,
    ) -> LiveFillApplyResult:
        """Apply order status and insert only the unrecorded live fill delta.

        The broker snapshot is cumulative. This method compares the broker's
        cumulative filled quantity against existing ``live_fills`` for the order,
        inserts at most one deterministic delta fill, and never updates positions
        or portfolio snapshots.
        """
        previous_fill_qty, previous_notional = self.store.fetch_live_fill_totals(order_id)
        decision = self.apply_order_snapshot(
            order_id=order_id,
            snapshot=snapshot,
            synced_at=synced_at,
            previous_applied_fill_qty=previous_fill_qty,
        )
        fill_id = ""
        fill_inserted = False
        if decision.matched and decision.delta_fill_qty > 0:
            row = self.store.fetch_live_order(order_id)
            if row is None:
                raise KeyError(f"live order not found after sync: {order_id}")
            fill_id = _live_fill_id(order_id, decision)
            fill = LiveFill(
                fill_id=fill_id,
                order_id=order_id,
                broker_order_no=decision.broker_order_no,
                broker_branch_no=decision.broker_branch_no,
                symbol=str(row["symbol"]),
                trading_day=str(row["trading_day"]),
                event_time=synced_at,
                side=str(row["side"]),
                fill_qty=decision.delta_fill_qty,
                fill_price=_derive_delta_fill_price(decision, previous_notional),
                commission=max(float(commission or 0.0), 0.0),
                tax=max(float(tax or 0.0), 0.0),
                fee=max(float(fee or 0.0), 0.0),
                settlement_day=settlement_day,
                detail_json={
                    "raw_broker_fill": _redacted_broker_payload(decision.raw_output),
                    "fees": {
                        "commission": max(float(commission or 0.0), 0.0),
                        "tax": max(float(tax or 0.0), 0.0),
                        "fee": max(float(fee or 0.0), 0.0),
                        "source": "caller_supplied_or_zero",
                    },
                    "settlement": {
                        "settlement_day": settlement_day,
                        "source": "caller_supplied",
                    },
                    "sync": {
                        "previous_fill_qty": previous_fill_qty,
                        "broker_filled_qty": decision.filled_qty,
                        "delta_fill_qty": decision.delta_fill_qty,
                        "broker_avg_fill_price": decision.avg_fill_price,
                        "previous_notional": previous_notional,
                        "delta_price_method": "cumulative_avg_minus_internal_notional",
                    },
                },
            )
            fill_inserted = self.writer.write_live_fill_if_absent(fill)
        consistency = self.validate_live_order_fill_qty(order_id)
        return LiveFillApplyResult(
            decision=decision,
            fill_id=fill_id,
            fill_inserted=fill_inserted,
            delta_fill_qty=decision.delta_fill_qty,
            order_filled_qty=consistency.order_filled_qty,
            live_fill_qty_sum=consistency.live_fill_qty_sum,
            consistent=consistency.consistent,
        )

    def validate_live_order_fill_qty(self, order_id: str) -> LiveFillConsistency:
        row = self.store.fetch_live_order(order_id)
        if row is None:
            raise KeyError(f"live order not found: {order_id}")
        live_fill_qty_sum = self.store.sum_live_fill_qty(order_id)
        order_filled_qty = int(row["filled_qty"] or 0)
        return LiveFillConsistency(
            order_id=order_id,
            order_filled_qty=order_filled_qty,
            live_fill_qty_sum=live_fill_qty_sum,
            consistent=order_filled_qty == live_fill_qty_sum,
        )

    def scan_live_order_fill_consistency(
        self,
        *,
        trading_day: str,
        include_consistent: bool = False,
    ) -> list[LiveFillConsistency]:
        results: list[LiveFillConsistency] = []
        for row in self.store.fetch_live_orders_for_trading_day(trading_day):
            consistency = self.validate_live_order_fill_qty(str(row["order_id"]))
            if include_consistent or not consistency.consistent:
                results.append(consistency)
        return results

    def build_live_order_fill_consistency_summary(self, *, trading_day: str) -> LiveFillConsistencySummary:
        return build_live_order_fill_consistency_summary_from_store(self.store, trading_day=trading_day)

    def _apply_status(
        self,
        row: Any,
        to_status: str,
        *,
        synced_at: datetime,
        decision: LiveOrderSyncDecision,
        update_quantities: bool,
    ) -> Any:
        from_status = str(row["status"])
        detail_json = _row_detail(row)
        detail_json["raw_broker_response"] = _redacted_broker_payload(decision.raw_output)
        self.store.update_live_order_transition(
            order_id=str(row["order_id"]),
            status=to_status,
            filled_qty=decision.filled_qty if update_quantities else None,
            remaining_qty=decision.remaining_qty if update_quantities else None,
            avg_fill_price=decision.avg_fill_price if update_quantities else None,
            broker_order_no=decision.broker_order_no or str(row["broker_order_no"]),
            broker_branch_no=decision.broker_branch_no or str(row["broker_branch_no"]),
            reject_reason="broker_rejected" if to_status == "rejected" else row["reject_reason"],
            cancel_reason=row["cancel_reason"],
            submitted_at=_parse_datetime(row["submitted_at"]),
            last_synced_at=synced_at,
            detail_json=detail_json,
        )
        self.writer.write_live_order_event(
            LiveOrderEvent(
                order_event_id=f"live-order-event-{_short_hash('|'.join([str(row['order_id']), synced_at.isoformat(), from_status, to_status, 'live_execution_sync']))}",
                order_id=str(row["order_id"]),
                event_time=synced_at,
                from_status=from_status,
                to_status=to_status,
                event_type="live_execution_sync",
                actor="system",
                detail_json={
                    "reason": f"broker_status={decision.status};delta_fill_qty={decision.delta_fill_qty}",
                    "source": "live_execution_sync",
                    "raw_broker_response": _redacted_broker_payload(decision.raw_output),
                },
            )
        )
        refreshed = self.store.fetch_live_order(str(row["order_id"]))
        if refreshed is None:
            raise KeyError(f"live order not found after update: {row['order_id']}")
        return refreshed


def build_live_order_fill_consistency_summary_from_store(store: Any, *, trading_day: str) -> LiveFillConsistencySummary:
    all_results: list[LiveFillConsistency] = []
    for row in store.fetch_live_orders_for_trading_day(trading_day):
        order_id = str(row["order_id"])
        live_fill_qty_sum = store.sum_live_fill_qty(order_id)
        order_filled_qty = int(row["filled_qty"] or 0)
        all_results.append(
            LiveFillConsistency(
                order_id=order_id,
                order_filled_qty=order_filled_qty,
                live_fill_qty_sum=live_fill_qty_sum,
                consistent=order_filled_qty == live_fill_qty_sum,
            )
        )
    mismatches = tuple(item for item in all_results if not item.consistent)
    return LiveFillConsistencySummary(
        trading_day=trading_day,
        checked_order_count=len(all_results),
        mismatch_count=len(mismatches),
        mismatches=mismatches,
    )


def _transition_path(from_status: str, to_status: str) -> list[str]:
    if from_status == to_status:
        return [to_status]
    direct = ALLOWED_TRANSITIONS.get(from_status)
    if direct is None:
        raise LiveOrderTransitionError(f"unknown live order status: {from_status}")
    if to_status in direct:
        return [to_status]
    candidates = (
        ["submitted", "accepted", to_status],
        ["accepted", to_status],
        ["open", to_status],
    )
    for candidate in candidates:
        current = from_status
        path: list[str] = []
        valid = True
        for next_status in candidate:
            if next_status == current:
                continue
            allowed = ALLOWED_TRANSITIONS.get(current, set())
            if next_status not in allowed:
                valid = False
                break
            path.append(next_status)
            current = next_status
        if valid and path and path[-1] == to_status:
            return path
    raise LiveOrderTransitionError(f"live order transition not allowed: {from_status} -> {to_status}")


def _field(record: Any, name: str, default: Any) -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _to_side_text(side_code: str) -> str:
    normalized = str(side_code or "").strip().lower()
    if normalized in {"02", "buy", "b"}:
        return "buy"
    if normalized in {"01", "sell", "s"}:
        return "sell"
    return normalized


def _flag(values: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = values.get(key)
        if isinstance(value, bool):
            if value:
                return True
        elif isinstance(value, int):
            if value == 1:
                return True
        elif isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "y", "on"}:
            return True
    return False


def _row_detail(row: Any) -> dict[str, Any]:
    value = row["detail_json"]
    if isinstance(value, dict):
        payload = dict(value)
    else:
        try:
            payload = json.loads(value or "{}")
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("order_policy", {})
    payload.setdefault("blocking_reasons", [])
    payload.setdefault("raw_broker_response", {})
    return payload


def _row_synced_to_decision(row: Any, decision: LiveOrderSyncDecision) -> bool:
    broker_order_no = decision.broker_order_no or str(row["broker_order_no"])
    broker_branch_no = decision.broker_branch_no or str(row["broker_branch_no"])
    return (
        str(row["status"]) == decision.status
        and int(row["filled_qty"] or 0) == decision.filled_qty
        and int(row["remaining_qty"] or 0) == decision.remaining_qty
        and abs(float(row["avg_fill_price"] or 0.0) - decision.avg_fill_price) < 0.000001
        and str(row["broker_order_no"]) == broker_order_no
        and str(row["broker_branch_no"]) == broker_branch_no
    )


def _derive_delta_fill_price(decision: LiveOrderSyncDecision, previous_notional: float) -> float:
    if decision.delta_fill_qty <= 0:
        return 0.0
    cumulative_notional = max(decision.filled_qty * decision.avg_fill_price, 0.0)
    delta_notional = cumulative_notional - max(float(previous_notional or 0.0), 0.0)
    if delta_notional <= 0 and decision.avg_fill_price > 0:
        return decision.avg_fill_price
    return max(delta_notional / decision.delta_fill_qty, 0.0)


def _live_fill_id(order_id: str, decision: LiveOrderSyncDecision) -> str:
    return "live-fill-" + _short_hash(
        "|".join(
            [
                order_id,
                decision.broker_branch_no,
                decision.broker_order_no,
                str(decision.applied_fill_qty),
                str(decision.delta_fill_qty),
            ]
        )
    )


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _redacted_broker_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = redact_kis_payload(payload or {})
    return redacted if isinstance(redacted, dict) else {}
