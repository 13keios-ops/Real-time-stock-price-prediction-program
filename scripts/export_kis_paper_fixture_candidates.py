#!/usr/bin/env python3
"""Export redacted KIS paper response fixture candidates from runtime SQLite.

This script is intentionally offline/read-only for the database. It never calls
KIS and only writes a redacted JSON report inside the repository.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.brokers.kis_response_redaction import find_unredacted_sensitive_paths, redact_kis_payload


DEFAULT_DATABASE_PATH = Path("runtime-data/dev.db")
DEFAULT_OUTPUT_PATH = Path(
    "runtime-data/reports/codex/ops/kis-fixture-candidates/latest-kis-paper-fixture-candidates.json"
)
TABLE_SPECS = {
    "broker_paper_order_submissions": {
        "time_column": "event_time",
        "detail_column": "detail_json",
    },
    "broker_paper_order_status_snapshots": {
        "time_column": "synced_at",
        "detail_column": "detail_json",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-path", default=str(DEFAULT_DATABASE_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument(
        "--fail-on-redaction-findings",
        action="store_true",
        help="Exit non-zero when any sensitive-looking key remains unredacted after export.",
    )
    args = parser.parse_args()

    repo_root = Path.cwd().resolve()
    database_path = _resolve_inside_repo(args.database_path, repo_root, "database_path")
    output_path = _resolve_inside_repo(args.output_path, repo_root, "output_path")
    if not database_path.exists():
        raise SystemExit(f"database_path does not exist: {database_path}")

    payload = export_fixture_candidates(database_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = _summary(payload, output_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_redaction_findings and not summary["redaction_ok"]:
        raise SystemExit("redaction findings detected")
    return 0


def export_fixture_candidates(database_path: Path) -> dict[str, Any]:
    connection = _connect_read_only(database_path)
    try:
        tables = _table_names(connection)
        payload: dict[str, Any] = {
            "generated_at": datetime.now().astimezone().isoformat(),
            "source": "runtime-data/dev.db read-only export from KIS paper trading records",
            "database_path": _display_path(database_path),
            "tables": {},
            "notes": [
                "KIS live account/order APIs were not called.",
                "Values are key-redacted by app.brokers.kis_response_redaction.redact_kis_payload().",
                "Order identifiers and stock codes are preserved for mapper verification; review before external sharing.",
            ],
        }
        for table_name, spec in TABLE_SPECS.items():
            if table_name not in tables:
                payload["tables"][table_name] = {"present": False, "row_count": 0}
                continue
            payload["tables"][table_name] = _export_table(connection, table_name, spec)
        return payload
    finally:
        connection.close()


def _export_table(connection: sqlite3.Connection, table_name: str, spec: dict[str, str]) -> dict[str, Any]:
    time_column = spec["time_column"]
    detail_column = spec["detail_column"]
    columns = _column_names(connection, table_name)
    if detail_column not in columns:
        return {"present": True, "row_count": _count_rows(connection, table_name), "error": "detail_json column missing"}
    result: dict[str, Any] = {
        "present": True,
        "row_count": _count_rows(connection, table_name),
        "detail_column": detail_column,
    }
    if result["row_count"] == 0:
        return result

    latest_row = _fetch_one(
        connection,
        f'SELECT rowid, {detail_column} FROM "{table_name}" ORDER BY "{time_column}" DESC, rowid DESC LIMIT 1',
    )
    richest_row = _fetch_one(
        connection,
        f'SELECT rowid, {detail_column} FROM "{table_name}" ORDER BY LENGTH(COALESCE("{detail_column}", "")) DESC, rowid DESC LIMIT 1',
    )
    result["latest_candidate"] = _candidate("latest", latest_row, detail_column)
    result["richest_detail_candidate"] = _candidate("richest_detail", richest_row, detail_column)
    return result


def _candidate(selector: str, row: sqlite3.Row | None, detail_column: str) -> dict[str, Any] | None:
    if row is None:
        return None
    detail = _load_detail_json(row[detail_column])
    redacted = redact_kis_payload(detail)
    redaction_findings = find_unredacted_sensitive_paths(redacted)
    return {
        "selector": selector,
        "source_rowid": int(row["rowid"]),
        "redacted_detail_json": redacted,
        "redacted_value_count": json.dumps(redacted, ensure_ascii=False).count("<REDACTED>"),
        "redaction_findings": redaction_findings,
        "redaction_ok": not redaction_findings,
    }


def _load_detail_json(value: Any) -> Any:
    if value is None or value == "":
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError as exc:
        return {"_invalid_json": True, "error": str(exc)}


def _connect_read_only(database_path: Path) -> sqlite3.Connection:
    uri = f"file:{database_path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row["name"]) for row in rows}


def _column_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return {str(row["name"]) for row in rows}


def _count_rows(connection: sqlite3.Connection, table_name: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) AS count FROM "{table_name}"').fetchone()["count"])


def _fetch_one(connection: sqlite3.Connection, sql: str) -> sqlite3.Row | None:
    return connection.execute(sql).fetchone()


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


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _summary(payload: dict[str, Any], output_path: Path) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for table_name, table_payload in payload.get("tables", {}).items():
        candidates = {}
        for key, candidate in table_payload.items():
            if not key.endswith("_candidate") or not isinstance(candidate, dict):
                continue
            detail = candidate.get("redacted_detail_json")
            if isinstance(detail, dict):
                detail_keys = sorted(detail.keys())
            else:
                detail_keys = []
            candidates[key] = {
                "redacted_value_count": candidate.get("redacted_value_count", 0),
                "redaction_ok": candidate.get("redaction_ok", False),
                "redaction_findings_count": len(candidate.get("redaction_findings", [])),
                "detail_keys": detail_keys,
            }
        tables[table_name] = {
            "present": table_payload.get("present", False),
            "row_count": table_payload.get("row_count", 0),
            "candidates": candidates,
        }
    all_redaction_ok = all(
        candidate.get("redaction_ok", False)
        for table_payload in tables.values()
        for candidate in table_payload["candidates"].values()
    )
    return {
        "status": "ok" if all_redaction_ok else "needs_review",
        "redaction_ok": all_redaction_ok,
        "output_path": _display_path(output_path),
        "tables": tables,
    }


if __name__ == "__main__":
    raise SystemExit(main())
