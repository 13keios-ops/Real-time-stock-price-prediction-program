#!/usr/bin/env python3
"""Probe full-period KIS paper account activity without exposing identifiers."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.brokers.kis_auth import KisApiError
from app.brokers.kis_quote_rest import KisDailyOrderFillRecord
from app.brokers.kis_readonly import get_kis_readonly_client
from app.config.settings import load_settings
from app.services.kis_probe_errors import build_sanitized_kis_probe_error
from app.utils.time import get_market_session_status, now_local


DEFAULT_DB_PATH = Path("runtime-data/dev.db")
DEFAULT_ALIGNMENT_PATH = Path("runtime-data/reports/broker-paper/latest-alignment.json")
DEFAULT_ACCOUNT_SYNC_PATH = Path("runtime-data/reports/reconciliation/latest-paper-account-sync.json")
DEFAULT_REPORT_PATH = Path("runtime-data/reports/reconciliation/latest-paper-account-activity.json")
DEFAULT_ATTEMPT_PATH = Path("runtime-data/reports/reconciliation/latest-paper-account-activity-attempt.json")
DEFAULT_COOLDOWN_SECONDS = 2 * 60 * 60


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _date_text(value: datetime) -> str:
    return value.strftime("%Y%m%d")


def _normalize_order_date(value: Any) -> str:
    return str(value or "").replace("-", "")[:8]


def _position_qty(rows: Iterable[dict[str, Any]], *, qty_keys: tuple[str, ...]) -> dict[str, int]:
    positions: dict[str, int] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        qty = 0
        for key in qty_keys:
            if row.get(key) not in {None, ""}:
                qty = int(row.get(key) or 0)
                break
        if qty:
            positions[symbol] = qty
    return positions


def load_probe_scope(
    *,
    db_path: Path,
    alignment_path: Path,
    account_sync_path: Path,
) -> dict[str, Any]:
    alignment = _read_json(alignment_path)
    account_sync = _read_json(account_sync_path)
    aligned_at = _parse_datetime(alignment.get("aligned_at"))
    account_as_of = _parse_datetime(account_sync.get("as_of"))
    blocking_reasons: list[str] = []
    if aligned_at is None:
        blocking_reasons.append("alignment_marker_missing")
    if account_as_of is None:
        blocking_reasons.append("account_snapshot_time_missing")
    if not db_path.exists():
        blocking_reasons.append("runtime_database_missing")

    submissions: list[dict[str, Any]] = []
    if not blocking_reasons:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            submissions = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT local_order_id, broker_branch_no, broker_order_no,
                           symbol, event_time, side, qty
                    FROM broker_paper_order_submissions
                    WHERE event_time > ? AND event_time <= ?
                    ORDER BY event_time, submission_id
                    """,
                    (aligned_at.isoformat(), account_as_of.isoformat()),
                )
            ]
        finally:
            connection.close()

    broker_account = account_sync.get("broker_account") if isinstance(account_sync.get("broker_account"), dict) else {}
    local_account = account_sync.get("local_account") if isinstance(account_sync.get("local_account"), dict) else {}
    query_start = _date_text(aligned_at) if aligned_at is not None else None
    query_end = _date_text(account_as_of) if account_as_of is not None else None
    return {
        "aligned_at": aligned_at.isoformat() if aligned_at is not None else None,
        "account_as_of": account_as_of.isoformat() if account_as_of is not None else None,
        "query_start": query_start,
        "query_end": query_end,
        "local_submissions": submissions,
        "baseline_positions": _position_qty(
            alignment.get("baseline_positions") or [],
            qty_keys=("qty", "holding_qty"),
        ),
        "broker_snapshot_positions": _position_qty(
            broker_account.get("positions") or [],
            qty_keys=("holding_qty", "qty"),
        ),
        "local_positions": _position_qty(
            local_account.get("positions") or [],
            qty_keys=("qty", "holding_qty"),
        ),
        "blocking_reasons": blocking_reasons,
    }


def scope_summary(scope: dict[str, Any]) -> dict[str, Any]:
    submissions = scope.get("local_submissions") or []
    dates = sorted(
        {
            _normalize_order_date(str(row.get("event_time") or "")[:10])
            for row in submissions
            if row.get("event_time")
        }
    )
    return {
        "alignment_at": scope.get("aligned_at"),
        "account_snapshot_as_of": scope.get("account_as_of"),
        "query_start": scope.get("query_start"),
        "query_end": scope.get("query_end"),
        "local_mirrored_submission_rows": len(submissions),
        "local_mirrored_trade_dates": len(dates),
        "local_mirrored_first_date": dates[0] if dates else None,
        "local_mirrored_last_date": dates[-1] if dates else None,
        "baseline_position_count": len(scope.get("baseline_positions") or {}),
        "broker_snapshot_position_count": len(scope.get("broker_snapshot_positions") or {}),
        "local_position_count": len(scope.get("local_positions") or {}),
        "blocking_reasons": list(scope.get("blocking_reasons") or []),
    }


