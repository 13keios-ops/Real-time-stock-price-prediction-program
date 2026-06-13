#!/usr/bin/env python3
"""Trace local paper vs KIS paper position mismatches.

This script is read-only. It combines the latest reconciliation JSON files with
symbol-filtered SQLite ledger snippets so an operator can see where a local-only
or broker-only position likely came from before applying any alignment.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = REPO_ROOT / "runtime-data" / "dev.db"
DEFAULT_DUAL_MATCH_PATH = (
    REPO_ROOT / "runtime-data" / "reports" / "reconciliation" / "latest-paper-dual-account-match.json"
)
DEFAULT_ACCOUNT_SYNC_PATH = (
    REPO_ROOT / "runtime-data" / "reports" / "reconciliation" / "latest-paper-account-sync.json"
)
DEFAULT_BROKER_SYNC_PATH = REPO_ROOT / "runtime-data" / "reports" / "broker-paper" / "latest-sync.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "reconciliation"

TABLE_NAME_HINTS = (
    "paper",
    "order",
    "fill",
    "position",
    "portfolio",
    "broker",
    "submission",
    "trade",
)
DEFAULT_LEDGER_TABLE_ALLOWLIST = {
    "broker_paper_order_status_snapshots",
    "broker_paper_order_submissions",
    "live_fills",
    "live_orders",
    "live_positions",
    "paper_orders",
    "paper_positions",
}
SYMBOL_COLUMN_CANDIDATES = ("symbol", "ticker", "stock_code", "code", "stck_shrn_iscd")
TIME_COLUMN_CANDIDATES = (
    "event_time",
    "created_at",
    "updated_at",
    "submitted_at",
    "filled_at",
    "opened_at",
    "closed_at",
    "order_time",
    "timestamp",
    "ts",
    "as_of",
)
INTERESTING_COLUMN_HINTS = (
    "id",
    "symbol",
    "ticker",
    "side",
    "action",
    "status",
    "state",
    "qty",
    "quantity",
    "price",
    "cash",
    "pnl",
    "order",
    "fill",
    "broker",
    "submitted",
    "filled",
    "created",
    "updated",
    "time",
)


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: list[str]
    symbol_column: str | None
    time_column: str | None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"_missing": True, "_path": str(path)}
    return json.loads(path.read_text(encoding="utf-8"))


def _pick_symbol_column(columns: Iterable[str]) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in SYMBOL_COLUMN_CANDIDATES:
        if candidate in lowered:
            return lowered[candidate]
    for column in columns:
        lower = column.lower()
        if "symbol" in lower or "ticker" in lower or "stock" in lower:
            return column
    return None


def _pick_time_column(columns: Iterable[str]) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in TIME_COLUMN_CANDIDATES:
        if candidate in lowered:
            return lowered[candidate]
    for column in columns:
        lower = column.lower()
        if lower.endswith("_at") or "time" in lower or "timestamp" in lower:
            return column
    return None


def _interesting_columns(columns: list[str]) -> list[str]:
    selected: list[str] = []
    for column in columns:
        lower = column.lower()
        if any(hint in lower for hint in INTERESTING_COLUMN_HINTS):
            selected.append(column)
    if not selected:
        selected = columns[:12]
    return selected[:18]


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_infos(conn: sqlite3.Connection, *, include_auxiliary: bool) -> list[TableInfo]:
    tables = [
        row[0]
        for row in conn.execute("select name from sqlite_master where type='table' order by name").fetchall()
    ]
    infos: list[TableInfo] = []
    for table in tables:
        columns = [row[1] for row in conn.execute(f"pragma table_info({_quote_identifier(table)})").fetchall()]
        if not columns:
            continue
        lower_name = table.lower()
        symbol_column = _pick_symbol_column(columns)
        if symbol_column is None:
            continue
        if not include_auxiliary and table not in DEFAULT_LEDGER_TABLE_ALLOWLIST:
            continue
        if include_auxiliary and not any(hint in lower_name for hint in TABLE_NAME_HINTS):
            continue
        infos.append(
            TableInfo(
                name=table,
                columns=columns,
                symbol_column=symbol_column,
                time_column=_pick_time_column(columns),
            )
        )
    return infos


def _query_symbol_rows(
    conn: sqlite3.Connection,
    table: TableInfo,
    symbol: str,
    *,
    limit_per_table: int,
) -> list[dict[str, Any]]:
    columns = _interesting_columns(table.columns)
    if table.symbol_column not in columns:
        columns.insert(0, table.symbol_column)
    order_clause = ""
    if table.time_column:
        order_clause = f" order by {_quote_identifier(table.time_column)} desc"
        if table.time_column not in columns:
            columns.insert(0, table.time_column)
    selected = ", ".join(_quote_identifier(column) for column in columns)
    query = (
        f"select {selected} from {_quote_identifier(table.name)} "
        f"where {_quote_identifier(table.symbol_column)} = ?{order_clause} limit ?"
    )
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, (symbol, limit_per_table)).fetchall()
    except sqlite3.DatabaseError as exc:
        return [{"_query_error": str(exc)}]
    return [dict(row) for row in rows]


def _comparison_mismatch_rows(report: dict[str, Any]) -> list[dict[str, Any]] | None:
    comparison = report.get("comparison") if isinstance(report, dict) else None
    if not isinstance(comparison, dict):
        return None
    rows = comparison.get("mismatch_rows")
    if rows is None and comparison.get("status") not in {None, "ok", "matched_waiting_first_submission"}:
        rows = comparison.get("position_rows")
    if rows is None:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _dedupe_mismatch_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        existing = seen.setdefault(symbol, {"symbol": symbol})
        existing.update(row)
    return list(seen.values())


def _select_mismatch_rows(
    *,
    dual_match: dict[str, Any],
    account_sync: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    account_rows = _comparison_mismatch_rows(account_sync)
    if account_rows is not None:
        return _dedupe_mismatch_rows(account_rows), "paper_account_sync"
    dual_rows = _comparison_mismatch_rows(dual_match)
    if dual_rows is not None:
        return _dedupe_mismatch_rows(dual_rows), "dual_account_match"
    return [], "none"


def _broker_sync_summary(report: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "synced_at",
        "status",
        "rate_limited_at",
        "open_order_count",
        "final_order_count",
        "total_submissions",
        "matched_orders",
        "updated_orders",
        "applied_fill_events",
        "applied_fill_qty",
        "pending_symbols",
        "error",
    )
    return {key: report.get(key) for key in keys if key in report}


def _latest_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None


def _summarize_symbol_trace(
    mismatch: dict[str, Any],
    symbol_trace: dict[str, list[dict[str, Any]]],
    *,
    broker_sync_status: str | None,
) -> dict[str, Any]:
    latest_local_order = _latest_row(symbol_trace.get("paper_orders", []))
    latest_broker_submission = _latest_row(symbol_trace.get("broker_paper_order_submissions", []))
    latest_broker_status = _latest_row(symbol_trace.get("broker_paper_order_status_snapshots", []))
    status = mismatch.get("status")
    likely_issue = "needs_manual_review"
    if (
        status == "only_local"
        and latest_local_order
        and latest_local_order.get("side") == "sell"
        and latest_local_order.get("status") in {"submitted", "open", "pending"}
        and broker_sync_status == "rate_limited"
    ):
        likely_issue = "close_order_fill_unknown_due_rate_limit"
    elif status == "only_local" and latest_local_order and latest_local_order.get("side") == "buy":
        likely_issue = "local_buy_position_without_broker_position"
    return {
        "symbol": mismatch.get("symbol"),
        "mismatch_status": status,
        "local_qty": mismatch.get("local_qty"),
        "broker_qty": mismatch.get("broker_qty"),
        "qty_gap": mismatch.get("qty_gap"),
        "latest_local_order": latest_local_order,
        "latest_broker_submission": latest_broker_submission,
        "latest_broker_status_snapshot": latest_broker_status,
        "likely_issue": likely_issue,
    }


def build_trace_report(
    *,
    db_path: Path,
    dual_match_path: Path,
    account_sync_path: Path,
    broker_sync_path: Path,
    limit_per_table: int,
    include_auxiliary: bool,
) -> dict[str, Any]:
    dual_match = _read_json(dual_match_path)
    account_sync = _read_json(account_sync_path)
    broker_sync = _read_json(broker_sync_path)
    mismatches, mismatch_source = _select_mismatch_rows(dual_match=dual_match, account_sync=account_sync)
    symbols = [str(row["symbol"]) for row in mismatches]
    report: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "db_path": str(db_path),
        "source_reports": {
            "dual_account_match": str(dual_match_path),
            "paper_account_sync": str(account_sync_path),
            "broker_paper_sync": str(broker_sync_path),
        },
        "dual_account_status": dual_match.get("status") or dual_match.get("comparison", {}).get("status"),
        "paper_account_sync_status": account_sync.get("comparison", {}).get("status"),
        "mismatch_source_report": mismatch_source,
        "broker_sync": _broker_sync_summary(broker_sync),
        "mismatch_count": len(symbols),
        "mismatch_rows": mismatches,
        "symbols": symbols,
        "table_traces": {},
        "assessment": {
            "status": "ok" if not symbols else "needs_review",
            "summary": "no mismatched symbols" if not symbols else "local/broker position mismatch requires ledger review",
        },
    }
    if not db_path.exists():
        report["assessment"] = {"status": "blocked", "summary": "database path missing"}
        return report
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    infos = _table_infos(conn, include_auxiliary=include_auxiliary)
    report["scanned_tables"] = [
        {"name": info.name, "symbol_column": info.symbol_column, "time_column": info.time_column}
        for info in infos
    ]
    mismatch_by_symbol = {str(row["symbol"]): row for row in mismatches}
    symbol_summaries: list[dict[str, Any]] = []
    for symbol in symbols:
        symbol_trace: dict[str, Any] = {}
        for info in infos:
            rows = _query_symbol_rows(conn, info, symbol, limit_per_table=limit_per_table)
            if rows:
                symbol_trace[info.name] = rows
        report["table_traces"][symbol] = symbol_trace
        symbol_summaries.append(
            _summarize_symbol_trace(
                mismatch_by_symbol[symbol],
                symbol_trace,
                broker_sync_status=report.get("broker_sync", {}).get("status"),
            )
        )
    report["symbol_summaries"] = symbol_summaries
    unknown_close_count = sum(
        1 for item in symbol_summaries if item.get("likely_issue") == "close_order_fill_unknown_due_rate_limit"
    )
    if unknown_close_count:
        report["assessment"] = {
            "status": "needs_review",
            "summary": f"{unknown_close_count} symbol(s) likely have close-order fill recovery blocked by broker rate limit",
        }
    return report


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join("" if value is None else str(value) for value in row) + " |")
    return "\n".join(lines)


def render_markdown(report: dict[str, Any]) -> str:
    rows = []
    for row in report.get("mismatch_rows", []):
        rows.append(
            [
                row.get("symbol"),
                row.get("status"),
                row.get("local_qty"),
                row.get("broker_qty"),
                row.get("qty_gap"),
                row.get("local_market_value"),
            ]
        )
    lines = [
        "# Paper/KIS Mismatch Trace",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- assessment: `{report.get('assessment', {}).get('status')}`",
        f"- summary: {report.get('assessment', {}).get('summary')}",
        f"- mismatch_count: `{report.get('mismatch_count')}`",
        f"- mismatch_source_report: `{report.get('mismatch_source_report')}`",
        f"- dual_account_status: `{report.get('dual_account_status')}`",
        f"- paper_account_sync_status: `{report.get('paper_account_sync_status')}`",
        f"- broker_sync_status: `{report.get('broker_sync', {}).get('status')}`",
        f"- broker_open_order_count: `{report.get('broker_sync', {}).get('open_order_count')}`",
        "",
        "## Mismatches",
        "",
        _markdown_table(
            ["symbol", "status", "local_qty", "broker_qty", "qty_gap", "local_market_value"],
            rows,
        )
        if rows
        else "No mismatches.",
        "",
        "## Symbol Summary",
        "",
    ]
    summary_rows = []
    for item in report.get("symbol_summaries", []):
        latest_local_order = item.get("latest_local_order") or {}
        latest_broker_submission = item.get("latest_broker_submission") or {}
        summary_rows.append(
            [
                item.get("symbol"),
                item.get("likely_issue"),
                item.get("local_qty"),
                item.get("broker_qty"),
                latest_local_order.get("side"),
                latest_local_order.get("status"),
                latest_local_order.get("event_time"),
                latest_broker_submission.get("side"),
                latest_broker_submission.get("status"),
                latest_broker_submission.get("event_time"),
            ]
        )
    lines.extend(
        [
            _markdown_table(
                [
                    "symbol",
                    "likely_issue",
                    "local_qty",
                    "broker_qty",
                    "local_side",
                    "local_status",
                    "local_time",
                    "broker_side",
                    "broker_status",
                    "broker_time",
                ],
                summary_rows,
            )
            if summary_rows
            else "No symbol summaries.",
            "",
        "## Ledger Snippets",
        "",
        ]
    )
    traces = report.get("table_traces", {})
    for symbol in report.get("symbols", []):
        lines.extend([f"### {symbol}", ""])
        symbol_trace = traces.get(symbol, {})
        if not symbol_trace:
            lines.extend(["No symbol rows found in scanned ledger tables.", ""])
            continue
        for table, table_rows in symbol_trace.items():
            lines.append(f"- `{table}`: {len(table_rows)} row(s)")
            for row in table_rows[:3]:
                compact = {key: row[key] for key in list(row)[:10]}
                lines.append(f"  - `{json.dumps(compact, ensure_ascii=False, default=str)}`")
            lines.append("")
    lines.extend(
        [
            "## Interpretation Guardrails",
            "",
            "- This report is read-only and does not align or mutate account state.",
            "- If broker sync is rate-limited, local-only positions can mean missing broker fills, stale local state, or both.",
            "- Do not apply marker-only alignment until the order/fill path for each mismatched symbol is understood.",
            "",
            "관련 문서/코드 경로:",
            "`scripts/trace_paper_kis_mismatch.py`,",
            "`runtime-data/reports/reconciliation/latest-paper-dual-account-match.json`,",
            "`runtime-data/reports/broker-paper/latest-sync.json`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--dual-match-path", type=Path, default=DEFAULT_DUAL_MATCH_PATH)
    parser.add_argument("--account-sync-path", type=Path, default=DEFAULT_ACCOUNT_SYNC_PATH)
    parser.add_argument("--broker-sync-path", type=Path, default=DEFAULT_BROKER_SYNC_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit-per-table", type=int, default=12)
    parser.add_argument(
        "--include-auxiliary",
        action="store_true",
        help="Also scan auxiliary symbol tables such as raw ticks and serving signals.",
    )
    args = parser.parse_args()

    report = build_trace_report(
        db_path=args.db_path,
        dual_match_path=args.dual_match_path,
        account_sync_path=args.account_sync_path,
        broker_sync_path=args.broker_sync_path,
        limit_per_table=max(1, args.limit_per_table),
        include_auxiliary=args.include_auxiliary,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "latest-paper-kis-mismatch-trace.json"
    md_path = args.output_dir / "latest-paper-kis-mismatch-trace.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"ok": True, "json_path": str(json_path), "markdown_path": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
