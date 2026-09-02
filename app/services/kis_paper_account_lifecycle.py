"""Sanitized lifecycle and Phase 0 compatibility for the current KIS paper account."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config.settings import AppSettings, KisPaperAccountLifecycleSettings


def _as_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _phase0_compatibility(
    history: dict[str, Any],
    *,
    lifecycle: KisPaperAccountLifecycleSettings,
) -> dict[str, Any]:
    epoch = history.get("phase0_epoch") or {}
    baseline_at = epoch.get("baseline_at")
    baseline_date: date | None = None
    if baseline_at:
        try:
            baseline_date = datetime.fromisoformat(str(baseline_at)).date()
        except ValueError:
            baseline_date = None

    if baseline_date is None:
        status = "current_account_baseline_missing"
        compatible = False
    elif baseline_date < lifecycle.activated_on:
        status = "baseline_predates_current_account"
        compatible = False
    else:
        status = "compatible"
        compatible = True

    return {
        "status": status,
        "compatible": compatible,
        "account_epoch_id": lifecycle.account_epoch_id,
        "account_activated_on": lifecycle.activated_on.isoformat(),
        "baseline_at": baseline_at,
        "baseline_trade_date": baseline_date.isoformat() if baseline_date else None,
    }


def build_kis_paper_account_lifecycle(
    settings: AppSettings,
    *,
    phase0_history: dict[str, Any] | None = None,
    as_of: date | str | None = None,
) -> dict[str, Any]:
    lifecycle = settings.kis_paper_account_lifecycle
    current_date = (
        _as_date(as_of)
        if as_of is not None
        else datetime.now(ZoneInfo(settings.timezone)).date()
    )
    warning_start = lifecycle.expires_on - timedelta(days=lifecycle.renewal_warning_days)
    urgent_start = lifecycle.expires_on - timedelta(days=lifecycle.renewal_urgent_days)
    days_until_expiry = (lifecycle.expires_on - current_date).days

    if current_date >= lifecycle.expires_on:
        lifecycle_status = "expired"
    elif current_date >= urgent_start:
        lifecycle_status = "renewal_urgent"
    elif current_date >= warning_start:
        lifecycle_status = "renewal_due"
    elif current_date < lifecycle.activated_on:
        lifecycle_status = "not_active_yet"
    else:
        lifecycle_status = "active"

    phase0 = _phase0_compatibility(
        phase0_history or {},
        lifecycle=lifecycle,
    )
    blocking_reasons: list[str] = []
    attention_reasons: list[str] = []
    if lifecycle_status in {"expired", "not_active_yet"}:
        blocking_reasons.append(f"paper_account_{lifecycle_status}")
    elif lifecycle_status in {"renewal_due", "renewal_urgent"}:
        attention_reasons.append(f"paper_account_{lifecycle_status}")
    if not phase0["compatible"]:
        blocking_reasons.append(f"phase0_{phase0['status']}")

    status = "blocked" if blocking_reasons else "attention" if attention_reasons else "ok"
    return {
        "schema_version": 1,
        "status": status,
        "passed": status == "ok",
        "as_of_date": current_date.isoformat(),
        "account": {
            "epoch_id": lifecycle.account_epoch_id,
            "activated_on": lifecycle.activated_on.isoformat(),
            "expires_on": lifecycle.expires_on.isoformat(),
            "identifier_in_report": False,
        },
        "renewal": {
            "status": lifecycle_status,
            "days_until_expiry": days_until_expiry,
            "warning_start_on": warning_start.isoformat(),
            "urgent_start_on": urgent_start.isoformat(),
            "warning_lead_days": lifecycle.renewal_warning_days,
            "urgent_lead_days": lifecycle.renewal_urgent_days,
        },
        "phase0_baseline": phase0,
        "blocking_reasons": blocking_reasons,
        "attention_reasons": attention_reasons,
        "safety": {
            "network_calls": 0,
            "order_calls": 0,
            "cancel_calls": 0,
            "secrets_in_report": False,
        },
    }


def render_kis_paper_account_lifecycle_markdown(payload: dict[str, Any]) -> str:
    account = payload.get("account") or {}
    renewal = payload.get("renewal") or {}
    phase0 = payload.get("phase0_baseline") or {}
    return "\n".join(
        [
            "# KIS Paper Account Lifecycle",
            "",
            f"- status: `{payload.get('status')}`",
            f"- as_of_date: `{payload.get('as_of_date')}`",
            f"- account_epoch_id: `{account.get('epoch_id')}`",
            f"- activated_on: `{account.get('activated_on')}`",
            f"- expires_on: `{account.get('expires_on')}`",
            f"- renewal_status: `{renewal.get('status')}`",
            f"- renewal_warning_start_on: `{renewal.get('warning_start_on')}`",
            f"- renewal_urgent_start_on: `{renewal.get('urgent_start_on')}`",
            f"- days_until_expiry: `{renewal.get('days_until_expiry')}`",
            f"- phase0_baseline_status: `{phase0.get('status')}`",
            f"- phase0_baseline_compatible: `{phase0.get('compatible')}`",
            f"- phase0_baseline_at: `{phase0.get('baseline_at')}`",
            f"- blocking_reasons: `{', '.join(payload.get('blocking_reasons') or []) or '-'}`",
            f"- attention_reasons: `{', '.join(payload.get('attention_reasons') or []) or '-'}`",
            "",
            "This report contains no account identifier, credential, token, order, or cancel data.",
            "",
        ]
    )