def _local_exact_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _normalize_order_date(str(row.get("event_time") or "")[:10]),
        str(row.get("broker_branch_no") or ""),
        str(row.get("broker_order_no") or ""),
    )


def _broker_exact_key(row: KisDailyOrderFillRecord) -> tuple[str, str, str]:
    return (
        _normalize_order_date(row.order_date),
        str(row.broker_branch_no or ""),
        str(row.broker_order_no or ""),
    )


def _fallback_key(key: tuple[str, str, str]) -> tuple[str, str]:
    return key[1], key[2]


def _signed_broker_fill(row: KisDailyOrderFillRecord) -> int:
    qty = int(row.filled_qty or 0)
    if str(row.side or "") == "01":
        return -qty
    if str(row.side or "") == "02":
        return qty
    return 0


def _position_comparison(
    activity_positions: dict[str, int],
    snapshot_positions: dict[str, int],
    local_positions: dict[str, int],
) -> tuple[list[dict[str, Any]], bool, bool]:
    symbols = sorted(set(activity_positions) | set(snapshot_positions) | set(local_positions))
    rows: list[dict[str, Any]] = []
    activity_matches_snapshot = True
    local_matches_snapshot = True
    for symbol in symbols:
        activity_qty = int(activity_positions.get(symbol, 0))
        snapshot_qty = int(snapshot_positions.get(symbol, 0))
        local_qty = int(local_positions.get(symbol, 0))
        if activity_qty != snapshot_qty:
            activity_matches_snapshot = False
        if local_qty != snapshot_qty:
            local_matches_snapshot = False
        rows.append(
            {
                "symbol": symbol,
                "full_activity_qty": activity_qty,
                "broker_snapshot_qty": snapshot_qty,
                "local_qty": local_qty,
                "activity_snapshot_gap": activity_qty - snapshot_qty,
                "local_snapshot_gap": local_qty - snapshot_qty,
            }
        )
    return rows, activity_matches_snapshot, local_matches_snapshot


