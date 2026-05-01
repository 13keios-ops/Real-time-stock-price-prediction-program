"""Helpers for separating actual runtime data from demo or research artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config.settings import AppSettings
from app.storage.sqlite_store import SQLiteRuntimeStore
from app.utils.time import get_market_session_status

ACTUAL_RAW_SOURCES = frozenset({"kis-rest", "kis-ws"})
TEST_ID_MARKERS = ("demo", "replay")


def minute_key(value: str | None) -> str | None:
    if not value:
        return None
    return str(value)[:16]


def _has_test_marker(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in TEST_ID_MARKERS)


@dataclass(slots=True)
class RuntimeScope:
    actual_symbol_minutes: set[tuple[str, str]]
    actual_global_minutes: set[str]
    actual_order_ids: set[str]
    actual_snapshot_ids: set[str]
    actual_position_symbols: set[str]


def _is_regular_session_timestamp(timestamp_text: str | None, settings: AppSettings) -> bool:
    if not timestamp_text:
        return False
    try:
        timestamp = datetime.fromisoformat(str(timestamp_text))
    except ValueError:
        return False
    return get_market_session_status(settings.market_calendar, timestamp) == "regular-session"


def build_runtime_scope(sqlite_store: SQLiteRuntimeStore, settings: AppSettings) -> RuntimeScope:
    raw_market_rows = [dict(row) for row in sqlite_store.fetch_all_rows("raw_market_ticks", "event_time")]
    raw_orderbook_rows = [dict(row) for row in sqlite_store.fetch_all_rows("raw_orderbook_ticks", "event_time")]
    symbol_minute_sources: dict[tuple[str, str], set[str]] = {}
    for row in [*raw_market_rows, *raw_orderbook_rows]:
        if not _is_regular_session_timestamp(str(row.get("event_time", "")), settings):
            continue
        minute = minute_key(row.get("event_time"))
        if minute is None:
            continue
        key = (str(row["symbol"]), minute)
        symbol_minute_sources.setdefault(key, set()).add(str(row.get("source", "")).lower())

    actual_symbol_minutes = {
        key
        for key, sources in symbol_minute_sources.items()
        if sources and sources.issubset(ACTUAL_RAW_SOURCES)
    }
    actual_global_minutes = {minute for _, minute in actual_symbol_minutes}

    actual_orders = [
        dict(row)
        for row in sqlite_store.fetch_all_rows("paper_orders", "event_time")
        if is_actual_row("paper_orders", dict(row), actual_symbol_minutes=actual_symbol_minutes)
    ]
    actual_order_ids = {str(row["order_id"]) for row in actual_orders}
    actual_order_minutes = {minute_key(str(row["event_time"])) for row in actual_orders if row.get("event_time")}
    actual_fill_minutes = {
        minute_key(str(row["event_time"]))
        for row in [dict(row) for row in sqlite_store.fetch_all_rows("paper_fills", "event_time")]
        if str(row.get("order_id", "")) in actual_order_ids and row.get("event_time")
    }
    actual_account_minutes = {minute for minute in [*actual_order_minutes, *actual_fill_minutes] if minute}
    actual_snapshot_ids = {
        str(row["snapshot_id"])
        for row in sqlite_store.fetch_all_rows("paper_portfolio_snapshots", "event_time")
        if is_actual_row(
            "paper_portfolio_snapshots",
            dict(row),
            actual_symbol_minutes=actual_symbol_minutes,
            actual_order_ids=actual_order_ids,
            actual_global_minutes=actual_global_minutes,
            actual_order_minutes=actual_account_minutes,
        )
    }
    actual_position_symbols = {str(row["symbol"]) for row in actual_orders}
    return RuntimeScope(
        actual_symbol_minutes=actual_symbol_minutes,
        actual_global_minutes=actual_global_minutes,
        actual_order_ids=actual_order_ids,
        actual_snapshot_ids=actual_snapshot_ids,
        actual_position_symbols=actual_position_symbols,
    )


def is_actual_row(
    table_name: str,
    row: dict[str, Any],
    *,
    actual_symbol_minutes: set[tuple[str, str]],
    actual_order_ids: set[str] | None = None,
    actual_snapshot_ids: set[str] | None = None,
    actual_position_symbols: set[str] | None = None,
    actual_global_minutes: set[str] | None = None,
    actual_order_minutes: set[str] | None = None,
) -> bool:
    table = str(table_name)

    if table == "raw_market_ticks" or table == "raw_orderbook_ticks":
        symbol = str(row.get("symbol", ""))
        minute = minute_key(str(row.get("event_time", ""))) or ""
        return str(row.get("source", "")).lower() in ACTUAL_RAW_SOURCES and (symbol, minute) in actual_symbol_minutes

    if table in {
        "curated_minute_bars",
        "feature_model_inputs",
        "feature_labels",
        "serving_predictions",
        "serving_trade_signals",
        "serving_target_positions",
        "paper_orders",
        "ops_risk_events",
    }:
        symbol = str(row.get("symbol", ""))
        time_value = row.get("bar_time") or row.get("event_time")
        key = (symbol, minute_key(str(time_value)) or "")
        if key not in actual_symbol_minutes:
            return False
        id_keys = {
            "serving_predictions": "prediction_id",
            "serving_trade_signals": "signal_id",
            "serving_target_positions": "target_id",
            "paper_orders": "order_id",
            "ops_risk_events": "risk_event_id",
        }
        id_key = id_keys.get(table)
        return not id_key or not _has_test_marker(row.get(id_key))

    if table == "paper_order_events" or table == "paper_fills":
        if actual_order_ids is None:
            return False
        order_id = str(row.get("order_id", ""))
        return order_id in actual_order_ids and not _has_test_marker(row.get("fill_id", ""))

    if table == "broker_paper_order_submissions":
        if actual_order_ids is None:
            return False
        local_order_id = str(row.get("local_order_id", ""))
        return local_order_id in actual_order_ids and not _has_test_marker(row.get("submission_id", ""))

    if table == "paper_positions":
        if actual_position_symbols is None:
            return False
        return str(row.get("symbol", "")) in actual_position_symbols

    if table == "paper_portfolio_snapshots":
        if actual_snapshot_ids is not None:
            return str(row.get("snapshot_id", "")) in actual_snapshot_ids
        if actual_order_minutes is None:
            return False
        snapshot_id = str(row.get("snapshot_id", ""))
        event_minute = minute_key(str(row.get("event_time", "")))
        return not _has_test_marker(snapshot_id) and event_minute in actual_order_minutes

    if table in {"ops_reconciliation_runs", "ops_replay_runs"}:
        if actual_global_minutes is None:
            return False
        id_key = "reconciliation_id" if table == "ops_reconciliation_runs" else "replay_id"
        as_of = minute_key(str(row.get("as_of", "")))
        return not _has_test_marker(row.get(id_key)) and as_of in actual_global_minutes

    return True


def filter_actual_rows(
    table_name: str,
    rows: list[dict[str, Any]],
    scope: RuntimeScope,
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if is_actual_row(
            table_name,
            row,
            actual_symbol_minutes=scope.actual_symbol_minutes,
            actual_order_ids=scope.actual_order_ids,
            actual_snapshot_ids=scope.actual_snapshot_ids,
            actual_position_symbols=scope.actual_position_symbols,
            actual_global_minutes=scope.actual_global_minutes,
        )
    ]
