#!/usr/bin/env python3
"""Rebuild feature JSONL artifacts from the canonical SQLite feature tables.

The runtime JSONL feature files are append-only convenience artifacts. Offline
dataset reconstruction historically replayed the same rows into them, so this
tool rebuilds that directory from SQLite primary keys instead of guessing which
duplicate JSONL row should win. It never reads or changes raw market data,
orders, fills, model policy, or broker state.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DATA_DIR = REPO_ROOT / "runtime-data"
DEFAULT_DATABASE_PATH = DEFAULT_RUNTIME_DATA_DIR / "dev.db"
DEFAULT_REPORT_NAME = "latest-feature-jsonl-rebuild.json"


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    table_name: str
    filename: str
    query: str


ARTIFACT_SPECS = (
    ArtifactSpec(
        name="model_inputs",
        table_name="feature_model_inputs",
        filename="model_inputs.jsonl",
        query=(
            "SELECT symbol, event_time, feature_set_version, values_json "
            "FROM feature_model_inputs ORDER BY event_time, symbol, feature_set_version"
        ),
    ),
    ArtifactSpec(
        name="labels",
        table_name="feature_labels",
        filename="labels.jsonl",
        query=(
            "SELECT symbol, event_time, horizon_min, label, threshold_pct, future_return_pct "
            "FROM feature_labels ORDER BY event_time, symbol, horizon_min"
        ),
    ),
)


def _now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _json_default(value: Any) -> str:
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _safe_runtime_dir(runtime_data_dir: Path) -> Path:
    runtime_dir = runtime_data_dir.resolve()
    if runtime_dir.name != "runtime-data":
        raise ValueError("runtime_data_dir must be the repository runtime-data directory")
    return runtime_dir


def _safe_feature_dir(runtime_dir: Path) -> Path:
    feature_dir = runtime_dir / "feature"
    if feature_dir.exists() and feature_dir.is_symlink():
        raise ValueError("feature directory must not be a symbolic link")
    return feature_dir


def _connect_readonly(database_path: Path) -> sqlite3.Connection:
    if not database_path.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {database_path}")
    connection = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _require_feature_tables(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?)",
        tuple(spec.table_name for spec in ARTIFACT_SPECS),
    ).fetchall()
    available = {str(row["name"]) for row in rows}
    missing = [spec.table_name for spec in ARTIFACT_SPECS if spec.table_name not in available]
    if missing:
        raise RuntimeError(f"SQLite feature tables missing: {', '.join(missing)}")


def _record_from_row(spec: ArtifactSpec, row: sqlite3.Row) -> dict[str, Any]:
    if spec.name == "model_inputs":
        try:
            values = json.loads(str(row["values_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Invalid values_json for {row['symbol']} at {row['event_time']}"
            ) from exc
        if not isinstance(values, dict):
            raise RuntimeError(f"values_json must be an object for {row['symbol']} at {row['event_time']}")
        return {
            "symbol": row["symbol"],
            "event_time": row["event_time"],
            "feature_set_version": row["feature_set_version"],
            "values": values,
        }
    return {
        "symbol": row["symbol"],
        "event_time": row["event_time"],
        "horizon_min": row["horizon_min"],
        "label": row["label"],
        "threshold_pct": row["threshold_pct"],
        "future_return_pct": row["future_return_pct"],
    }


def _source_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        spec.name: int(
            connection.execute(f"SELECT COUNT(*) AS row_count FROM {spec.table_name}").fetchone()["row_count"]
        )
        for spec in ARTIFACT_SPECS
    }


def _artifact_file_stats(feature_dir: Path) -> dict[str, int]:
    if not feature_dir.exists():
        return {"file_count": 0, "bytes": 0}
    files = [path for path in feature_dir.rglob("*.jsonl") if path.is_file()]
    return {"file_count": len(files), "bytes": sum(path.stat().st_size for path in files)}


def _write_stage(connection: sqlite3.Connection, stage_dir: Path) -> dict[str, int]:
    counts = {spec.name: 0 for spec in ARTIFACT_SPECS}
    handles: dict[tuple[str, str], Any] = {}
    try:
        for spec in ARTIFACT_SPECS:
            cursor = connection.execute(spec.query)
            for row in cursor:
                event_time = str(row["event_time"])
                day = event_time[:10]
                if len(day) != 10:
                    raise RuntimeError(f"Invalid event_time for {spec.name}: {event_time}")
                key = (spec.name, day)
                handle = handles.get(key)
                if handle is None:
                    path = stage_dir / day / spec.filename
                    path.parent.mkdir(parents=True, exist_ok=True)
                    handle = path.open("w", encoding="utf-8", newline="\n")
                    handles[key] = handle
                handle.write(json.dumps(_record_from_row(spec, row), ensure_ascii=False, default=_json_default))
                handle.write("\n")
                counts[spec.name] += 1
    finally:
        for handle in handles.values():
            handle.close()
    return counts


def _verify_stage(stage_dir: Path, expected_counts: dict[str, int]) -> dict[str, int]:
    actual = {spec.name: 0 for spec in ARTIFACT_SPECS}
    filenames = {spec.filename: spec.name for spec in ARTIFACT_SPECS}
    for path in sorted(stage_dir.rglob("*.jsonl")):
        artifact_name = filenames.get(path.name)
        if artifact_name is None:
            raise RuntimeError(f"Unexpected JSONL artifact in stage: {path}")
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    raise RuntimeError(f"Blank JSONL line in stage: {path}:{line_number}")
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise RuntimeError(f"Non-object JSONL record in stage: {path}:{line_number}")
                actual[artifact_name] += 1
    if actual != expected_counts:
        raise RuntimeError(f"Stage row counts differ from SQLite source: expected={expected_counts} actual={actual}")
    return actual


def _safe_remove_backup(runtime_dir: Path, backup_dir: Path) -> None:
    if backup_dir.parent.resolve() != runtime_dir.resolve() or not backup_dir.name.startswith(".feature-precanonical-"):
        raise ValueError(f"Refusing to remove unsafe backup path: {backup_dir}")
    if backup_dir.is_symlink():
        raise ValueError(f"Refusing to remove symlink backup: {backup_dir}")
    shutil.rmtree(backup_dir)


def _write_report(runtime_dir: Path, report: dict[str, Any]) -> Path:
    report_path = runtime_dir / "reports" / "storage" / DEFAULT_REPORT_NAME
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_path, report_path)
    return report_path


def rebuild_feature_jsonl(
    *,
    runtime_data_dir: Path,
    database_path: Path,
    execute: bool,
    discard_backup: bool,
) -> dict[str, Any]:
    runtime_dir = _safe_runtime_dir(runtime_data_dir)
    feature_dir = _safe_feature_dir(runtime_dir)
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "dry_run",
        "execute": execute,
        "runtime_data_dir": str(runtime_dir),
        "database_path": str(database_path.resolve()),
        "target_feature_dir": str(feature_dir),
        "before": _artifact_file_stats(feature_dir),
        "discard_backup": discard_backup,
    }
    with _connect_readonly(database_path.resolve()) as connection:
        _require_feature_tables(connection)
        source_counts = _source_counts(connection)
        report["source_rows"] = source_counts
        if not execute:
            report["after"] = report["before"]
            report["summary"] = "dry run only; no JSONL artifact was changed"
            report["report_path"] = str(_write_report(runtime_dir, report))
            return report

        stage_dir = runtime_dir / f".feature-canonical-stage-{_now_id()}-{uuid.uuid4().hex[:8]}"
        backup_dir = runtime_dir / f".feature-precanonical-{_now_id()}-{uuid.uuid4().hex[:8]}"
        if stage_dir.exists() or backup_dir.exists():
            raise RuntimeError("Unexpected feature rebuild staging path already exists")
        stage_dir.mkdir(parents=True)
        try:
            written_counts = _write_stage(connection, stage_dir)
            verified_counts = _verify_stage(stage_dir, source_counts)
            if written_counts != source_counts or verified_counts != source_counts:
                raise RuntimeError("Feature artifact write verification failed")

            moved_old_feature = False
            if feature_dir.exists():
                feature_dir.rename(backup_dir)
                moved_old_feature = True
            try:
                stage_dir.rename(feature_dir)
            except Exception:
                if moved_old_feature and backup_dir.exists() and not feature_dir.exists():
                    backup_dir.rename(feature_dir)
                raise

            report.update(
                {
                    "status": "ok",
                    "written_rows": written_counts,
                    "verified_rows": verified_counts,
                    "after": _artifact_file_stats(feature_dir),
                    "backup_path": str(backup_dir) if moved_old_feature else None,
                    "backup_retained": moved_old_feature,
                }
            )
            if moved_old_feature and discard_backup:
                _safe_remove_backup(runtime_dir, backup_dir)
                report["backup_retained"] = False
                report["backup_removed"] = True
            report["summary"] = "feature JSONL rebuilt from canonical SQLite primary keys"
        except Exception:
            if stage_dir.exists():
                report["failed_stage_path"] = str(stage_dir)
            raise
    report["report_path"] = str(_write_report(runtime_dir, report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-data-dir", type=Path, default=DEFAULT_RUNTIME_DATA_DIR)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Rebuild and replace runtime-data/feature after SQLite-based verification.",
    )
    parser.add_argument(
        "--discard-backup",
        action="store_true",
        help="Remove the renamed pre-rebuild feature directory after the new artifact is verified.",
    )
    args = parser.parse_args()
    if args.discard_backup and not args.execute:
        parser.error("--discard-backup requires --execute")
    try:
        report = rebuild_feature_jsonl(
            runtime_data_dir=args.runtime_data_dir,
            database_path=args.database_path,
            execute=args.execute,
            discard_backup=args.discard_backup,
        )
    except (FileNotFoundError, RuntimeError, ValueError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
