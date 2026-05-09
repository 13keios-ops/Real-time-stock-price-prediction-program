#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ACTUAL_RAW_SOURCES = ("kis-ws", "kis-rest")
DEFAULT_OUTPUT_NAME = "latest-kis-live-data-quality"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _database_path_from_env(default_path: Path) -> Path:
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///")).expanduser()
    return default_path


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _fetch_scalar(connection: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> Any:
    row = connection.execute(query, params).fetchone()
    if row is None:
        return None
    return row[0]


def _round_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 6)


def _source_clause(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"{prefix}source IN ({', '.join('?' for _ in ACTUAL_RAW_SOURCES)})"


def _source_summary(connection: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    if not _table_exists(connection, table_name):
        return []
    query = f"""
        SELECT
            source,
            COUNT(*) AS rows,
            COUNT(DISTINCT symbol) AS symbols,
            COUNT(DISTINCT substr(event_time, 1, 10)) AS trade_dates,
            MIN(event_time) AS first_event_time,
            MAX(event_time) AS last_event_time
        FROM {table_name}
        WHERE {_source_clause()}
        GROUP BY source
        ORDER BY source
    """
    return [dict(row) for row in connection.execute(query, ACTUAL_RAW_SOURCES)]


def _date_bounds(trade_date: str) -> tuple[str, str]:
    start_date = date.fromisoformat(trade_date)
    end_date = start_date + timedelta(days=1)
    return start_date.isoformat(), end_date.isoformat()


def _raw_minute_index(
    connection: sqlite3.Connection,
    table_name: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, int]], dict[str, dict[str, set[str]]]]:
    day_stats: dict[str, dict[str, Any]] = {}
    symbol_minutes: dict[str, dict[str, int]] = {}
    actual_minutes: dict[str, dict[str, set[str]]] = {}
    if not _table_exists(connection, table_name):
        return day_stats, symbol_minutes, actual_minutes
    query = f"""
        SELECT
            symbol,
            substr(event_time, 1, 16) AS minute_key,
            source,
            MIN(event_time) AS sample_time,
            COUNT(*) AS row_count
        FROM {table_name}
        WHERE {_source_clause()}
        GROUP BY symbol, minute_key, source
        ORDER BY minute_key, symbol
    """
    for row in connection.execute(query, ACTUAL_RAW_SOURCES):
        symbol = str(row["symbol"])
        minute_key = str(row["minute_key"])
        trade_date = minute_key[:10]
        row_count = int(row["row_count"] or 0)
        sample_time = str(row["sample_time"] or "")
        stats = day_stats.setdefault(
            trade_date,
            {"rows": 0, "symbol_minutes": 0, "_symbols": set(), "first_time": None, "last_time": None},
        )
        stats["rows"] = int(stats["rows"]) + row_count
        stats["symbol_minutes"] = int(stats["symbol_minutes"]) + 1
        stats["_symbols"].add(symbol)
        if sample_time:
            if stats["first_time"] is None or sample_time < stats["first_time"]:
                stats["first_time"] = sample_time
            if stats["last_time"] is None or sample_time > stats["last_time"]:
                stats["last_time"] = sample_time
        symbol_minutes.setdefault(trade_date, {}).setdefault(symbol, 0)
        symbol_minutes[trade_date][symbol] += 1
        actual_minutes.setdefault(trade_date, {}).setdefault(symbol, set()).add(minute_key)

    for stats in day_stats.values():
        symbols = stats.pop("_symbols", set())
        stats["symbols"] = len(symbols)
    return day_stats, symbol_minutes, actual_minutes


def _merge_actual_minutes(
    left: dict[str, dict[str, set[str]]],
    right: dict[str, dict[str, set[str]]],
) -> dict[str, dict[str, set[str]]]:
    merged: dict[str, dict[str, set[str]]] = {
        trade_date: {symbol: set(minutes) for symbol, minutes in by_symbol.items()}
        for trade_date, by_symbol in left.items()
    }
    for trade_date, by_symbol in right.items():
        target = merged.setdefault(trade_date, {})
        for symbol, minutes in by_symbol.items():
            target.setdefault(symbol, set()).update(minutes)
    return merged


