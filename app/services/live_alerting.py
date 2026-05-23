"""Live operation alert routing and outbox records.

This module decides which channels should receive an alert and writes local
outbox records. It does not send Telegram or email messages by itself, so no
secret token, SMTP password, or network access is required for unit tests.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.brokers.kis_response_redaction import redact_kis_payload


ALERT_SEVERITIES = {"info", "warning", "critical"}
ALERT_CHANNELS = ("local", "telegram", "email")
IMPORTANT_EMAIL_EVENT_TYPES = {
    "kill_switch_enabled",
    "live_order_unknown",
    "live_order_stuck",
    "live_order_attention",
    "live_fill_mismatch",
    "live_submit_unknown",
    "live_cancel_unknown",
    "database_unavailable",
    "disk_space_low",
    "live_runtime_down",
    "broker_account_mismatch",
}


@dataclass(frozen=True, slots=True)
class LiveAlert:
    alert_id: str
    created_at: datetime
    severity: str
    event_type: str
    title: str
    message: str
    source: str
    trading_day: str | None = None
    symbol: str | None = None
    order_id: str | None = None
    dedupe_key: str | None = None
    detail_json: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        severity = self.severity.strip().lower()
        if severity not in ALERT_SEVERITIES:
            allowed = ", ".join(sorted(ALERT_SEVERITIES))
            raise ValueError(f"severity must be one of: {allowed}")
        if not self.alert_id.strip():
            raise ValueError("alert_id must not be empty")
        if not self.event_type.strip():
            raise ValueError("event_type must not be empty")
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if not self.message.strip():
            raise ValueError("message must not be empty")

    def to_record(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "created_at": self.created_at.isoformat(),
            "severity": self.severity,
            "event_type": self.event_type,
            "title": self.title,
            "message": self.message,
            "source": self.source,
            "trading_day": self.trading_day,
            "symbol": self.symbol,
            "order_id": self.order_id,
            "dedupe_key": self.dedupe_key,
            "detail_json": self.detail_json,
        }


@dataclass(frozen=True, slots=True)
class LiveAlertRoute:
    channels: tuple[str, ...]
    important: bool
    written_channels: tuple[str, ...] = ()
    suppressed_channels: tuple[str, ...] = ()

    @property
    def telegram(self) -> bool:
        return "telegram" in self.channels

    @property
    def email(self) -> bool:
        return "email" in self.channels


def route_live_alert(alert: LiveAlert) -> LiveAlertRoute:
    severity = alert.severity.strip().lower()
    important = bool(alert.detail_json.get("important")) or alert.event_type in IMPORTANT_EMAIL_EVENT_TYPES
    channels = ["local"]
    if severity in {"warning", "critical"}:
        channels.append("telegram")
    if severity == "critical" or important:
        channels.append("email")
    return LiveAlertRoute(channels=tuple(dict.fromkeys(channels)), important=important)


def render_telegram_alert(alert: LiveAlert) -> str:
    return _render_alert_text(alert, heading_prefix="[LIVE ALERT]")


def render_email_alert(alert: LiveAlert) -> dict[str, str]:
    subject = f"[LIVE {alert.severity.upper()}] {alert.title}"
    body = _render_alert_text(alert, heading_prefix="LIVE OPERATION ALERT")
    return {"subject": subject, "body": body}


def build_live_monitoring_alerts(
    *,
    created_at: datetime,
    live_fill_consistency: dict[str, Any] | None,
    live_order_attention: dict[str, Any] | None,
    source: str = "live_monitoring",
) -> tuple[LiveAlert, ...]:
    alerts: list[LiveAlert] = []
    fill_payload = live_fill_consistency or {}
    fill_mismatch_count = int(fill_payload.get("mismatch_count") or 0)
    if fill_mismatch_count > 0:
        trading_day = _optional_text(fill_payload.get("trading_day"))
        fingerprint = _payload_fingerprint(
            {
                "mismatch_count": fill_mismatch_count,
                "mismatches": fill_payload.get("mismatches") or [],
            }
        )
        alerts.append(
            LiveAlert(
                alert_id=_alert_id("live_fill_mismatch", trading_day, fingerprint),
                created_at=created_at,
                severity="critical",
                event_type="live_fill_mismatch",
                title="실전 fill 정합성 불일치",
                message=(
                    f"{trading_day or '-'} 기준 live order/fill 수량 불일치 "
                    f"{fill_mismatch_count}건이 있습니다. 신규 실전 주문을 차단하고 브로커 체결 조회로 확인해야 합니다."
                ),
                source=source,
                trading_day=trading_day,
                dedupe_key=f"live_fill_mismatch:{trading_day or 'unknown'}:{fingerprint}",
                detail_json={"important": True, "live_fill_consistency": fill_payload},
            )
        )

    attention_payload = live_order_attention or {}
    attention_count = int(attention_payload.get("attention_count") or 0)
    if attention_count > 0 and not _inside_attention_grace(attention_payload):
        trading_day = _optional_text(attention_payload.get("trading_day"))
        fingerprint = _payload_fingerprint(
            {
                "attention_count": attention_count,
                "attention_orders": attention_payload.get("attention_orders") or [],
            }
        )
        alerts.append(
            LiveAlert(
                alert_id=_alert_id("live_order_attention", trading_day, fingerprint),
                created_at=created_at,
                severity="critical",
                event_type="live_order_attention",
                title="실전 주문 상태 확인 필요",
                message=(
                    f"{trading_day or '-'} 기준 unknown/stuck 실전 주문 "
                    f"{attention_count}건이 있습니다. 상태 확정 전 신규 실전 주문을 보수적으로 차단해야 합니다."
                ),
                source=source,
                trading_day=trading_day,
                dedupe_key=f"live_order_attention:{trading_day or 'unknown'}:{fingerprint}",
                detail_json={"important": True, "live_order_attention": attention_payload},
            )
        )
    return tuple(alerts)


class LiveAlertOutbox:
    def __init__(self, alerts_root: Path) -> None:
        self.alerts_root = alerts_root

    def write_alert(self, alert: LiveAlert) -> LiveAlertRoute:
        route = route_live_alert(alert)
        written_channels: list[str] = []
        suppressed_channels: list[str] = []
        for channel in route.channels:
            written = self._append_channel_record(alert, channel=channel, route=route)
            if written:
                written_channels.append(channel)
            else:
                suppressed_channels.append(channel)
        return LiveAlertRoute(
            channels=route.channels,
            important=route.important,
            written_channels=tuple(written_channels),
            suppressed_channels=tuple(suppressed_channels),
        )

    def _append_channel_record(self, alert: LiveAlert, *, channel: str, route: LiveAlertRoute) -> bool:
        if channel not in ALERT_CHANNELS:
            raise ValueError(f"unknown alert channel: {channel}")
        channel_dir = self.alerts_root / channel
        channel_dir.mkdir(parents=True, exist_ok=True)
        path = channel_dir / f"alerts-{alert.created_at.date().isoformat()}.jsonl"
        if _path_contains_alert_id(path, alert.alert_id):
            return False
        alert_record = _redacted_alert_record(alert)
        record = {
            "channel": channel,
            "delivery_mode": "outbox_only",
            "dedupe_status": "new",
            "route": {"channels": list(route.channels), "important": route.important},
            "alert": alert_record,
            "rendered": _rendered_for_channel(alert, channel),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return True


def _rendered_for_channel(alert: LiveAlert, channel: str) -> Any:
    if channel == "telegram":
        return {"text": render_telegram_alert(alert)}
    if channel == "email":
        return render_email_alert(alert)
    return {"text": _render_alert_text(alert, heading_prefix="[LOCAL ALERT]")}


def _redacted_alert_record(alert: LiveAlert) -> dict[str, Any]:
    record = alert.to_record()
    record["detail_json"] = redact_kis_payload(record.get("detail_json") or {})
    return record


def _render_alert_text(alert: LiveAlert, *, heading_prefix: str) -> str:
    lines = [
        f"{heading_prefix} {alert.title}",
        f"- severity: {alert.severity}",
        f"- event_type: {alert.event_type}",
        f"- created_at: {alert.created_at.isoformat()}",
    ]
    if alert.trading_day:
        lines.append(f"- trading_day: {alert.trading_day}")
    if alert.symbol:
        lines.append(f"- symbol: {alert.symbol}")
    if alert.order_id:
        lines.append(f"- order_id: {alert.order_id}")
    lines.append(f"- message: {alert.message}")
    return "\n".join(lines)


def _alert_id(event_type: str, trading_day: str | None, fingerprint: str) -> str:
    return f"live-alert-{event_type}-{trading_day or 'unknown'}-{fingerprint}"


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _inside_attention_grace(payload: dict[str, Any]) -> bool:
    grace_minutes = _optional_float(payload.get("attention_grace_minutes", payload.get("grace_minutes")))
    if grace_minutes is None or grace_minutes <= 0:
        return False
    max_age_minutes = _optional_float(payload.get("max_attention_age_minutes"))
    if max_age_minutes is None:
        return False
    return max_age_minutes < grace_minutes


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _path_contains_alert_id(path: Path, alert_id: str) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                alert = record.get("alert") if isinstance(record, dict) else None
                if isinstance(alert, dict) and alert.get("alert_id") == alert_id:
                    return True
    except OSError:
        return False
    return False
