"""Live order manager for intent, submit, cancel, and recovery transitions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.brokers.kis_response_redaction import redact_kis_payload
from app.services.live_kill_switch import LiveKillSwitchState
from app.services.live_order_guard import LiveOrderGuard, LiveOrderGuardError
from app.services.market_status import MarketStatusDecision
from app.services.system_clock import ClockSkewDecision
from app.storage.contracts import LiveOrder, LiveOrderEvent
from app.storage.runtime_writer import RuntimeWriter


TERMINAL_STATUSES = {"blocked", "filled", "cancelled", "cancelled_partial", "expired", "rejected"}
PHASE2_PRE_SUBMIT_PHASES = {"phase2", "phase2_canary", "phase2_conservative"}
PHASE2_DEFAULT_MAX_ORDER_NOTIONAL = 100_000.0
PHASE2_DEFAULT_MAX_ORDER_ALLOCATION_PCT = 0.10
PHASE2_DEFAULT_MAX_ORDER_QTY = 1
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "intent_created": {"blocked", "submit_pending", "unknown"},
    "blocked": set(),
    "submit_pending": {"submitted", "rejected", "unknown"},
    "submitted": {"accepted", "open", "rejected", "unknown"},
    "accepted": {"open", "partially_filled", "filled", "cancel_requested", "rejected", "unknown"},
    "open": {"partially_filled", "filled", "cancel_requested", "stuck", "unknown"},
    "partially_filled": {"filled", "cancel_requested", "cancelled_partial", "stuck", "unknown"},
    "filled": set(),
    "cancel_requested": {"cancelled", "cancelled_partial", "filled", "unknown"},
    "cancelled": set(),
    "cancelled_partial": set(),
    "expired": set(),
    "rejected": set(),
    "stuck": {"cancel_requested", "unknown", "filled"},
    "unknown": {"accepted", "open", "filled", "cancelled", "expired", "rejected", "stuck"},
}
RECOVERY_TO_UNKNOWN_STATUSES = {
    "submit_pending",
    "submitted",
    "accepted",
    "open",
    "partially_filled",
    "cancel_requested",
}


@dataclass(frozen=True, slots=True)
class LiveOrderIntentRequest:
    trading_day: str
    phase: str
    symbol: str
    side: str
    qty: int
    order_type: str
    limit_price: float
    prediction_id: str
    signal_id: str
    target_id: str
    gate_decision_id: str
    market_status_snapshot_id: str
    model_version: str
    rule_version: str
    created_at: datetime
    parent_order_id: str | None = None
    order_policy: dict[str, Any] = field(default_factory=dict)
    extra_detail: dict[str, Any] = field(default_factory=dict)
    order_id: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class BrokerSubmitResult:
    accepted: bool
    status: str
    broker_order_no: str = ""
    broker_branch_no: str = ""
    reject_reason: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrokerCancelResult:
    accepted: bool
    status: str = "cancel_requested"
    cancel_reason: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LiveOrderManagerResult:
    order_id: str
    status: str
    created: bool = False
    transitioned: bool = False
    broker_order_no: str = ""
    blocking_reasons: tuple[str, ...] = ()
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LivePreSubmitPolicy:
    max_parent_orders_per_day: int | None = None
    block_same_symbol_pending: bool = False
    block_live_fill_mismatch: bool = False
    max_order_qty: int | None = None
    max_order_notional: float | None = None
    allocation_amount: float | None = None
    max_order_allocation_pct: float | None = None


@dataclass(frozen=True, slots=True)
class LivePreSubmitCheck:
    blocking_reasons: tuple[str, ...]
    context: dict[str, Any]


class LiveSubmitBroker(Protocol):
    def submit_cash_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: int,
        order_type: str,
        limit_price: float,
        idempotency_key: str,
    ) -> BrokerSubmitResult | dict[str, Any]:
        ...


class LiveCancelBroker(Protocol):
    def cancel_order(
        self,
        *,
        broker_order_no: str,
        broker_branch_no: str,
        reason: str,
    ) -> BrokerCancelResult | dict[str, Any]:
        ...


class LiveOrderTransitionError(RuntimeError):
    pass


class LiveOrderManager:
    def __init__(self, writer: RuntimeWriter) -> None:
        if writer.sqlite_store is None:
            raise ValueError("LiveOrderManager requires a SQLiteRuntimeStore")
        self.writer = writer
        self.store = writer.sqlite_store

    def create_intent(self, request: LiveOrderIntentRequest) -> LiveOrderManagerResult:
        """Create one idempotent live order intent for a prediction/signal pair.

        A guard-blocked order is terminal. Reusing the same idempotency key returns
        that blocked order; retrying after the blocking reason clears requires a
        fresh prediction_id or signal_id so silent resubmission cannot occur.
        """
        _validate_intent_request(request)
        idempotency_key = request.idempotency_key or _idempotency_key(request)
        existing = self.store.fetch_live_order_by_idempotency_key(idempotency_key)
        if existing is not None:
            return LiveOrderManagerResult(
                order_id=str(existing["order_id"]),
                status=str(existing["status"]),
                created=False,
                broker_order_no=str(existing["broker_order_no"]),
            )

        pre_submit_check = self._pre_submit_check(request, idempotency_key)
        blocking_reasons = pre_submit_check.blocking_reasons
        order_id = request.order_id or f"live-order-{_short_hash(idempotency_key)}"
        detail_json = {
            "order_policy": request.order_policy or {"order_type": request.order_type},
            "blocking_reasons": [],
            "pre_submit_policy_context": pre_submit_check.context,
            "raw_broker_response": {},
            "extra_detail": request.extra_detail,
        }
        order = LiveOrder(
            order_id=order_id,
            idempotency_key=idempotency_key,
            trading_day=request.trading_day,
            phase=request.phase,
            symbol=request.symbol,
            side=request.side,
            qty=request.qty,
            filled_qty=0,
            remaining_qty=request.qty,
            order_type=request.order_type,
            limit_price=request.limit_price,
            avg_fill_price=0.0,
            status="intent_created",
            prediction_id=request.prediction_id,
            signal_id=request.signal_id,
            target_id=request.target_id,
            gate_decision_id=request.gate_decision_id,
            market_status_snapshot_id=request.market_status_snapshot_id,
            model_version=request.model_version,
            rule_version=request.rule_version,
            broker_order_no="",
            broker_branch_no="",
            reject_reason=None,
            cancel_reason=None,
            parent_order_id=request.parent_order_id,
            created_at=request.created_at,
            submitted_at=None,
            last_synced_at=None,
            detail_json=detail_json,
        )
        self.writer.write_live_order(order)
        self._write_event(
            order_id=order_id,
            event_time=request.created_at,
            from_status="none",
            to_status="intent_created",
            event_type="intent_created",
            actor="system",
            reason="live_order_intent_created",
            raw_broker_response={},
        )
        if blocking_reasons:
            updated = self._transition(
                self._require_order(order_id),
                "blocked",
                event_type="pre_submit_policy_blocked",
                actor="system",
                event_time=request.created_at,
                reason=",".join(blocking_reasons),
                reject_reason="pre_submit_policy_blocked",
                blocking_reasons=blocking_reasons,
                blocking_context=pre_submit_check.context,
            )
            return LiveOrderManagerResult(
                order_id=order_id,
                status=str(updated["status"]),
                created=True,
                transitioned=True,
                blocking_reasons=blocking_reasons,
            )
        return LiveOrderManagerResult(order_id=order_id, status="intent_created", created=True)

    def submit_intent(
        self,
        *,
        order_id: str,
        settings: Any,
        profile_mode: str,
        kill_switch_state: LiveKillSwitchState | None,
        market_status_decision: MarketStatusDecision | None,
        phase_approved: bool,
        broker: LiveSubmitBroker,
        submitted_at: datetime,
        clock_skew_decision: ClockSkewDecision | None = None,
        require_clock_skew_check: bool = False,
        ws_recovery_evidence_type: str | None = None,
        require_real_ws_recovery_evidence: bool | None = None,
    ) -> LiveOrderManagerResult:
        row = self._require_order(order_id)
        try:
            LiveOrderGuard.assert_can_submit(
                settings,
                str(row["phase"]),
                profile_mode,
                kill_switch_state,
                market_status_decision=market_status_decision,
                phase_approved=phase_approved,
                order_type=str(row["order_type"]),
                clock_skew_decision=clock_skew_decision,
                require_clock_skew_check=require_clock_skew_check,
                ws_recovery_evidence_type=ws_recovery_evidence_type,
                require_real_ws_recovery_evidence=require_real_ws_recovery_evidence,
            )
        except LiveOrderGuardError as exc:
            self._transition(
                row,
                "blocked",
                event_type="submit_blocked",
                actor="system",
                event_time=submitted_at,
                reason=",".join(exc.blocking_reasons),
                reject_reason="guard_blocked",
                blocking_reasons=exc.blocking_reasons,
            )
            return LiveOrderManagerResult(
                order_id=order_id,
                status="blocked",
                transitioned=True,
                blocking_reasons=exc.blocking_reasons,
            )

        pending = self._transition(
            row,
            "submit_pending",
            event_type="submit_pending",
            actor="system",
            event_time=submitted_at,
            reason="live_order_guard_passed",
        )
        try:
            raw_result = broker.submit_cash_order(
                symbol=str(pending["symbol"]),
                side=str(pending["side"]),
                qty=int(pending["qty"]),
                order_type=str(pending["order_type"]),
                limit_price=float(pending["limit_price"]),
                idempotency_key=str(pending["idempotency_key"]),
            )
        except Exception as exc:
            updated = self._transition(
                self._require_order(order_id),
                "unknown",
                event_type="submit_unknown",
                actor="system",
                event_time=submitted_at,
                reason="broker_submit_exception",
                raw_broker_response={"error": str(exc)},
                last_synced_at=submitted_at,
            )
            return LiveOrderManagerResult(order_id=order_id, status=str(updated["status"]), transitioned=True)

        result = _normalize_submit_result(raw_result)
        target_status = _submit_target_status(result)
        next_status = "submitted" if target_status in {"accepted", "open"} else target_status
        updated = self._transition(
            self._require_order(order_id),
            next_status,
            event_type=f"submit_{next_status}",
            actor="system",
            event_time=submitted_at,
            reason=result.reject_reason or "broker_submit_response",
            broker_order_no=result.broker_order_no,
            broker_branch_no=result.broker_branch_no,
            reject_reason=result.reject_reason if target_status == "rejected" else None,
            raw_broker_response=result.raw_response,
            submitted_at=submitted_at,
            last_synced_at=submitted_at,
        )
        if target_status in {"accepted", "open"}:
            updated = self._transition(
                updated,
                target_status,
                event_type=f"broker_{target_status}",
                actor="system",
                event_time=submitted_at,
                reason="broker_submit_response_implied_status",
                raw_broker_response=result.raw_response,
                submitted_at=submitted_at,
                last_synced_at=submitted_at,
            )
        return LiveOrderManagerResult(
            order_id=order_id,
            status=str(updated["status"]),
            transitioned=True,
            broker_order_no=str(updated["broker_order_no"]),
            raw_response=_redacted_broker_payload(result.raw_response),
        )

    def request_cancel(
        self,
        *,
        order_id: str,
        settings: Any,
        profile_mode: str,
        kill_switch_state: LiveKillSwitchState | None,
        broker: LiveCancelBroker,
        requested_at: datetime,
        reason: str,
    ) -> LiveOrderManagerResult:
        row = self._require_order(order_id)
        LiveOrderGuard.assert_can_cancel(settings, str(row["phase"]), profile_mode, kill_switch_state)
        if not str(row["broker_order_no"]):
            updated = self._transition(
                row,
                "unknown",
                event_type="cancel_unknown",
                actor="system",
                event_time=requested_at,
                reason="broker_order_no_missing",
                cancel_reason=reason,
                last_synced_at=requested_at,
            )
            return LiveOrderManagerResult(order_id=order_id, status=str(updated["status"]), transitioned=True)
        pending = self._transition(
            row,
            "cancel_requested",
            event_type="cancel_requested",
            actor="system",
            event_time=requested_at,
            reason=reason,
            cancel_reason=reason,
            last_synced_at=requested_at,
        )
        try:
            raw_result = broker.cancel_order(
                broker_order_no=str(pending["broker_order_no"]),
                broker_branch_no=str(pending["broker_branch_no"]),
                reason=reason,
            )
        except Exception as exc:
            updated = self._transition(
                self._require_order(order_id),
                "unknown",
                event_type="cancel_unknown",
                actor="system",
                event_time=requested_at,
                reason="broker_cancel_exception",
                raw_broker_response={"error": str(exc)},
                last_synced_at=requested_at,
            )
            return LiveOrderManagerResult(order_id=order_id, status=str(updated["status"]), transitioned=True)

        result = _normalize_cancel_result(raw_result)
        if not result.accepted:
            updated = self._transition(
                self._require_order(order_id),
                "unknown",
                event_type="cancel_unknown",
                actor="system",
                event_time=requested_at,
                reason=result.cancel_reason or "broker_cancel_rejected",
                raw_broker_response=result.raw_response,
                last_synced_at=requested_at,
            )
            return LiveOrderManagerResult(order_id=order_id, status=str(updated["status"]), transitioned=True)
        target_status = result.status.strip().lower()
        if target_status not in (ALLOWED_TRANSITIONS["cancel_requested"] | {"cancel_requested"}):
            target_status = "cancel_requested"
        updated = self._transition(
            self._require_order(order_id),
            target_status,
            event_type=f"cancel_{target_status}",
            actor="system",
            event_time=requested_at,
            reason=result.cancel_reason or "broker_cancel_response",
            raw_broker_response=result.raw_response,
            last_synced_at=requested_at,
        )
        return LiveOrderManagerResult(
            order_id=order_id,
            status=str(updated["status"]),
            transitioned=True,
            raw_response=_redacted_broker_payload(result.raw_response),
        )

    def mark_unknown(self, *, order_id: str, reason: str, event_time: datetime) -> LiveOrderManagerResult:
        updated = self._transition(
            self._require_order(order_id),
            "unknown",
            event_type="mark_unknown",
            actor="system",
            event_time=event_time,
            reason=reason,
            last_synced_at=event_time,
        )
        return LiveOrderManagerResult(order_id=order_id, status=str(updated["status"]), transitioned=True)

    def recover_open_orders(self, *, trading_day: str, recovered_at: datetime) -> list[LiveOrderManagerResult]:
        results: list[LiveOrderManagerResult] = []
        for row in self.store.fetch_open_live_orders(trading_day):
            status = str(row["status"])
            if status in RECOVERY_TO_UNKNOWN_STATUSES:
                updated = self._transition(
                    row,
                    "unknown",
                    event_type="restart_recovery_unknown",
                    actor="recovery",
                    event_time=recovered_at,
                    reason="open_order_recovery_requires_broker_reconcile",
                    last_synced_at=recovered_at,
                )
                results.append(
                    LiveOrderManagerResult(order_id=str(updated["order_id"]), status=str(updated["status"]), transitioned=True)
                )
            else:
                results.append(LiveOrderManagerResult(order_id=str(row["order_id"]), status=status, transitioned=False))
        return results

    def _pre_submit_blocking_reasons(
        self,
        request: LiveOrderIntentRequest,
        idempotency_key: str,
    ) -> tuple[str, ...]:
        return self._pre_submit_check(request, idempotency_key).blocking_reasons

    def _pre_submit_check(
        self,
        request: LiveOrderIntentRequest,
        idempotency_key: str,
    ) -> LivePreSubmitCheck:
        policy = _pre_submit_policy(request)
        reasons: list[str] = []
        context: dict[str, Any] = {
            "phase": request.phase,
            "max_parent_orders_per_day": policy.max_parent_orders_per_day,
            "block_same_symbol_pending": policy.block_same_symbol_pending,
            "block_live_fill_mismatch": policy.block_live_fill_mismatch,
            "max_order_qty": policy.max_order_qty,
            "max_order_notional": policy.max_order_notional,
            "allocation_amount": policy.allocation_amount,
            "max_order_allocation_pct": policy.max_order_allocation_pct,
        }
        if policy.max_order_qty is not None and request.parent_order_id is None and int(request.qty) > policy.max_order_qty:
            reasons.append("phase2_order_qty_limit_exceeded")
            context["phase2_order_qty_limit_exceeded"] = {
                "current": int(request.qty),
                "limit": policy.max_order_qty,
            }
        order_notional = max(float(request.qty) * float(request.limit_price), 0.0)
        effective_order_limit = _effective_order_notional_limit(policy)
        context["order_notional"] = order_notional
        context["effective_max_order_notional"] = effective_order_limit
        if effective_order_limit is not None and request.parent_order_id is None and order_notional > effective_order_limit:
            reasons.append("phase2_order_notional_limit_exceeded")
            context["phase2_order_notional_limit_exceeded"] = {
                "current": order_notional,
                "limit": effective_order_limit,
            }
        if policy.max_parent_orders_per_day is not None and request.parent_order_id is None:
            parent_orders = [
                row
                for row in self.store.fetch_live_orders_for_trading_day(request.trading_day)
                if _is_parent_live_order(row)
                and str(row["idempotency_key"]) != idempotency_key
                and str(row["status"]) != "blocked"
            ]
            context["parent_order_count"] = len(parent_orders)
            context["parent_order_limit_remaining"] = max(policy.max_parent_orders_per_day - len(parent_orders), 0)
            if len(parent_orders) >= policy.max_parent_orders_per_day:
                reasons.append("phase2_parent_order_limit_exceeded")
                context["phase2_parent_order_limit_exceeded"] = {
                    "current": len(parent_orders),
                    "limit": policy.max_parent_orders_per_day,
                }
        if policy.block_same_symbol_pending:
            same_symbol_pending = [
                row
                for row in self.store.fetch_open_live_orders(request.trading_day)
                if str(row["idempotency_key"]) != idempotency_key and str(row["symbol"]) == request.symbol
            ]
            context["same_symbol_pending_count"] = len(same_symbol_pending)
            if same_symbol_pending:
                reasons.append("same_symbol_order_pending")
        if policy.block_live_fill_mismatch:
            mismatched_orders = [
                row
                for row in self.store.fetch_live_orders_for_trading_day(request.trading_day)
                if int(row["filled_qty"] or 0) != self.store.sum_live_fill_qty(str(row["order_id"]))
            ]
            context["live_fill_mismatch_count"] = len(mismatched_orders)
            if mismatched_orders:
                reasons.append("live_fill_mismatch_detected")
        return LivePreSubmitCheck(blocking_reasons=tuple(reasons), context=context)

    def _transition(
        self,
        row: Any,
        to_status: str,
        *,
        event_type: str,
        actor: str,
        event_time: datetime,
        reason: str,
        broker_order_no: str | None = None,
        broker_branch_no: str | None = None,
        reject_reason: str | None = None,
        cancel_reason: str | None = None,
        raw_broker_response: dict[str, Any] | None = None,
        submitted_at: datetime | None = None,
        last_synced_at: datetime | None = None,
        blocking_reasons: tuple[str, ...] = (),
        blocking_context: dict[str, Any] | None = None,
    ) -> Any:
        from_status = str(row["status"])
        _assert_transition_allowed(from_status, to_status)
        detail_json = _row_detail(row)
        if blocking_reasons:
            detail_json["blocking_reasons"] = list(blocking_reasons)
        if blocking_context is not None:
            detail_json["pre_submit_policy_context"] = blocking_context
        if raw_broker_response is not None:
            detail_json["raw_broker_response"] = _redacted_broker_payload(raw_broker_response)
        self.store.update_live_order_transition(
            order_id=str(row["order_id"]),
            status=to_status,
            broker_order_no=broker_order_no if broker_order_no is not None else str(row["broker_order_no"]),
            broker_branch_no=broker_branch_no if broker_branch_no is not None else str(row["broker_branch_no"]),
            reject_reason=reject_reason if reject_reason is not None else row["reject_reason"],
            cancel_reason=cancel_reason if cancel_reason is not None else row["cancel_reason"],
            submitted_at=submitted_at or _parse_datetime(row["submitted_at"]),
            last_synced_at=last_synced_at or _parse_datetime(row["last_synced_at"]),
            detail_json=detail_json,
        )
        self._write_event(
            order_id=str(row["order_id"]),
            event_time=event_time,
            from_status=from_status,
            to_status=to_status,
            event_type=event_type,
            actor=actor,
            reason=reason,
            raw_broker_response=raw_broker_response or {},
        )
        return self._require_order(str(row["order_id"]))

    def _write_event(
        self,
        *,
        order_id: str,
        event_time: datetime,
        from_status: str,
        to_status: str,
        event_type: str,
        actor: str,
        reason: str,
        raw_broker_response: dict[str, Any],
    ) -> None:
        event = LiveOrderEvent(
            order_event_id=f"live-order-event-{_short_hash('|'.join([order_id, event_time.isoformat(), event_type, from_status, to_status]))}",
            order_id=order_id,
            event_time=event_time,
            from_status=from_status,
            to_status=to_status,
            event_type=event_type,
            actor=actor,
            detail_json={
                "reason": reason,
                "source": "live_order_manager",
                "raw_broker_response": _redacted_broker_payload(raw_broker_response),
            },
        )
        self.writer.write_live_order_event(event)

    def _require_order(self, order_id: str) -> Any:
        row = self.store.fetch_live_order(order_id)
        if row is None:
            raise KeyError(f"live order not found: {order_id}")
        return row


def _idempotency_key(request: LiveOrderIntentRequest) -> str:
    payload = {
        "trading_day": request.trading_day,
        "phase": request.phase,
        "symbol": request.symbol,
        "side": request.side,
        "qty": request.qty,
        "order_type": request.order_type,
        "limit_price": request.limit_price,
        "prediction_id": request.prediction_id,
        "signal_id": request.signal_id,
        "target_id": request.target_id,
        "gate_decision_id": request.gate_decision_id,
        "rule_version": request.rule_version,
        "parent_order_id": request.parent_order_id,
    }
    return "live-idem-" + _short_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _validate_intent_request(request: LiveOrderIntentRequest) -> None:
    required_fields = {
        "trading_day": request.trading_day,
        "phase": request.phase,
        "symbol": request.symbol,
        "side": request.side,
        "order_type": request.order_type,
        "prediction_id": request.prediction_id,
        "signal_id": request.signal_id,
        "target_id": request.target_id,
        "gate_decision_id": request.gate_decision_id,
        "market_status_snapshot_id": request.market_status_snapshot_id,
        "model_version": request.model_version,
        "rule_version": request.rule_version,
    }
    missing = [key for key, value in required_fields.items() if not str(value or "").strip()]
    if missing:
        raise ValueError(f"live order intent missing required fields: {', '.join(missing)}")
    if int(request.qty) <= 0:
        raise ValueError("live order intent qty must be greater than zero")
    normalized_side = str(request.side).strip().lower()
    if normalized_side not in {"buy", "sell", "b", "s", "01", "02"}:
        raise ValueError("live order intent side must be buy or sell")
    limit_price = float(request.limit_price)
    if limit_price < 0:
        raise ValueError("live order intent limit_price must not be negative")
    if str(request.order_type).strip().lower() == "limit" and limit_price <= 0:
        raise ValueError("limit live order intent limit_price must be greater than zero")


def _pre_submit_policy(request: LiveOrderIntentRequest) -> LivePreSubmitPolicy:
    policy = dict(request.order_policy or {})
    phase = request.phase.strip().lower()
    if phase in PHASE2_PRE_SUBMIT_PHASES:
        return LivePreSubmitPolicy(
            max_parent_orders_per_day=_policy_int(
                policy.get("max_parent_orders_per_day", policy.get("max_parent_orders", 1)),
                default=1,
            ),
            block_same_symbol_pending=_policy_bool(policy.get("block_same_symbol_pending"), default=True),
            block_live_fill_mismatch=_policy_bool(policy.get("block_live_fill_mismatch"), default=True),
            max_order_qty=_policy_int(
                policy.get("max_order_qty", policy.get("max_qty", PHASE2_DEFAULT_MAX_ORDER_QTY)),
                default=PHASE2_DEFAULT_MAX_ORDER_QTY,
            ),
            max_order_notional=_policy_float(
                policy.get("max_order_notional", policy.get("max_order_amount", PHASE2_DEFAULT_MAX_ORDER_NOTIONAL)),
                default=PHASE2_DEFAULT_MAX_ORDER_NOTIONAL,
            ),
            allocation_amount=_policy_float(
                policy.get("allocation_amount", policy.get("phase2_allocation_amount")),
                default=None,
            ),
            max_order_allocation_pct=_policy_float(
                policy.get("max_order_allocation_pct", policy.get("max_order_allocation_ratio", PHASE2_DEFAULT_MAX_ORDER_ALLOCATION_PCT)),
                default=PHASE2_DEFAULT_MAX_ORDER_ALLOCATION_PCT,
            ),
        )
    return LivePreSubmitPolicy(
        max_parent_orders_per_day=_policy_int(
            policy.get("max_parent_orders_per_day", policy.get("max_parent_orders")),
            default=None,
        ),
        block_same_symbol_pending=_policy_bool(policy.get("block_same_symbol_pending"), default=False),
        block_live_fill_mismatch=_policy_bool(policy.get("block_live_fill_mismatch"), default=False),
        max_order_qty=_policy_int(
            policy.get("max_order_qty", policy.get("max_qty")),
            default=None,
        ),
        max_order_notional=_policy_float(
            policy.get("max_order_notional", policy.get("max_order_amount")),
            default=None,
        ),
        allocation_amount=_policy_float(
            policy.get("allocation_amount", policy.get("phase2_allocation_amount")),
            default=None,
        ),
        max_order_allocation_pct=_policy_float(
            policy.get("max_order_allocation_pct", policy.get("max_order_allocation_ratio")),
            default=None,
        ),
    )


def _policy_int(value: Any, *, default: int | None) -> int | None:
    if value is None or value == "":
        return default
    return max(int(value), 0)


def _policy_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _policy_float(value: Any, *, default: float | None) -> float | None:
    if value is None or value == "":
        return default
    return max(float(value), 0.0)


def _effective_order_notional_limit(policy: LivePreSubmitPolicy) -> float | None:
    candidates: list[float] = []
    if policy.max_order_notional is not None:
        candidates.append(policy.max_order_notional)
    if (
        policy.allocation_amount is not None
        and policy.allocation_amount > 0
        and policy.max_order_allocation_pct is not None
        and policy.max_order_allocation_pct >= 0
    ):
        candidates.append(policy.allocation_amount * policy.max_order_allocation_pct)
    if not candidates:
        return None
    return min(candidates)


def _is_parent_live_order(row: Any) -> bool:
    parent_order_id = row["parent_order_id"]
    return parent_order_id is None or str(parent_order_id) == ""


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _assert_transition_allowed(from_status: str, to_status: str) -> None:
    if from_status == to_status:
        return
    allowed = ALLOWED_TRANSITIONS.get(from_status)
    if allowed is None:
        raise LiveOrderTransitionError(f"unknown live order status: {from_status}")
    if to_status not in allowed:
        raise LiveOrderTransitionError(f"live order transition not allowed: {from_status} -> {to_status}")


def _row_detail(row: Any) -> dict[str, Any]:
    value = row["detail_json"]
    if isinstance(value, dict):
        return dict(value)
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


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _normalize_submit_result(value: BrokerSubmitResult | dict[str, Any]) -> BrokerSubmitResult:
    if isinstance(value, BrokerSubmitResult):
        return value
    accepted = bool(value.get("accepted", value.get("ok", False)))
    return BrokerSubmitResult(
        accepted=accepted,
        status=str(value.get("status") or ("submitted" if accepted else "rejected")),
        broker_order_no=str(value.get("broker_order_no") or value.get("order_no") or ""),
        broker_branch_no=str(value.get("broker_branch_no") or value.get("branch_no") or ""),
        reject_reason=value.get("reject_reason"),
        raw_response=dict(value),
    )


def _normalize_cancel_result(value: BrokerCancelResult | dict[str, Any]) -> BrokerCancelResult:
    if isinstance(value, BrokerCancelResult):
        return value
    accepted = bool(value.get("accepted", value.get("ok", False)))
    return BrokerCancelResult(
        accepted=accepted,
        status=str(value.get("status") or "cancel_requested"),
        cancel_reason=value.get("cancel_reason"),
        raw_response=dict(value),
    )


def _submit_target_status(result: BrokerSubmitResult) -> str:
    if not result.accepted:
        return "rejected"
    if not result.broker_order_no:
        return "unknown"
    status = result.status.strip().lower()
    if status in {"submitted", "accepted", "open"}:
        return status
    return "submitted"


def _redacted_broker_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = redact_kis_payload(payload or {})
    return redacted if isinstance(redacted, dict) else {}