def build_success_report(
    *,
    scope: dict[str, Any],
    broker_rows: list[KisDailyOrderFillRecord],
    pagination: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    local_rows = list(scope.get("local_submissions") or [])
    local_exact_counts = Counter(_local_exact_key(row) for row in local_rows)
    broker_exact_counts = Counter(_broker_exact_key(row) for row in broker_rows)
    local_fallback_counts = Counter(_fallback_key(key) for key in local_exact_counts)
    broker_fallback_counts = Counter(_fallback_key(key) for key in broker_exact_counts)
    ambiguous_fallback_keys = {
        key
        for key in set(local_fallback_counts) | set(broker_fallback_counts)
        if local_fallback_counts.get(key, 0) > 1 or broker_fallback_counts.get(key, 0) > 1
    }
    conflicting_exact_keys = {
        key for key, count in broker_exact_counts.items() if count > 1
    }

    local_exact_keys = set(local_exact_counts)
    local_fallback_keys = set(local_fallback_counts)
    broker_exact_keys = set(broker_exact_counts)
    broker_fallback_keys = set(broker_fallback_counts)
    broker_rows_unlinked = sum(
        1
        for row in broker_rows
        if _broker_exact_key(row) not in local_exact_keys
        and _fallback_key(_broker_exact_key(row)) not in local_fallback_keys
    )
    local_rows_unlinked = sum(
        1
        for row in local_rows
        if _local_exact_key(row) not in broker_exact_keys
        and _fallback_key(_local_exact_key(row)) not in broker_fallback_keys
    )

    deduplicated_rows: dict[tuple[str, str, str], KisDailyOrderFillRecord] = {}
    for row in broker_rows:
        key = _broker_exact_key(row)
        existing = deduplicated_rows.get(key)
        if existing is None or int(row.filled_qty or 0) >= int(existing.filled_qty or 0):
            deduplicated_rows[key] = row

    activity_positions = defaultdict(int, scope.get("baseline_positions") or {})
    date_counts: Counter[str] = Counter()
    for row in deduplicated_rows.values():
        activity_positions[str(row.symbol or "")] += _signed_broker_fill(row)
        date_counts[_normalize_order_date(row.order_date)] += 1
    activity_positions = {
        symbol: qty for symbol, qty in sorted(activity_positions.items()) if qty
    }
    position_rows, activity_matches_snapshot, local_matches_snapshot = _position_comparison(
        activity_positions,
        scope.get("broker_snapshot_positions") or {},
        scope.get("local_positions") or {},
    )

    pagination_complete = bool(pagination.get("pagination_complete"))
    evidence_complete = pagination_complete and not conflicting_exact_keys
    if not pagination_complete:
        status = "blocked_incomplete_pagination"
    elif not broker_rows and local_rows:
        status = "blocked_history_unavailable_or_empty"
    elif conflicting_exact_keys:
        status = "blocked_ambiguous_broker_activity"
    elif activity_matches_snapshot and local_matches_snapshot:
        status = "full_activity_and_accounts_matched"
    elif activity_matches_snapshot and broker_rows_unlinked > 0:
        status = "resolved_external_or_unlinked_account_activity"
    elif activity_matches_snapshot:
        status = "resolved_local_ledger_divergence"
    else:
        status = "broker_snapshot_vs_full_activity_divergence"

    root_cause_scope = {
        "full_activity_and_accounts_matched": "none",
        "resolved_external_or_unlinked_account_activity": "external_or_unlinked_broker_activity",
        "resolved_local_ledger_divergence": "local_ledger_divergence",
        "broker_snapshot_vs_full_activity_divergence": "kis_account_snapshot_vs_full_account_activity_divergence",
    }.get(status, "full_account_activity_evidence_incomplete")

    return {
        "schema_version": 1,
        "generated_at": generated_at.astimezone().isoformat(timespec="seconds"),
        "status": status,
        "mode": "paper",
        "access": "read-only",
        "execution_started": True,
        "scope": scope_summary(scope),
        "pagination": dict(pagination),
        "broker_activity": {
            "rows": len(broker_rows),
            "distinct_order_keys": len(broker_exact_counts),
            "distinct_trade_dates": len(date_counts),
            "first_trade_date": min(date_counts) if date_counts else None,
            "last_trade_date": max(date_counts) if date_counts else None,
            "rows_linked_to_local_submissions": len(broker_rows) - broker_rows_unlinked,
            "rows_unlinked_to_local_submissions": broker_rows_unlinked,
            "local_submissions_unlinked_to_broker_rows": local_rows_unlinked,
            "ambiguous_fallback_key_count": len(ambiguous_fallback_keys),
            "duplicate_exact_key_count": len(conflicting_exact_keys),
        },
        "position_reconstruction": {
            "evidence_complete": evidence_complete,
            "activity_matches_broker_snapshot": activity_matches_snapshot,
            "local_matches_broker_snapshot": local_matches_snapshot,
            "rows": position_rows,
        },
        "root_cause_scope": root_cause_scope,
        "phase0_resolution": {
            "status": (
                "cause_identified_clean_baseline_still_required"
                if status.startswith("resolved_")
                else "full_account_history_confirmed"
                if status == "full_activity_and_accounts_matched"
                else "blocked_requires_clean_baseline_or_broker_support"
                if status == "blocked_history_unavailable_or_empty"
                else "blocked_requires_evidence_review"
            ),
            "automatic_alignment_allowed": False,
        },
        "safety": {
            "account_identifiers_in_report": False,
            "broker_order_identifiers_in_report": False,
            "raw_response_in_report": False,
            "order_calls": 0,
            "cancel_calls": 0,
        },
    }


def build_attempt_report(
    *,
    scope: dict[str, Any],
    status: str,
    generated_at: datetime,
    execution_started: bool,
    max_pages: int,
    error: dict[str, Any] | None = None,
    cooldown_until: datetime | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": generated_at.astimezone().isoformat(timespec="seconds"),
        "status": status,
        "mode": "paper",
        "access": "read-only",
        "execution_started": execution_started,
        "scope": scope_summary(scope),
        "request_limits": {"request_batch_cap": 1, "max_pages": max_pages},
        "safety": {
            "account_identifiers_in_report": False,
            "broker_order_identifiers_in_report": False,
            "raw_response_in_report": False,
            "order_calls": 0,
            "cancel_calls": 0,
        },
    }
    if error:
        payload["error"] = dict(error)
    if cooldown_until is not None:
        payload["cooldown_until"] = cooldown_until.astimezone().isoformat(timespec="seconds")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _active_cooldown(attempt_path: Path, *, now: datetime) -> datetime | None:
    previous = _read_json(attempt_path)
    if previous.get("status") not in {"rate_limited", "cooldown_active"}:
        return None
    generated_at = _parse_datetime(previous.get("generated_at"))
    cooldown_until = _parse_datetime(previous.get("cooldown_until"))
    if cooldown_until is None and generated_at is not None:
        cooldown_until = generated_at + timedelta(seconds=DEFAULT_COOLDOWN_SECONDS)
    if cooldown_until is not None and cooldown_until > now:
        return cooldown_until
    return None


def _resolve_inside_repo(value: str, repo_root: Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise SystemExit(f"{label} must stay inside repository root: {resolved}") from exc
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--alignment-path", default=str(DEFAULT_ALIGNMENT_PATH))
    parser.add_argument("--account-sync-path", default=str(DEFAULT_ACCOUNT_SYNC_PATH))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--attempt-path", default=str(DEFAULT_ATTEMPT_PATH))
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    db_path = _resolve_inside_repo(args.db_path, project_root, "db_path")
    alignment_path = _resolve_inside_repo(args.alignment_path, project_root, "alignment_path")
    account_sync_path = _resolve_inside_repo(args.account_sync_path, project_root, "account_sync_path")
    report_path = _resolve_inside_repo(args.report_path, project_root, "report_path")
    attempt_path = _resolve_inside_repo(args.attempt_path, project_root, "attempt_path")
    settings = load_settings(project_root=project_root)
    local_now = now_local(settings.timezone)
    scope = load_probe_scope(
        db_path=db_path,
        alignment_path=alignment_path,
        account_sync_path=account_sync_path,
    )

    if scope.get("blocking_reasons"):
        payload = build_attempt_report(
            scope=scope,
            status="blocked_missing_local_evidence",
            generated_at=local_now,
            execution_started=False,
            max_pages=args.max_pages,
        )
        _write_json_atomic(attempt_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    session_status = get_market_session_status(settings.market_calendar, local_now)
    if session_status in {"pre-open", "regular-session"}:
        payload = build_attempt_report(
            scope=scope,
            status="blocked_protected_market_session",
            generated_at=local_now,
            execution_started=False,
            max_pages=args.max_pages,
        )
        payload["market_session_status"] = session_status
        _write_json_atomic(attempt_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    cooldown_until = _active_cooldown(attempt_path, now=local_now)
    if cooldown_until is not None:
        payload = build_attempt_report(
            scope=scope,
            status="cooldown_active",
            generated_at=local_now,
            execution_started=False,
            max_pages=args.max_pages,
            cooldown_until=cooldown_until,
        )
        payload["market_session_status"] = session_status
        _write_json_atomic(attempt_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    if not args.execute:
        payload = build_attempt_report(
            scope=scope,
            status="ready_dry_run",
            generated_at=local_now,
            execution_started=False,
            max_pages=args.max_pages,
        )
        payload["market_session_status"] = session_status
        _write_json_atomic(attempt_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    readonly_client = get_kis_readonly_client(
        settings,
        mode="paper",
        timeout_seconds=args.timeout_seconds,
    )
    try:
        broker_rows = readonly_client.get_daily_order_fills(
            start_date=str(scope["query_start"]),
            end_date=str(scope["query_end"]),
            max_pages=args.max_pages,
        )
    except KisApiError as exc:
        error = build_sanitized_kis_probe_error(exc)
        rate_limited = error.get("error_category") == "rate_limited"
        cooldown_until = (
            local_now + timedelta(seconds=DEFAULT_COOLDOWN_SECONDS)
            if rate_limited
            else None
        )
        payload = build_attempt_report(
            scope=scope,
            status="rate_limited" if rate_limited else "query_failed",
            generated_at=local_now,
            execution_started=True,
            max_pages=args.max_pages,
            error=error,
            cooldown_until=cooldown_until,
        )
        _write_json_atomic(attempt_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    payload = build_success_report(
        scope=scope,
        broker_rows=broker_rows,
        pagination=readonly_client.last_daily_order_fill_query,
        generated_at=local_now,
    )
    payload["market_session_status"] = session_status
    _write_json_atomic(report_path, payload)
    _write_json_atomic(attempt_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("status") == "full_activity_and_accounts_matched" else 2


if __name__ == "__main__":
    raise SystemExit(main())