def _query_actual_symbol_rows(
    connection: sqlite3.Connection,
    table_name: str,
    time_column: str,
    trade_date: str,
    actual_minutes_by_symbol: dict[str, set[str]],
    *,
    horizon_min: int | None = None,
    label_distribution: bool = False,
) -> tuple[dict[str, Any], dict[str, int], dict[str, int]]:
    if not actual_minutes_by_symbol or not _table_exists(connection, table_name):
        return {"rows": 0, "symbols": 0, "symbol_minutes": 0}, {}, {}
    start_at, end_at = _date_bounds(trade_date)
    total_rows = 0
    symbols_with_rows: set[str] = set()
    symbol_minute_counts: dict[str, int] = {}
    label_counts: Counter[str] = Counter()
    fields = [time_column]
    if label_distribution:
        fields.append("label")
    query = f"""
        SELECT {', '.join(fields)}
        FROM {table_name}
        WHERE symbol = ?
          AND {time_column} >= ?
          AND {time_column} < ?
    """
    params_tail: tuple[Any, ...] = ()
    if horizon_min is not None:
        query += " AND horizon_min = ?"
        params_tail = (horizon_min,)
    for symbol, actual_minutes in actual_minutes_by_symbol.items():
        if not actual_minutes:
            continue
        seen_minutes: set[str] = set()
        params = (symbol, start_at, end_at, *params_tail)
        for row in connection.execute(query, params):
            minute_key = str(row[time_column])[:16]
            if minute_key not in actual_minutes:
                continue
            total_rows += 1
            seen_minutes.add(minute_key)
            symbols_with_rows.add(symbol)
            if label_distribution:
                label_counts[str(row["label"])] += 1
        if seen_minutes:
            symbol_minute_counts[symbol] = len(seen_minutes)
    return (
        {"rows": total_rows, "symbols": len(symbols_with_rows), "symbol_minutes": sum(symbol_minute_counts.values())},
        symbol_minute_counts,
        dict(sorted(label_counts.items())),
    )


def _trade_dates(connection: sqlite3.Connection) -> list[str]:
    parts: list[str] = []
    if _table_exists(connection, "raw_market_ticks"):
        parts.append(
            "SELECT DISTINCT substr(event_time, 1, 10) AS trade_date "
            "FROM raw_market_ticks WHERE source IN (?, ?)"
        )
    if _table_exists(connection, "raw_orderbook_ticks"):
        parts.append(
            "SELECT DISTINCT substr(event_time, 1, 10) AS trade_date "
            "FROM raw_orderbook_ticks WHERE source IN (?, ?)"
        )
    if not parts:
        return []
    query = " UNION ".join(parts)
    params = ACTUAL_RAW_SOURCES * len(parts)
    return [
        str(row["trade_date"])
        for row in connection.execute(f"SELECT trade_date FROM ({query}) ORDER BY trade_date", params)
        if row["trade_date"]
    ]


def _date_filter(column: str, dates: list[str]) -> tuple[str, tuple[Any, ...]]:
    if not dates:
        return "1 = 0", ()
    return f"substr({column}, 1, 10) IN ({', '.join('?' for _ in dates)})", tuple(dates)


def _empty_day_stats() -> dict[str, Any]:
    return {"rows": 0, "symbols": 0, "symbol_minutes": 0, "first_time": None, "last_time": None}


def _raw_day_stats_by_date(
    connection: sqlite3.Connection,
    table_name: str,
    trade_dates: list[str],
) -> dict[str, dict[str, Any]]:
    if not trade_dates or not _table_exists(connection, table_name):
        return {}
    date_clause, date_params = _date_filter("event_time", trade_dates)
    query = f"""
        SELECT
            substr(event_time, 1, 10) AS trade_date,
            COUNT(*) AS rows,
            COUNT(DISTINCT symbol) AS symbols,
            COUNT(DISTINCT symbol || '|' || substr(event_time, 1, 16)) AS symbol_minutes,
            MIN(event_time) AS first_time,
            MAX(event_time) AS last_time
        FROM {table_name}
        WHERE {_source_clause()} AND {date_clause}
        GROUP BY trade_date
    """
    params = (*ACTUAL_RAW_SOURCES, *date_params)
    return {str(row["trade_date"]): dict(row) for row in connection.execute(query, params)}


