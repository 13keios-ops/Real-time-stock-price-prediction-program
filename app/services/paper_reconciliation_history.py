"""Sanitized daily history for local-paper versus KIS-paper reconciliation."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Iterable


HISTORY_SCHEMA_VERSION = 1
DEFAULT_REQUIRED_DAYS = 10
HISTORY_DIRECTORY_NAME = "paper-account-history"
LATEST_JSON_NAME = "latest-paper-account-history.json"
LATEST_MARKDOWN_NAME = "latest-paper-account-history.md"


def _report_directory(runtime_data_dir: Path) -> Path:
    return runtime_data_dir / "reports" / "reconciliation"


def _history_directory(runtime_data_dir: Path) -> Path:
    return _report_directory(runtime_data_dir) / HISTORY_DIRECTORY_NAME


def _load_phase0_epoch_start(runtime_data_dir: Path) -> str | None:
    marker_path = runtime_data_dir / "reports" / "broker-paper" / "latest-alignment.json"
    if not marker_path.is_file():
        return None
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(marker, dict) or marker.get("status") != "aligned_to_broker_marker":
        return None
    aligned_at = str(marker.get("aligned_at") or "")
    try:
        datetime.fromisoformat(aligned_at)
    except ValueError:
        return None
    return aligned_at


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_trade_date(as_of: str) -> str | None:
    try:
        return datetime.fromisoformat(as_of).date().isoformat()
    except (TypeError, ValueError):
        return None


def build_paper_reconciliation_history_entry(
    payload: dict[str, Any],
    *,
    market_session_status: str,
) -> dict[str, Any]:
    comparison = payload.get("comparison") or {}
    as_of = str(payload.get("as_of") or "")
    trade_date = _parse_trade_date(as_of)
    mismatch_symbols = sorted(
        {
            str(row.get("symbol"))
            for row in comparison.get("mismatch_rows", [])
            if row.get("symbol")
        }
    )
    status = str(comparison.get("status") or "unknown")
    mirrored_order_count = int(comparison.get("mirrored_order_count") or 0)
    broker_account_available = bool(payload.get("ok"))
    matched = bool(
        broker_account_available
        and status == "aligned"
        and mirrored_order_count > 0
        and comparison.get("positions_match") is True
        and comparison.get("balance_match") is True
        and comparison.get("total_asset_match") is True
        and int(comparison.get("mismatch_count") or 0) == 0
    )
    session = str(market_session_status or "unknown").strip().lower()
    eligible_for_phase0_gate = bool(
        session == "post-close"
        and trade_date is not None
        and broker_account_available
        and mirrored_order_count > 0
    )
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "trade_date": trade_date,
        "as_of": as_of or None,
        "market_session_status": session,
        "eligible_for_phase0_gate": eligible_for_phase0_gate,
        "broker_account_available": broker_account_available,
        "status": status,
        "matched": matched,
        "mismatch_count": int(comparison.get("mismatch_count") or 0),
        "mismatch_symbols": mismatch_symbols,
        "positions_match": comparison.get("positions_match") is True,
        "balance_match": comparison.get("balance_match") is True,
        "total_asset_match": comparison.get("total_asset_match") is True,
        "cash_gap": _safe_float(comparison.get("cash_gap")),
        "total_asset_gap": _safe_float(comparison.get("total_asset_gap")),
        "order_mirroring_enabled": bool(comparison.get("order_mirroring_enabled")),
        "mirrored_order_count": mirrored_order_count,
    }


def _summarize_eligible_days(
    all_days: list[dict[str, Any]],
    *,
    required_days: int,
) -> dict[str, Any]:
    window = all_days[-required_days:]
    matched_days = sum(1 for entry in window if entry.get("matched") is True)
    mismatch_days = sum(1 for entry in window if entry.get("matched") is not True)
    consecutive_matched_days = 0
    for entry in reversed(window):
        if entry.get("matched") is not True:
            break
        consecutive_matched_days += 1

    days_available = len(window)
    if days_available == 0:
        gate_status = "no_history"
    elif mismatch_days:
        gate_status = "needs_review"
    elif days_available < required_days:
        gate_status = "insufficient_history"
    else:
        gate_status = "ready"
    observation_status = (
        "no_history"
        if not window
        else "ok"
        if mismatch_days == 0
        else "needs_review"
    )
    cash_gaps = [abs(float(entry["cash_gap"])) for entry in window if entry.get("cash_gap") is not None]
    asset_gaps = [
        abs(float(entry["total_asset_gap"]))
        for entry in window
        if entry.get("total_asset_gap") is not None
    ]
    latest = window[-1] if window else {}
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "status": gate_status,
        "observation_status": observation_status,
        "ready": gate_status == "ready",
        "required_days": required_days,
        "days_available": days_available,
        "days_remaining": max(required_days - days_available, 0),
        "matched_days": matched_days,
        "mismatch_days": mismatch_days,
        "consecutive_matched_days": consecutive_matched_days,
        "date_range": {
            "start": window[0].get("trade_date") if window else None,
            "end": window[-1].get("trade_date") if window else None,
        },
        "latest_status": latest.get("status"),
        "latest_mismatch_count": latest.get("mismatch_count"),
        "latest_mismatch_symbols": list(latest.get("mismatch_symbols") or []),
        "max_abs_cash_gap": max(cash_gaps) if cash_gaps else None,
        "max_abs_total_asset_gap": max(asset_gaps) if asset_gaps else None,
        "days": window,
    }


def _entry_is_after_epoch(entry: dict[str, Any], epoch_start_at: str) -> bool:
    try:
        return datetime.fromisoformat(str(entry.get("as_of") or "")) > datetime.fromisoformat(epoch_start_at)
    except (TypeError, ValueError):
        return False


def summarize_paper_reconciliation_history(
    entries: Iterable[dict[str, Any]],
    *,
    required_days: int = DEFAULT_REQUIRED_DAYS,
    epoch_start_at: str | None = None,
) -> dict[str, Any]:
    if required_days <= 0:
        raise ValueError("required_days must be positive")
    latest_by_day: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not entry.get("eligible_for_phase0_gate"):
            continue
        trade_date = str(entry.get("trade_date") or "")
        if not trade_date:
            continue
        previous = latest_by_day.get(trade_date)
        if previous is None or str(entry.get("as_of") or "") >= str(previous.get("as_of") or ""):
            latest_by_day[trade_date] = dict(entry)

    all_days = [latest_by_day[trade_date] for trade_date in sorted(latest_by_day)]
    if epoch_start_at:
        current_days = [entry for entry in all_days if _entry_is_after_epoch(entry, epoch_start_at)]
        prior_days = [entry for entry in all_days if not _entry_is_after_epoch(entry, epoch_start_at)]
    else:
        current_days = all_days
        prior_days = []

    summary = _summarize_eligible_days(current_days, required_days=required_days)
    summary["phase0_epoch"] = (
        {
            "status": "owner_approved_clean_baseline",
            "baseline_at": epoch_start_at,
            "baseline_trade_date": _parse_trade_date(epoch_start_at),
            "eligible_evidence_scope": "strictly_after_baseline",
        }
        if epoch_start_at
        else None
    )
    summary["prior_epoch"] = (
        _summarize_eligible_days(prior_days, required_days=required_days)
        if epoch_start_at
        else None
    )
    summary["interpretation"] = (
        "Phase 0 requires ten eligible post-close trading days with aligned mirrored-account evidence "
        "inside the current clean-baseline epoch. Pre-open, regular-session, weekend, holiday, "
        "no-submission, and pre-baseline observations do not count as current matched days."
    )
    return summary


def _load_daily_entries(runtime_data_dir: Path) -> list[dict[str, Any]]:
    history_dir = _history_directory(runtime_data_dir)
    if not history_dir.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("????-??-??.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def load_paper_reconciliation_history(
    runtime_data_dir: Path,
    *,
    required_days: int = DEFAULT_REQUIRED_DAYS,
) -> dict[str, Any]:
    epoch_start_at = _load_phase0_epoch_start(runtime_data_dir)
    if epoch_start_at:
        return summarize_paper_reconciliation_history(
            _load_daily_entries(runtime_data_dir),
            required_days=required_days,
            epoch_start_at=epoch_start_at,
        )

    latest_path = _report_directory(runtime_data_dir) / LATEST_JSON_NAME
    if latest_path.is_file():
        try:
            payload = json.loads(latest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and int(payload.get("required_days") or 0) == required_days:
            return payload
    return summarize_paper_reconciliation_history(
        _load_daily_entries(runtime_data_dir),
        required_days=required_days,
    )


def record_paper_reconciliation_history(
    runtime_data_dir: Path,
    payload: dict[str, Any],
    *,
    market_session_status: str,
    required_days: int = DEFAULT_REQUIRED_DAYS,
) -> dict[str, Any]:
    entry = build_paper_reconciliation_history_entry(
        payload,
        market_session_status=market_session_status,
    )
    trade_date = entry.get("trade_date")
    if not trade_date:
        raise ValueError("reconciliation payload must include an ISO as_of date")
    history_dir = _history_directory(runtime_data_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    entry_path = history_dir / f"{trade_date}.json"
    _write_json_atomic(entry_path, entry)

    summary = summarize_paper_reconciliation_history(
        _load_daily_entries(runtime_data_dir),
        required_days=required_days,
        epoch_start_at=_load_phase0_epoch_start(runtime_data_dir),
    )
    summary["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    report_dir = _report_directory(runtime_data_dir)
    json_path = report_dir / LATEST_JSON_NAME
    markdown_path = report_dir / LATEST_MARKDOWN_NAME
    _write_json_atomic(json_path, summary)
    _write_text_atomic(markdown_path, render_paper_reconciliation_history_markdown(summary))
    return {
        "entry_path": str(entry_path),
        "summary_json_path": str(json_path),
        "summary_markdown_path": str(markdown_path),
        "summary": summary,
    }


def render_paper_reconciliation_history_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Paper Account Reconciliation History",
        "",
        f"- status: `{summary.get('status')}`",
        f"- observation_status: `{summary.get('observation_status')}`",
        f"- ready: `{summary.get('ready')}`",
        f"- days: `{summary.get('days_available')}/{summary.get('required_days')}`",
        f"- matched_days: `{summary.get('matched_days')}`",
        f"- mismatch_days: `{summary.get('mismatch_days')}`",
        f"- consecutive_matched_days: `{summary.get('consecutive_matched_days')}`",
        f"- date_range: `{summary.get('date_range', {}).get('start')}` ~ `{summary.get('date_range', {}).get('end')}`",
        f"- clean_baseline_at: `{(summary.get('phase0_epoch') or {}).get('baseline_at')}`",
        f"- prior_epoch_status: `{(summary.get('prior_epoch') or {}).get('status')}`",
        f"- prior_epoch_days: `{(summary.get('prior_epoch') or {}).get('days_available')}`",
        "",
        "| date | status | matched | mismatch_count | cash_gap | total_asset_gap | mismatch_symbols |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for entry in summary.get("days", []):
        lines.append(
            "| {date} | {status} | {matched} | {mismatch_count} | {cash_gap} | {asset_gap} | {symbols} |".format(
                date=entry.get("trade_date"),
                status=entry.get("status"),
                matched=entry.get("matched"),
                mismatch_count=entry.get("mismatch_count"),
                cash_gap=entry.get("cash_gap"),
                asset_gap=entry.get("total_asset_gap"),
                symbols=", ".join(entry.get("mismatch_symbols") or []) or "-",
            )
        )
    lines.extend(["", summary.get("interpretation") or "", ""])
    return "\n".join(lines)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
