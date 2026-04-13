"""Cleanup helpers for removing non-actual runtime rows from serving and paper tables."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from pathlib import Path

from app.config.settings import load_settings
from app.observability.logging import configure_logging
from app.services.runtime_scope import build_runtime_scope, is_actual_row
from app.storage.runtime_writer import get_sqlite_store


@dataclass(slots=True)
class RuntimeCleanupResult:
    runtime_root: Path
    database_path: Path
    deleted_rows: dict[str, int]
    kept_actual_order_ids: int
    kept_actual_snapshots: int

    def to_dict(self) -> dict[str, object]:
        return {
            "runtime_root": str(self.runtime_root),
            "database_path": str(self.database_path),
            "deleted_rows": self.deleted_rows,
            "kept_actual_order_ids": self.kept_actual_order_ids,
            "kept_actual_snapshots": self.kept_actual_snapshots,
        }


def cleanup_non_actual_runtime_rows(project_root: Path) -> RuntimeCleanupResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for cleanup.")

    scope = build_runtime_scope(sqlite_store, settings)
    deleted_rows: dict[str, int] = {}
    table_order = [
        ("serving_predictions", "event_time"),
        ("serving_trade_signals", "event_time"),
        ("serving_target_positions", "event_time"),
        ("paper_orders", "event_time"),
        ("paper_order_events", "event_time"),
        ("paper_fills", "event_time"),
        ("paper_positions", "updated_at"),
        ("paper_portfolio_snapshots", "event_time"),
        ("ops_risk_events", "event_time"),
        ("ops_reconciliation_runs", "as_of"),
        ("ops_replay_runs", "as_of"),
    ]

    connection = sqlite3.connect(sqlite_store.database_path)
    connection.row_factory = sqlite3.Row
    try:
        for table_name, order_column in table_order:
            rows = connection.execute(
                f"SELECT rowid, * FROM {table_name} ORDER BY {order_column}"
            ).fetchall()
            delete_rowids: list[int] = []
            for row in rows:
                payload = dict(row)
                rowid = int(payload.pop("rowid"))
                if is_actual_row(
                    table_name,
                    payload,
                    actual_symbol_minutes=scope.actual_symbol_minutes,
                    actual_order_ids=scope.actual_order_ids,
                    actual_snapshot_ids=scope.actual_snapshot_ids,
                    actual_position_symbols=scope.actual_position_symbols,
                    actual_global_minutes=scope.actual_global_minutes,
                ):
                    continue
                delete_rowids.append(rowid)
            if delete_rowids:
                connection.executemany(
                    f"DELETE FROM {table_name} WHERE rowid = ?",
                    [(rowid,) for rowid in delete_rowids],
                )
            deleted_rows[table_name] = len(delete_rowids)
        connection.commit()
    finally:
        connection.close()

    return RuntimeCleanupResult(
        runtime_root=settings.runtime_data_dir,
        database_path=sqlite_store.database_path,
        deleted_rows=deleted_rows,
        kept_actual_order_ids=len(scope.actual_order_ids),
        kept_actual_snapshots=len(scope.actual_snapshot_ids),
    )