def _raw_day_stats(connection: sqlite3.Connection, table_name: str, trade_date: str) -> dict[str, Any]:
    if not _table_exists(connection, table_name):
        return _empty_day_stats()
    query = f"""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT symbol) AS symbols,
            COUNT(DISTINCT symbol || '|' || substr(event_time, 1, 16)) AS symbol_minutes,
            MIN(event_time) AS first_time,
            MAX(event_time) AS last_time
        FROM {table_name}
        WHERE {_source_clause()} AND substr(event_time, 1, 10) = ?
    """
    return dict(connection.execute(query, (*ACTUAL_RAW_SOURCES, trade_date)).fetchone())


def _prepare_actual_minutes(connection: sqlite3.Connection, trade_dates: list[str]) -> None:
    connection.execute("DROP TABLE IF EXISTS temp_actual_minutes")
    connection.execute(
        """
        CREATE TEMP TABLE temp_actual_minutes (
            symbol TEXT NOT NULL,
            minute_key TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            PRIMARY KEY (symbol, minute_key)
        ) WITHOUT ROWID
        """
    )
    if not trade_dates:
        return
    date_clause, date_params = _date_filter("event_time", trade_dates)
    for table_name in ("raw_market_ticks", "raw_orderbook_ticks"):
        if not _table_exists(connection, table_name):
            continue
        query = f"""
            INSERT OR IGNORE INTO temp_actual_minutes(symbol, minute_key, trade_date)
            SELECT
                symbol,
                substr(event_time, 1, 16) AS minute_key,
                substr(event_time, 1, 10) AS trade_date
            FROM {table_name}
            WHERE {_source_clause()} AND {date_clause}
        """
        connection.execute(query, (*ACTUAL_RAW_SOURCES, *date_params))
    connection.execute("CREATE INDEX IF NOT EXISTS idx_temp_actual_minutes_date_symbol ON temp_actual_minutes(trade_date, symbol)")


def _actual_table_count(
    connection: sqlite3.Connection,
    table_name: str,
    time_column: str,
    trade_date: str,
    *,
    horizon_min: int | None = None,
) -> dict[str, Any]:
    if not _table_exists(connection, table_name):
        return {"rows": 0, "symbols": 0, "symbol_minutes": 0}
    extra_where = ""
    params: list[Any] = [trade_date]
    if horizon_min is not None:
        extra_where = " AND target.horizon_min = ?"
        params.append(horizon_min)
    query = f"""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT target.symbol) AS symbols,
            COUNT(DISTINCT target.symbol || '|' || substr(target.{time_column}, 1, 16)) AS symbol_minutes
        FROM {table_name} AS target
        JOIN temp_actual_minutes AS actual_minutes
          ON actual_minutes.symbol = target.symbol
         AND actual_minutes.minute_key = substr(target.{time_column}, 1, 16)
        WHERE actual_minutes.trade_date = ?
        {extra_where}
    """
    return dict(connection.execute(query, tuple(params)).fetchone())


def _label_distribution(connection: sqlite3.Connection, trade_date: str, horizon_min: int) -> dict[str, int]:
    if not _table_exists(connection, "feature_labels"):
        return {}
    query = f"""
        SELECT target.label, COUNT(*) AS rows
        FROM feature_labels AS target
        JOIN temp_actual_minutes AS actual_minutes
          ON actual_minutes.symbol = target.symbol
         AND actual_minutes.minute_key = substr(target.event_time, 1, 16)
        WHERE actual_minutes.trade_date = ?
          AND target.horizon_min = ?
        GROUP BY target.label
        ORDER BY target.label
    """
    return {
        str(row["label"]): int(row["rows"])
        for row in connection.execute(query, (trade_date, horizon_min))
    }


