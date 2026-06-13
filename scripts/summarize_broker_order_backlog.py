#!/usr/bin/env python3
"""Summarize broker paper open-order backlog without mutating the ledger."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = REPO_ROOT / "runtime-data" / "dev.db"
DEFAULT_ALIGNMENT_PATH = REPO_ROOT / "runtime-data" / "reports" / "broker-paper" / "latest-alignment.json"
DEFAULT_SYNC_PATH = REPO_ROOT / "runtime-data" / "reports" / "broker-paper" / "latest-sync.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "broker-paper"
OPEN_STATUSES = {"submitted", "pending_lookup", "open", "partially_filled"}
FINAL_STATUSES = {"filled", "cancelled", "cancelled_partial", "rejected", "expired", "expired_partial"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"_missing": True, "_path": str(path)}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"_invalid_json": True, "_path": str(path), "error": str(exc)}


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_order_date(value: Any) -> datetime.date | None:
    normalized = str(value or "").replace("-", "").strip()
    if len(normalized) < 8:
        return None
    try:
        return datetime.strptime(normalized[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def project_backlog_status(
    *,
    current_status: str,
    order_date: Any,
    synced_at: Any,
    order_qty: int,
    filled_qty: int,
    remaining_qty: int,
    applied_fill_qty: int,
) -> tuple[str, str]:
    status = str(current_status or "submitted")
    if status in FINAL_STATUSES:
        return status, "already_final"

    effective_filled = max(int(filled_qty or 0), int(applied_fill_qty or 0))
    effective_remaining = max(int(remaining_qty or 0), int(order_qty or 0) - effective_filled)
    if order_qty > 0 and effective_filled >= order_qty:
        return "filled", "applied_fill_qty_covers_order"
    if effective_remaining <= 0 and order_qty > 0:
        return "filled", "remaining_qty_zero"

    parsed_order_date = _parse_order_date(order_date)
    parsed_synced_at = _parse_iso(synced_at)
    if parsed_order_date is not None and parsed_synced_at is not None and parsed_order_date < parsed_synced_at.date():
        if effective_filled > 0:
            return "expired_partial", "prior_day_open_with_partial_fill"
        return "expired", "prior_day_open_unfilled"
    return status, "still_current_or_unknown"


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _load_rows(conn: sqlite3.Connection, *, alignment_cutoff: str | None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = ()
    where = ""
    if alignment_cutoff:
        where = "where event_time >= ?"
        params = (alignment_cutoff,)
    query = f"""
    with submissions as (
      select * from broker_paper_order_submissions {where}
    ),
    latest as (
      select local_order_id, max(synced_at) as max_synced_at
      from broker_paper_order_status_snapshots
      group by local_order_id
    )
    select
      sub.local_order_id,
      sub.symbol,
      sub.event_time as submission_time,
      sub.side as submission_side,
      sub.qty as submission_qty,
      sub.limit_price,
      sub.broker_order_no,
      sub.broker_branch_no,
      coalesce(snap.status, sub.status, po.status, 'submitted') as current_status,
      snap.order_date,
      coalesce(snap.order_qty, sub.qty, po.qty, 0) as order_qty,
      coalesce(snap.filled_qty, 0) as filled_qty,
      coalesce(snap.remaining_qty, sub.qty, po.qty, 0) as remaining_qty,
      coalesce(snap.applied_fill_qty, 0) as applied_fill_qty,
      coalesce(snap.matched, 0) as matched,
      snap.synced_at,
      po.status as paper_status
    from submissions sub
    left join latest latest on latest.local_order_id = sub.local_order_id
    left join broker_paper_order_status_snapshots snap
      on snap.local_order_id = sub.local_order_id
     and snap.synced_at = latest.max_synced_at
    left join paper_orders po on po.order_id = sub.local_order_id
    order by sub.event_time, sub.local_order_id
    """
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def build_backlog_analysis(
    *,
    rows: list[dict[str, Any]],
    latest_sync: dict[str, Any],
    alignment: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    analyzed_rows: list[dict[str, Any]] = []
    for row in rows:
        projected_status, projection_reason = project_backlog_status(
            current_status=str(row.get("current_status") or ""),
            order_date=row.get("order_date") or str(row.get("submission_time") or "")[:10],
            synced_at=row.get("synced_at") or latest_sync.get("synced_at"),
            order_qty=_int(row.get("order_qty")),
            filled_qty=_int(row.get("filled_qty")),
            remaining_qty=_int(row.get("remaining_qty")),
            applied_fill_qty=_int(row.get("applied_fill_qty")),
        )
        enriched = dict(row)
        enriched["projected_status"] = projected_status
        enriched["projection_reason"] = projection_reason
        enriched["current_is_open"] = str(row.get("current_status") or "") in OPEN_STATUSES
        enriched["projected_is_open"] = projected_status in OPEN_STATUSES
        enriched["applied_fill_gt_filled"] = _int(row.get("applied_fill_qty")) > _int(row.get("filled_qty"))
        analyzed_rows.append(enriched)

    current_open = [row for row in analyzed_rows if row["current_is_open"]]
    projected_open = [row for row in analyzed_rows if row["projected_is_open"]]
    would_close = [row for row in analyzed_rows if row["current_is_open"] and not row["projected_is_open"]]
    current_open_by_date = Counter(str(row.get("submission_time") or "")[:10] for row in current_open)
    current_open_by_symbol = Counter(str(row.get("symbol") or "") for row in current_open)
    projected_status_counts = Counter(str(row.get("projected_status") or "") for row in analyzed_rows)
    current_status_counts = Counter(str(row.get("current_status") or "") for row in analyzed_rows)
    reason_counts = Counter(str(row.get("projection_reason") or "") for row in analyzed_rows)

    return {
        "generated_at": generated_at or _now_iso(),
        "ok": True,
        "status": "analysis_only",
        "read_only": True,
        "alignment_cutoff": alignment.get("aligned_at"),
        "latest_sync": {
            "synced_at": latest_sync.get("synced_at"),
            "status": latest_sync.get("status"),
            "reported_open_order_count": latest_sync.get("open_order_count"),
            "reported_final_order_count": latest_sync.get("final_order_count"),
            "reported_pending_symbols": latest_sync.get("pending_symbols"),
        },
        "summary": {
            "submission_rows": len(analyzed_rows),
            "current_open_order_count": len(current_open),
            "projected_open_order_count": len(projected_open),
            "would_close_count": len(would_close),
            "current_status_counts": dict(sorted(current_status_counts.items())),
            "projected_status_counts": dict(sorted(projected_status_counts.items())),
            "projection_reason_counts": dict(sorted(reason_counts.items())),
            "current_open_by_submission_date": dict(sorted(current_open_by_date.items())),
            "current_open_by_symbol": dict(sorted(current_open_by_symbol.items())),
            "current_open_applied_fill_gt_filled_count": sum(1 for row in current_open if row["applied_fill_gt_filled"]),
        },
        "samples": {
            "current_open": current_open[:20],
            "would_close": would_close[:20],
            "projected_open": projected_open[:20],
        },
        "recommendation": _build_recommendation(would_close=would_close, projected_open=projected_open),
    }


def _build_recommendation(
    *,
    would_close: list[dict[str, Any]],
    projected_open: list[dict[str, Any]],
) -> dict[str, str]:
    if would_close and not projected_open:
        return {
            "next_action": "run_broker_paper_sync_after_fix",
            "reason": "All currently open rows would become final under the fixed prior-day/preserved-final interpretation.",
        }
    if not would_close and not projected_open:
        return {
            "next_action": "backlog_cleared_no_action",
            "reason": "No current or projected open broker paper orders remain after the latest sync.",
        }
    return {
        "next_action": "review_projected_open_orders",
        "reason": "Some rows still project as open and need separate broker/account review.",
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = payload.get("summary") or {}
    latest_sync = payload.get("latest_sync") or {}
    recommendation = payload.get("recommendation") or {}
    lines = [
        "# Broker Open Order Backlog Analysis",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        "- mode: read-only analysis",
        f"- alignment_cutoff: `{payload.get('alignment_cutoff')}`",
        "",
        "## Summary",
        "",
        f"- latest sync status: `{latest_sync.get('status')}`",
        f"- latest sync reported open orders: `{latest_sync.get('reported_open_order_count')}`",
        f"- submission rows after alignment: `{summary.get('submission_rows')}`",
        f"- current open order count: `{summary.get('current_open_order_count')}`",
        f"- projected open order count: `{summary.get('projected_open_order_count')}`",
        f"- would close count: `{summary.get('would_close_count')}`",
        f"- current open applied_fill > filled count: `{summary.get('current_open_applied_fill_gt_filled_count')}`",
        "",
        "## Current Open By Date",
        "",
    ]
    by_date = summary.get("current_open_by_submission_date") or {}
    lines.extend(f"- `{key}`: {value}" for key, value in by_date.items()) if by_date else lines.append("- none")
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- next action: `{recommendation.get('next_action')}`",
            f"- reason: {recommendation.get('reason')}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_reports(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest-open-order-backlog-analysis.json"
    markdown_path = output_dir / "latest-open-order-backlog-analysis.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(markdown_path, payload)
    return json_path, markdown_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--alignment-path", type=Path, default=DEFAULT_ALIGNMENT_PATH)
    parser.add_argument("--latest-sync-path", type=Path, default=DEFAULT_SYNC_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    alignment = _read_json(args.alignment_path)
    latest_sync = _read_json(args.latest_sync_path)
    with _connect_readonly(args.database_path) as conn:
        rows = _load_rows(conn, alignment_cutoff=alignment.get("aligned_at"))
    payload = build_backlog_analysis(rows=rows, latest_sync=latest_sync, alignment=alignment)
    json_path, markdown_path = write_reports(payload, args.output_dir)
    payload["report_json_path"] = str(json_path)
    payload["report_markdown_path"] = str(markdown_path)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"broker open order backlog analysis: {payload['recommendation']['next_action']}")
        print(f"report: {markdown_path}")


if __name__ == "__main__":
    main()
