"""Append-only live audit hash chain helpers.

This module builds and verifies live audit events. It does not submit orders,
query KIS, or decide whether trading may continue.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Protocol

from app.storage.contracts import LiveAuditEvent


GENESIS_HASH = "0" * 64
REQUIRED_AUDIT_FIELDS = (
    "trading_day",
    "event_type",
    "actor",
    "symbol",
    "order_id",
    "prediction_id",
    "signal_id",
    "gate_decision_id",
    "rule_version",
    "model_version",
    "data_snapshot_id",
    "previous_hash",
)


class LiveAuditWriterProtocol(Protocol):
    sqlite_store: Any

    def write_live_audit_event(self, event: LiveAuditEvent) -> None:
        ...


@dataclass(frozen=True, slots=True)
class LiveAuditVerificationIssue:
    index: int
    audit_event_id: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class LiveAuditVerificationResult:
    checked_count: int
    issues: tuple[LiveAuditVerificationIssue, ...]
    latest_hash: str

    @property
    def ok(self) -> bool:
        return not self.issues


class LiveAuditLog:
    def __init__(self, writer: LiveAuditWriterProtocol) -> None:
        self.writer = writer

    def append(
        self,
        *,
        event_time: datetime,
        trading_day: str,
        event_type: str,
        actor: str,
        symbol: str,
        order_id: str,
        prediction_id: str,
        signal_id: str,
        gate_decision_id: str,
        rule_version: str,
        model_version: str,
        data_snapshot_id: str,
        detail_json: dict[str, Any],
    ) -> LiveAuditEvent:
        previous_hash = self.latest_hash(trading_day=trading_day)
        event = build_live_audit_event(
            event_time=event_time,
            trading_day=trading_day,
            event_type=event_type,
            actor=actor,
            symbol=symbol,
            order_id=order_id,
            prediction_id=prediction_id,
            signal_id=signal_id,
            gate_decision_id=gate_decision_id,
            rule_version=rule_version,
            model_version=model_version,
            data_snapshot_id=data_snapshot_id,
            previous_hash=previous_hash,
            detail_json=detail_json,
        )
        self.writer.write_live_audit_event(event)
        return event

    def latest_hash(self, *, trading_day: str) -> str:
        rows = _fetch_audit_rows(self.writer.sqlite_store, trading_day=trading_day)
        if not rows:
            return GENESIS_HASH
        return _event_from_record(rows[-1]).event_hash

    def verify(self, *, trading_day: str | None = None) -> LiveAuditVerificationResult:
        return verify_live_audit_chain(_fetch_audit_rows(self.writer.sqlite_store, trading_day=trading_day))


def build_live_audit_event(
    *,
    event_time: datetime,
    trading_day: str,
    event_type: str,
    actor: str,
    symbol: str,
    order_id: str,
    prediction_id: str,
    signal_id: str,
    gate_decision_id: str,
    rule_version: str,
    model_version: str,
    data_snapshot_id: str,
    previous_hash: str,
    detail_json: dict[str, Any],
) -> LiveAuditEvent:
    _validate_required_audit_fields(
        {
            "trading_day": trading_day,
            "event_type": event_type,
            "actor": actor,
            "symbol": symbol,
            "order_id": order_id,
            "prediction_id": prediction_id,
            "signal_id": signal_id,
            "gate_decision_id": gate_decision_id,
            "rule_version": rule_version,
            "model_version": model_version,
            "data_snapshot_id": data_snapshot_id,
            "previous_hash": previous_hash,
        }
    )
    event_hash = compute_live_audit_hash(
        event_time=event_time,
        trading_day=trading_day,
        event_type=event_type,
        actor=actor,
        symbol=symbol,
        order_id=order_id,
        prediction_id=prediction_id,
        signal_id=signal_id,
        gate_decision_id=gate_decision_id,
        rule_version=rule_version,
        model_version=model_version,
        data_snapshot_id=data_snapshot_id,
        previous_hash=previous_hash,
        detail_json=detail_json,
    )
    return LiveAuditEvent(
        audit_event_id=f"live-audit-{trading_day}-{event_hash[:16]}",
        event_time=event_time,
        trading_day=trading_day,
        event_type=event_type,
        actor=actor,
        symbol=symbol,
        order_id=order_id,
        prediction_id=prediction_id,
        signal_id=signal_id,
        gate_decision_id=gate_decision_id,
        rule_version=rule_version,
        model_version=model_version,
        data_snapshot_id=data_snapshot_id,
        previous_hash=previous_hash,
        event_hash=event_hash,
        detail_json=detail_json,
    )


def compute_live_audit_hash(
    *,
    event_time: datetime | str,
    trading_day: str,
    event_type: str,
    actor: str,
    symbol: str,
    order_id: str,
    prediction_id: str,
    signal_id: str,
    gate_decision_id: str,
    rule_version: str,
    model_version: str,
    data_snapshot_id: str,
    previous_hash: str,
    detail_json: dict[str, Any],
) -> str:
    payload = {
        "event_time": _event_time_text(event_time),
        "trading_day": trading_day,
        "event_type": event_type,
        "actor": actor,
        "symbol": symbol,
        "order_id": order_id,
        "prediction_id": prediction_id,
        "signal_id": signal_id,
        "gate_decision_id": gate_decision_id,
        "rule_version": rule_version,
        "model_version": model_version,
        "data_snapshot_id": data_snapshot_id,
        "previous_hash": previous_hash,
        "detail_json": detail_json,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_live_audit_chain(records: Iterable[Any]) -> LiveAuditVerificationResult:
    issues: list[LiveAuditVerificationIssue] = []
    latest_hash = GENESIS_HASH
    events = [_event_from_record(record) for record in records]
    for index, event in enumerate(events):
        if event.previous_hash != latest_hash:
            issues.append(
                LiveAuditVerificationIssue(
                    index=index,
                    audit_event_id=event.audit_event_id,
                    code="previous_hash_mismatch",
                    message=f"expected previous_hash {latest_hash}, got {event.previous_hash}",
                )
            )
        expected_hash = compute_live_audit_hash(
            event_time=event.event_time,
            trading_day=event.trading_day,
            event_type=event.event_type,
            actor=event.actor,
            symbol=event.symbol,
            order_id=event.order_id,
            prediction_id=event.prediction_id,
            signal_id=event.signal_id,
            gate_decision_id=event.gate_decision_id,
            rule_version=event.rule_version,
            model_version=event.model_version,
            data_snapshot_id=event.data_snapshot_id,
            previous_hash=event.previous_hash,
            detail_json=event.detail_json,
        )
        if event.event_hash != expected_hash:
            issues.append(
                LiveAuditVerificationIssue(
                    index=index,
                    audit_event_id=event.audit_event_id,
                    code="event_hash_mismatch",
                    message=f"expected event_hash {expected_hash}, got {event.event_hash}",
                )
            )
        latest_hash = event.event_hash
    return LiveAuditVerificationResult(
        checked_count=len(events),
        issues=tuple(issues),
        latest_hash=latest_hash,
    )


def _fetch_audit_rows(sqlite_store: Any, *, trading_day: str | None) -> list[Any]:
    if sqlite_store is None:
        raise ValueError("sqlite_store is required for live audit chain append/verify")
    if hasattr(sqlite_store, "fetch_live_audit_events"):
        return list(sqlite_store.fetch_live_audit_events(trading_day=trading_day))
    rows = sqlite_store.fetch_all_rows("ops_live_audit_events", "event_time")
    if trading_day is None:
        return list(rows)
    return [row for row in rows if str(_record_get(row, "trading_day")) == trading_day]


def _event_from_record(record: Any) -> LiveAuditEvent:
    if isinstance(record, LiveAuditEvent):
        return record
    detail_json = _record_get(record, "detail_json")
    if isinstance(detail_json, str):
        detail_json = json.loads(detail_json)
    event_time = _record_get(record, "event_time")
    if isinstance(event_time, str):
        event_time = datetime.fromisoformat(event_time)
    return LiveAuditEvent(
        audit_event_id=str(_record_get(record, "audit_event_id")),
        event_time=event_time,
        trading_day=str(_record_get(record, "trading_day")),
        event_type=str(_record_get(record, "event_type")),
        actor=str(_record_get(record, "actor")),
        symbol=str(_record_get(record, "symbol")),
        order_id=str(_record_get(record, "order_id")),
        prediction_id=str(_record_get(record, "prediction_id")),
        signal_id=str(_record_get(record, "signal_id")),
        gate_decision_id=str(_record_get(record, "gate_decision_id")),
        rule_version=str(_record_get(record, "rule_version")),
        model_version=str(_record_get(record, "model_version")),
        data_snapshot_id=str(_record_get(record, "data_snapshot_id")),
        previous_hash=str(_record_get(record, "previous_hash")),
        event_hash=str(_record_get(record, "event_hash")),
        detail_json=detail_json,
    )


def _record_get(record: Any, key: str) -> Any:
    if isinstance(record, dict):
        return record[key]
    return record[key]


def _event_time_text(value: datetime | str) -> str:
    return value.isoformat() if isinstance(value, datetime) else value


def _validate_required_audit_fields(values: dict[str, str]) -> None:
    missing = [key for key in REQUIRED_AUDIT_FIELDS if not str(values.get(key, "")).strip()]
    if missing:
        raise ValueError(f"live audit event missing required fields: {', '.join(missing)}")
    previous_hash = str(values["previous_hash"]).strip()
    if len(previous_hash) != 64 or any(char not in "0123456789abcdefABCDEF" for char in previous_hash):
        raise ValueError("previous_hash must be a 64 character hex string")