def _day_summary(
    connection: sqlite3.Connection,
    trade_date: str,
    *,
    raw_market_by_date: dict[str, dict[str, Any]],
    raw_orderbook_by_date: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    raw_market = raw_market_by_date.get(trade_date, _empty_day_stats())
    raw_orderbook = raw_orderbook_by_date.get(trade_date, _empty_day_stats())
    minute_bars = _actual_table_count(connection, "curated_minute_bars", "bar_time", trade_date)
    features = _actual_table_count(connection, "feature_model_inputs", "event_time", trade_date)
    labels_h15 = _actual_table_count(connection, "feature_labels", "event_time", trade_date, horizon_min=15)
    labels_h60 = _actual_table_count(connection, "feature_labels", "event_time", trade_date, horizon_min=60)
    predictions_h15 = _actual_table_count(connection, "serving_predictions", "event_time", trade_date, horizon_min=15)
    signals = _actual_table_count(connection, "serving_trade_signals", "event_time", trade_date)
    feature_symbol_minutes = int(features.get("symbol_minutes") or 0)
    return {
        "trade_date": trade_date,
        "raw_market": raw_market,
        "raw_orderbook": raw_orderbook,
        "minute_bars": minute_bars,
        "features": features,
        "labels_h15": labels_h15,
        "labels_h60": labels_h60,
        "predictions_h15": predictions_h15,
        "signals": signals,
        "label_distribution_h15": _label_distribution(connection, trade_date, 15),
        "feature_to_bar_symbol_minute_ratio": _round_ratio(
            int(features.get("symbol_minutes") or 0),
            int(minute_bars.get("symbol_minutes") or 0),
        ),
        "label_h15_to_feature_symbol_minute_ratio": _round_ratio(
            int(labels_h15.get("symbol_minutes") or 0),
            feature_symbol_minutes,
        ),
    }


def _day_summary_from_indexes(
    connection: sqlite3.Connection,
    trade_date: str,
    *,
    raw_market_by_date: dict[str, dict[str, Any]],
    raw_orderbook_by_date: dict[str, dict[str, Any]],
    actual_minutes_by_date: dict[str, dict[str, set[str]]],
) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    raw_market = raw_market_by_date.get(trade_date, _empty_day_stats())
    raw_orderbook = raw_orderbook_by_date.get(trade_date, _empty_day_stats())
    actual_minutes_by_symbol = actual_minutes_by_date.get(trade_date, {})
    minute_bars, minute_bar_symbols, _ = _query_actual_symbol_rows(
        connection, "curated_minute_bars", "bar_time", trade_date, actual_minutes_by_symbol
    )
    features, feature_symbols, _ = _query_actual_symbol_rows(
        connection, "feature_model_inputs", "event_time", trade_date, actual_minutes_by_symbol
    )
    labels_h15, label_h15_symbols, label_dist_h15 = _query_actual_symbol_rows(
        connection,
        "feature_labels",
        "event_time",
        trade_date,
        actual_minutes_by_symbol,
        horizon_min=15,
        label_distribution=True,
    )
    labels_h60, _, _ = _query_actual_symbol_rows(
        connection, "feature_labels", "event_time", trade_date, actual_minutes_by_symbol, horizon_min=60
    )
    predictions_h15, _, _ = _query_actual_symbol_rows(
        connection, "serving_predictions", "event_time", trade_date, actual_minutes_by_symbol, horizon_min=15
    )
    signals, _, _ = _query_actual_symbol_rows(
        connection, "serving_trade_signals", "event_time", trade_date, actual_minutes_by_symbol
    )
    feature_symbol_minutes = int(features.get("symbol_minutes") or 0)
    row = {
        "trade_date": trade_date,
        "raw_market": raw_market,
        "raw_orderbook": raw_orderbook,
        "minute_bars": minute_bars,
        "features": features,
        "labels_h15": labels_h15,
        "labels_h60": labels_h60,
        "predictions_h15": predictions_h15,
        "signals": signals,
        "label_distribution_h15": label_dist_h15,
        "feature_to_bar_symbol_minute_ratio": _round_ratio(
            int(features.get("symbol_minutes") or 0),
            int(minute_bars.get("symbol_minutes") or 0),
        ),
        "label_h15_to_feature_symbol_minute_ratio": _round_ratio(
            int(labels_h15.get("symbol_minutes") or 0),
            feature_symbol_minutes,
        ),
    }
    return row, {
        "minute_bars": minute_bar_symbols,
        "features": feature_symbols,
        "labels_h15": label_h15_symbols,
    }


def _latest_symbol_summary_from_maps(
    trade_date: str,
    *,
    actual_minutes_by_date: dict[str, dict[str, set[str]]],
    raw_market_symbols_by_date: dict[str, dict[str, int]],
    raw_orderbook_symbols_by_date: dict[str, dict[str, int]],
    derived_symbols: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    symbols = set(actual_minutes_by_date.get(trade_date, {}))
    rows = [
        {
            "symbol": symbol,
            "raw_market_symbol_minutes": int(raw_market_symbols_by_date.get(trade_date, {}).get(symbol, 0)),
            "raw_orderbook_symbol_minutes": int(raw_orderbook_symbols_by_date.get(trade_date, {}).get(symbol, 0)),
            "minute_bar_symbol_minutes": int(derived_symbols.get("minute_bars", {}).get(symbol, 0)),
            "feature_symbol_minutes": int(derived_symbols.get("features", {}).get(symbol, 0)),
            "label_h15_symbol_minutes": int(derived_symbols.get("labels_h15", {}).get(symbol, 0)),
        }
        for symbol in symbols
    ]
    rows.sort(key=lambda item: (int(item.get("feature_symbol_minutes") or 0), item["symbol"]))
    return rows


def _raw_symbol_minutes(connection: sqlite3.Connection, table_name: str, trade_date: str) -> dict[str, int]:
    if not _table_exists(connection, table_name):
        return {}
    query = f"""
        SELECT symbol, COUNT(DISTINCT substr(event_time, 1, 16)) AS symbol_minutes
        FROM {table_name}
        WHERE {_source_clause()} AND substr(event_time, 1, 10) = ?
        GROUP BY symbol
    """
    return {
        str(row["symbol"]): int(row["symbol_minutes"])
        for row in connection.execute(query, (*ACTUAL_RAW_SOURCES, trade_date))
    }


def _actual_symbol_minutes(
    connection: sqlite3.Connection,
    table_name: str,
    time_column: str,
    trade_date: str,
    *,
    horizon_min: int | None = None,
) -> dict[str, int]:
    if not _table_exists(connection, table_name):
        return {}
    extra_where = ""
    params: list[Any] = [trade_date]
    if horizon_min is not None:
        extra_where = " AND target.horizon_min = ?"
        params.append(horizon_min)
    query = f"""
        SELECT target.symbol, COUNT(DISTINCT substr(target.{time_column}, 1, 16)) AS symbol_minutes
        FROM {table_name} AS target
        JOIN temp_actual_minutes AS actual_minutes
          ON actual_minutes.symbol = target.symbol
         AND actual_minutes.minute_key = substr(target.{time_column}, 1, 16)
        WHERE actual_minutes.trade_date = ?
        {extra_where}
        GROUP BY target.symbol
    """
    return {
        str(row["symbol"]): int(row["symbol_minutes"])
        for row in connection.execute(query, tuple(params))
    }


def _latest_symbol_summary(connection: sqlite3.Connection, trade_date: str) -> list[dict[str, Any]]:
    symbols = {
        str(row["symbol"])
        for row in connection.execute(
            "SELECT DISTINCT symbol FROM temp_actual_minutes WHERE trade_date = ? ORDER BY symbol",
            (trade_date,),
        )
    }
    raw_market = _raw_symbol_minutes(connection, "raw_market_ticks", trade_date)
    raw_orderbook = _raw_symbol_minutes(connection, "raw_orderbook_ticks", trade_date)
    minute_bars = _actual_symbol_minutes(connection, "curated_minute_bars", "bar_time", trade_date)
    features = _actual_symbol_minutes(connection, "feature_model_inputs", "event_time", trade_date)
    labels_h15 = _actual_symbol_minutes(connection, "feature_labels", "event_time", trade_date, horizon_min=15)
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        rows.append(
            {
                "symbol": symbol,
                "raw_market_symbol_minutes": int(raw_market.get(symbol, 0)),
                "raw_orderbook_symbol_minutes": int(raw_orderbook.get(symbol, 0)),
                "minute_bar_symbol_minutes": int(minute_bars.get(symbol, 0)),
                "feature_symbol_minutes": int(features.get(symbol, 0)),
                "label_h15_symbol_minutes": int(labels_h15.get(symbol, 0)),
            }
        )
    rows.sort(key=lambda item: (int(item.get("feature_symbol_minutes") or 0), item["symbol"]))
    return rows


def _overall_assessment(recent_days: list[dict[str, Any]]) -> dict[str, Any]:
    if not recent_days:
        return {
            "status": "no_kis_live_data",
            "notes": ["No KIS live raw rows were found."],
        }
    latest = recent_days[-1]
    notes: list[str] = []
    if int(latest["raw_market"].get("symbol_minutes") or 0) == 0:
        notes.append("Latest date has no KIS market tick symbol-minutes.")
    if int(latest["raw_orderbook"].get("symbol_minutes") or 0) == 0:
        notes.append("Latest date has no KIS orderbook symbol-minutes.")
    feature_ratio = latest.get("feature_to_bar_symbol_minute_ratio")
    if feature_ratio is None or float(feature_ratio) < 0.95:
        notes.append("Latest date feature coverage is below 95% of actual minute bars.")
    label_ratio = latest.get("label_h15_to_feature_symbol_minute_ratio")
    if label_ratio is None or float(label_ratio) < 0.80:
        notes.append("Latest date h15 label coverage is still low; this is normal for fresh or partial sessions.")
    if not notes:
        status = "ok"
    elif any("no KIS" in note or "no KIS" in note for note in notes):
        status = "needs_attention"
    else:
        status = "watch"
    return {"status": status, "notes": notes}


def summarize(database_path: Path, *, recent_days: int = 10) -> dict[str, Any]:
    with _connect(database_path) as connection:
        raw_market_by_date, raw_market_symbol_minutes, raw_market_actual_minutes = _raw_minute_index(
            connection, "raw_market_ticks"
        )
        raw_orderbook_by_date, raw_orderbook_symbol_minutes, raw_orderbook_actual_minutes = _raw_minute_index(
            connection, "raw_orderbook_ticks"
        )
        actual_minutes_by_date = _merge_actual_minutes(raw_market_actual_minutes, raw_orderbook_actual_minutes)
        trade_dates = sorted(set(raw_market_by_date) | set(raw_orderbook_by_date))
        selected_dates = trade_dates[-recent_days:] if recent_days > 0 else trade_dates
        day_rows: list[dict[str, Any]] = []
        derived_symbols_by_date: dict[str, dict[str, dict[str, int]]] = {}
        for trade_date in selected_dates:
            day_row, derived_symbols = _day_summary_from_indexes(
                connection,
                trade_date,
                raw_market_by_date=raw_market_by_date,
                raw_orderbook_by_date=raw_orderbook_by_date,
                actual_minutes_by_date=actual_minutes_by_date,
            )
            day_rows.append(day_row)
            derived_symbols_by_date[trade_date] = derived_symbols
        latest_trade_date = trade_dates[-1] if trade_dates else None
        latest_symbols = (
            _latest_symbol_summary_from_maps(
                latest_trade_date,
                actual_minutes_by_date=actual_minutes_by_date,
                raw_market_symbols_by_date=raw_market_symbol_minutes,
                raw_orderbook_symbols_by_date=raw_orderbook_symbol_minutes,
                derived_symbols=derived_symbols_by_date.get(latest_trade_date, {}),
            )
            if latest_trade_date in selected_dates
            else []
        )
        source_summary = {
            "raw_market_ticks": _source_summary(connection, "raw_market_ticks"),
            "raw_orderbook_ticks": _source_summary(connection, "raw_orderbook_ticks"),
        }
    label_counter: Counter[str] = Counter()
    for day in day_rows:
        label_counter.update({key: int(value) for key, value in day.get("label_distribution_h15", {}).items()})
    return {
        "review": "kis_live_data_quality",
        "completed_at": datetime.now().astimezone().isoformat(),
        "database_path": str(database_path),
        "actual_raw_sources": list(ACTUAL_RAW_SOURCES),
        "trade_dates_observed": len(trade_dates),
        "first_trade_date": trade_dates[0] if trade_dates else None,
        "latest_trade_date": latest_trade_date,
        "recent_days_requested": recent_days,
        "source_summary": source_summary,
        "recent_days": day_rows,
        "recent_h15_label_distribution": dict(sorted(label_counter.items())),
        "latest_symbol_summary": latest_symbols,
        "assessment": _overall_assessment(day_rows),
        "next_actions": [
            "On the next market day, compare the 09:30 actual symbol-minute counts against watchdog/live-runtime status.",
            "If feature coverage stays below 95% after the session, inspect minute bar and feature build timing.",
            "If orderbook symbol-minutes are sparse, prioritize KIS WebSocket orderbook stability before more model tuning.",
        ],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# KIS Live Data Quality",
        "",
        f"- completed_at: `{summary.get('completed_at')}`",
        f"- database_path: `{summary.get('database_path')}`",
        f"- observed_dates: `{summary.get('trade_dates_observed')}`",
        f"- date_range: `{summary.get('first_trade_date')}`..`{summary.get('latest_trade_date')}`",
        f"- assessment: `{(summary.get('assessment') or {}).get('status')}`",
        "",
        "## Source Summary",
        "",
        "| table | source | rows | symbols | trade_dates | first_event_time | last_event_time |",
        "| --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for table_name, source_rows in (summary.get("source_summary") or {}).items():
        for row in source_rows:
            lines.append(
                "| "
                f"{table_name} | "
                f"{row.get('source')} | "
                f"{int(row.get('rows') or 0)} | "
                f"{int(row.get('symbols') or 0)} | "
                f"{int(row.get('trade_dates') or 0)} | "
                f"{row.get('first_event_time')} | "
                f"{row.get('last_event_time')} |"
            )

    lines.extend(
        [
            "",
            "## Recent Days",
            "",
            "| date | market_symbol_minutes | orderbook_symbol_minutes | bars | features | h15_labels | h60_labels | feature/bar | h15_label/feature |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary.get("recent_days", []):
        lines.append(
            "| "
            f"{row.get('trade_date')} | "
            f"{int((row.get('raw_market') or {}).get('symbol_minutes') or 0)} | "
            f"{int((row.get('raw_orderbook') or {}).get('symbol_minutes') or 0)} | "
            f"{int((row.get('minute_bars') or {}).get('symbol_minutes') or 0)} | "
            f"{int((row.get('features') or {}).get('symbol_minutes') or 0)} | "
            f"{int((row.get('labels_h15') or {}).get('symbol_minutes') or 0)} | "
            f"{int((row.get('labels_h60') or {}).get('symbol_minutes') or 0)} | "
            f"{row.get('feature_to_bar_symbol_minute_ratio')} | "
            f"{row.get('label_h15_to_feature_symbol_minute_ratio')} |"
        )

    assessment = summary.get("assessment") or {}
    lines.extend(["", "## Assessment", ""])
    notes = assessment.get("notes") or []
    if notes:
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("- No immediate data-quality warning in the latest observed KIS live date.")

    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- {action}" for action in summary.get("next_actions", []))
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize KIS live data quality from the runtime SQLite DB.")
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--recent-days", type=int, default=10)
    args = parser.parse_args()

    root = _repo_root()
    database_path = args.db_path or _database_path_from_env(root / "runtime-data" / "dev.db")
    output_dir = args.output_dir or (root / "runtime-data" / "reports" / "data-quality")
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = summarize(database_path, recent_days=args.recent_days)
    json_path = output_dir / f"{DEFAULT_OUTPUT_NAME}.json"
    md_path = output_dir / f"{DEFAULT_OUTPUT_NAME}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "assessment": summary["assessment"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
