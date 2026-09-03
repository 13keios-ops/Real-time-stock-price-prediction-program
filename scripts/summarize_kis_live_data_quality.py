#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import tomllib
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


def _read_watchlist(root: Path) -> list[str]:
    path = root / "config" / "watchlist.txt"
    if not path.exists():
        return []
    symbols: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        symbols.append(line)
    return symbols


def _read_market_clock(root: Path) -> tuple[str, str, str, str]:
    path = root / "config" / "market_calendar.toml"
    if not path.exists():
        return "Asia/Seoul", "09:00", "15:30", "15:20"
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    market = config.get("market") if isinstance(config, dict) else {}
    if not isinstance(market, dict):
        market = {}
    return (
        str(market.get("timezone") or "Asia/Seoul"),
        str(market.get("session_open") or "09:00"),
        str(market.get("session_close") or "15:30"),
        str(market.get("forced_flat_time") or "15:20"),
    )


def _floor_minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def _latest_intraday_coverage(
    *,
    root: Path,
    latest_day: dict[str, Any] | None,
    latest_symbol_summary: list[dict[str, Any]],
) -> dict[str, Any]:
    if not latest_day:
        return {"status": "no_latest_day"}
    trade_date_text = str(latest_day.get("trade_date") or "")
    if not trade_date_text:
        return {"status": "no_latest_day"}

    watchlist_symbols = _read_watchlist(root)
    symbols = watchlist_symbols or [str(row.get("symbol")) for row in latest_symbol_summary if row.get("symbol")]
    symbol_count = len(symbols)
    if symbol_count <= 0:
        return {"status": "no_symbols", "trade_date": trade_date_text}

    timezone_name, session_open_text, session_close_text, _ = _read_market_clock(root)
    tz_suffix = "+09:00" if timezone_name in {"Asia/Seoul", "KST"} else ""
    session_start = datetime.fromisoformat(f"{trade_date_text}T{session_open_text}:00{tz_suffix}")
    session_end = datetime.fromisoformat(f"{trade_date_text}T{session_close_text}:00{tz_suffix}")

    raw_market = latest_day.get("raw_market") or {}
    raw_orderbook = latest_day.get("raw_orderbook") or {}
    last_times = [
        str(value)
        for value in (raw_market.get("last_time"), raw_orderbook.get("last_time"))
        if value
    ]
    if not last_times:
        return {
            "status": "no_raw_last_time",
            "trade_date": trade_date_text,
            "watchlist_symbols": symbol_count,
        }
    latest_raw_time = min(_floor_minute(datetime.fromisoformat(max(last_times))), session_end)
    now = datetime.now(latest_raw_time.tzinfo) if latest_raw_time.tzinfo else datetime.now()
    latest_raw_minute_lag_seconds = max(int((now - latest_raw_time).total_seconds()), 0)
    if latest_raw_time < session_start:
        minute_slots = 0
    else:
        minute_slots = int((latest_raw_time - session_start).total_seconds() // 60) + 1
    expected_symbol_minutes = minute_slots * symbol_count
    closed_minute_slots = max(minute_slots - 1, 0)
    closed_expected_symbol_minutes = closed_minute_slots * symbol_count

    def coverage(value: int, denominator: int = expected_symbol_minutes) -> float | None:
        return _round_ratio(value, denominator)

    return {
        "status": "ok" if expected_symbol_minutes > 0 else "no_expected_minutes",
        "trade_date": trade_date_text,
        "session_open": session_open_text,
        "session_close": session_close_text,
        "latest_raw_minute": latest_raw_time.isoformat(),
        "latest_raw_minute_lag_seconds": latest_raw_minute_lag_seconds,
        "watchlist_symbols": symbol_count,
        "expected_minute_slots_per_symbol": minute_slots,
        "expected_symbol_minutes": expected_symbol_minutes,
        "closed_expected_minute_slots_per_symbol": closed_minute_slots,
        "closed_expected_symbol_minutes": closed_expected_symbol_minutes,
        "raw_market_symbol_minutes": int(raw_market.get("symbol_minutes") or 0),
        "raw_orderbook_symbol_minutes": int(raw_orderbook.get("symbol_minutes") or 0),
        "minute_bar_symbol_minutes": int((latest_day.get("minute_bars") or {}).get("symbol_minutes") or 0),
        "feature_symbol_minutes": int((latest_day.get("features") or {}).get("symbol_minutes") or 0),
        "raw_market_coverage_ratio": coverage(int(raw_market.get("symbol_minutes") or 0)),
        "raw_orderbook_coverage_ratio": coverage(int(raw_orderbook.get("symbol_minutes") or 0)),
        "minute_bar_coverage_ratio": coverage(int((latest_day.get("minute_bars") or {}).get("symbol_minutes") or 0)),
        "feature_coverage_ratio": coverage(int((latest_day.get("features") or {}).get("symbol_minutes") or 0)),
        "minute_bar_closed_coverage_ratio": coverage(
            int((latest_day.get("minute_bars") or {}).get("symbol_minutes") or 0),
            closed_expected_symbol_minutes,
        ),
        "feature_closed_coverage_ratio": coverage(
            int((latest_day.get("features") or {}).get("symbol_minutes") or 0),
            closed_expected_symbol_minutes,
        ),
    }


def _compact_minute_ranges(minute_keys: set[str]) -> list[str]:
    if not minute_keys:
        return []
    values = [datetime.fromisoformat(value) for value in sorted(minute_keys)]
    groups: list[list[datetime]] = [[values[0]]]
    for value in values[1:]:
        if value - groups[-1][-1] == timedelta(minutes=1):
            groups[-1].append(value)
        else:
            groups.append([value])
    return [
        group[0].strftime("%H:%M")
        if len(group) == 1
        else f"{group[0].strftime('%H:%M')}-{group[-1].strftime('%H:%M')}"
        for group in groups
    ]


def _latest_raw_gap_summary(
    *,
    root: Path,
    trade_date: str | None,
    raw_market_actual_minutes: dict[str, dict[str, set[str]]],
    raw_orderbook_actual_minutes: dict[str, dict[str, set[str]]],
) -> dict[str, Any]:
    if not trade_date:
        return {"status": "no_latest_day"}
    watchlist_symbols = _read_watchlist(root)
    observed_symbols = sorted(
        set(raw_market_actual_minutes.get(trade_date, {}))
        | set(raw_orderbook_actual_minutes.get(trade_date, {}))
    )
    symbols = watchlist_symbols or observed_symbols
    if not symbols:
        return {"status": "no_symbols", "trade_date": trade_date}

    _, session_open_text, session_close_text, forced_flat_time_text = _read_market_clock(root)
    current = datetime.fromisoformat(f"{trade_date}T{session_open_text}:00")
    session_end = datetime.fromisoformat(f"{trade_date}T{session_close_text}:00")
    forced_flat_start = datetime.fromisoformat(f"{trade_date}T{forced_flat_time_text}:00")
    expected_minutes: set[str] = set()
    while current <= session_end:
        expected_minutes.add(current.strftime("%Y-%m-%dT%H:%M"))
        current += timedelta(minutes=1)
    expected_closing_auction_minutes: set[str] = set()
    while forced_flat_start < session_end:
        expected_closing_auction_minutes.add(forced_flat_start.strftime("%Y-%m-%dT%H:%M"))
        forced_flat_start += timedelta(minutes=1)

    streams: dict[str, Any] = {}
    has_gaps = False
    has_unexpected_common_gaps = False
    for stream_name, actual_by_date in (
        ("raw_market", raw_market_actual_minutes),
        ("raw_orderbook", raw_orderbook_actual_minutes),
    ):
        actual_by_symbol = actual_by_date.get(trade_date, {})
        common_missing = set(expected_minutes)
        missing_by_symbol: dict[str, Any] = {}
        total_missing = 0
        for symbol in symbols:
            observed = {
                minute_key
                for minute_key in actual_by_symbol.get(symbol, set())
                if minute_key in expected_minutes
            }
            missing = expected_minutes - observed
            common_missing &= missing
            total_missing += len(missing)
            missing_by_symbol[symbol] = {
                "missing_minutes": len(missing),
                "missing_ranges": _compact_minute_ranges(missing),
            }
        has_gaps = has_gaps or total_missing > 0
        expected_closing_auction_common_missing = (
            common_missing & expected_closing_auction_minutes
            if stream_name == "raw_market"
            else set()
        )
        unexpected_common_missing = common_missing - expected_closing_auction_common_missing
        has_unexpected_common_gaps = has_unexpected_common_gaps or bool(unexpected_common_missing)
        streams[stream_name] = {
            "expected_minutes_per_symbol": len(expected_minutes),
            "symbols": len(symbols),
            "total_missing_symbol_minutes": total_missing,
            "common_missing_minutes": len(common_missing),
            "common_missing_ranges": _compact_minute_ranges(common_missing),
            "expected_closing_auction_common_missing_ranges": _compact_minute_ranges(
                expected_closing_auction_common_missing
            ),
            "unexpected_common_missing_ranges": _compact_minute_ranges(unexpected_common_missing),
            "missing_by_symbol": missing_by_symbol,
        }

    return {
        "status": "gaps_detected" if has_gaps else "complete",
        "trade_date": trade_date,
        "session_open": session_open_text,
        "session_close": session_close_text,
        "expected_closing_auction_window": {
            "start": forced_flat_time_text,
            "end_exclusive": session_close_text,
        },
        "unexpected_common_gaps_detected": has_unexpected_common_gaps,
        "streams": streams,
    }


def _raw_minute_index(
    connection: sqlite3.Connection,
    table_name: str,
    trade_dates: list[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, int]], dict[str, dict[str, set[str]]]]:
    day_stats: dict[str, dict[str, Any]] = {}
    symbol_minutes: dict[str, dict[str, int]] = {}
    actual_minutes: dict[str, dict[str, set[str]]] = {}
    if not _table_exists(connection, table_name):
        return day_stats, symbol_minutes, actual_minutes
    date_where = ""
    params: tuple[Any, ...] = ACTUAL_RAW_SOURCES
    if trade_dates is not None:
        date_clause, date_params = _date_filter("event_time", trade_dates)
        date_where = f" AND {date_clause}"
        params = (*params, *date_params)
    query = f"""
        SELECT
            symbol,
            substr(event_time, 1, 16) AS minute_key,
            source,
            MIN(event_time) AS sample_time,
            COUNT(*) AS row_count
        FROM {table_name}
        WHERE {_source_clause()}
          {date_where}
        GROUP BY symbol, minute_key, source
        ORDER BY minute_key, symbol
    """
    for row in connection.execute(query, params):
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


def _has_lineage_value(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _decision_lineage_summary(connection: sqlite3.Connection, trade_date: str) -> dict[str, Any]:
    table_name = "serving_decision_ledger"
    if not _table_exists(connection, table_name):
        return {"status": "table_missing", "trade_date": trade_date, "rows": 0}
    rows = connection.execute(
        """
        SELECT
            symbol,
            event_time,
            decision_stage,
            active_prediction_id,
            active_model_version,
            active_training_run_id,
            active_artifact_id,
            active_artifact_sha256,
            shadow_predictions_json
        FROM serving_decision_ledger
        WHERE substr(event_time, 1, 10) = ?
        ORDER BY event_time, symbol
        """,
        (trade_date,),
    ).fetchall()
    if not rows:
        return {"status": "no_rows", "trade_date": trade_date, "rows": 0}

    active_fields = (
        "active_prediction_id",
        "active_model_version",
        "active_training_run_id",
        "active_artifact_id",
        "active_artifact_sha256",
    )
    shadow_fields = (
        "prediction_id",
        "model_version",
        "training_run_id",
        "artifact_id",
        "artifact_sha256",
    )
    stages: Counter[str] = Counter()
    symbols: set[str] = set()
    minutes: set[str] = set()
    active_complete_rows = 0
    complete_lineage_rows = 0
    malformed_shadow_rows = 0
    shadow_entries = 0
    complete_shadow_entries = 0
    for row in rows:
        stages[str(row["decision_stage"] or "unknown")] += 1
        symbols.add(str(row["symbol"]))
        minutes.add(str(row["event_time"])[:16])
        active_complete = all(_has_lineage_value(row[field]) for field in active_fields)
        active_complete_rows += int(active_complete)
        try:
            shadows = json.loads(str(row["shadow_predictions_json"] or "[]"))
        except (TypeError, ValueError):
            shadows = None
        if not isinstance(shadows, list):
            malformed_shadow_rows += 1
            shadow_complete = False
        else:
            shadow_complete = True
            for shadow in shadows:
                shadow_entries += 1
                entry_complete = isinstance(shadow, dict) and all(
                    _has_lineage_value(shadow.get(field)) for field in shadow_fields
                )
                complete_shadow_entries += int(entry_complete)
                shadow_complete = shadow_complete and entry_complete
        complete_lineage_rows += int(active_complete and shadow_complete)

    total_rows = len(rows)
    completion_ratio = _round_ratio(complete_lineage_rows, total_rows)
    status = "ok" if complete_lineage_rows == total_rows else "lineage_incomplete"
    return {
        "status": status,
        "trade_date": trade_date,
        "rows": total_rows,
        "symbols": len(symbols),
        "symbol_minutes": len({(str(row["symbol"]), str(row["event_time"])[:16]) for row in rows}),
        "minutes": len(minutes),
        "active_lineage_complete_rows": active_complete_rows,
        "complete_lineage_rows": complete_lineage_rows,
        "lineage_completion_ratio": completion_ratio,
        "malformed_shadow_rows": malformed_shadow_rows,
        "shadow_entries": shadow_entries,
        "complete_shadow_entries": complete_shadow_entries,
        "decision_stages": dict(sorted(stages.items())),
        "first_event_time": str(rows[0]["event_time"]),
        "last_event_time": str(rows[-1]["event_time"]),
    }


def _websocket_reconnect_summary(log_path: Path, trade_date: str) -> dict[str, Any]:
    if not log_path.exists():
        return {"status": "log_missing", "trade_date": trade_date, "count": 0, "log_path": str(log_path)}
    marker = "KIS WebSocket disconnected; reconnecting"
    events: list[str] = []
    reasons: Counter[str] = Counter()
    attempts: list[int] = []
    storm_count = 0
    connected_events: list[str] = []
    subscription_restore_events: list[str] = []
    first_frame_after_restore_events: list[str] = []
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith(trade_date):
                continue
            stripped = line.rstrip()
            if "Connected to KIS WebSocket" in stripped:
                connected_events.append(stripped)
            if "KIS WebSocket subscriptions restored" in stripped:
                subscription_restore_events.append(stripped)
            if "KIS WebSocket first frame received after subscription restore" in stripped:
                first_frame_after_restore_events.append(stripped)
            if marker not in stripped:
                continue
            events.append(stripped)
            attempt_match = re.search(r"attempt (\d+)/", stripped)
            if attempt_match:
                attempts.append(int(attempt_match.group(1)))
            if "storm=True" in stripped:
                storm_count += 1
            reason = stripped.split("): ", 1)[1] if "): " in stripped else "unknown"
            reasons[reason] += 1
    return {
        "status": "storm_detected" if storm_count else ("observed_no_storm" if events else "no_events"),
        "trade_date": trade_date,
        "count": len(events),
        "storm_count": storm_count,
        "max_attempt": max(attempts) if attempts else 0,
        "first_event_at": events[0][:23] if events else None,
        "last_event_at": events[-1][:23] if events else None,
        "connected_count": len(connected_events),
        "last_connected_at": connected_events[-1][:23] if connected_events else None,
        "subscription_restore_count": len(subscription_restore_events),
        "last_subscription_restore_at": (
            subscription_restore_events[-1][:23] if subscription_restore_events else None
        ),
        "first_frame_after_restore_count": len(first_frame_after_restore_events),
        "last_first_frame_after_restore_at": (
            first_frame_after_restore_events[-1][:23] if first_frame_after_restore_events else None
        ),
        "reasons": dict(sorted(reasons.items())),
        "log_path": str(log_path),
    }

def _coverage_assessment_notes(coverage: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not coverage or coverage.get("status") != "ok":
        return "ok", []
    expected_symbol_minutes = int(coverage.get("expected_symbol_minutes") or 0)
    if expected_symbol_minutes <= 0:
        return "ok", []

    notes: list[str] = []
    severity = "ok"
    for key, label in (
        ("raw_market_coverage_ratio", "market tick"),
        ("raw_orderbook_coverage_ratio", "orderbook"),
        ("minute_bar_closed_coverage_ratio", "minute bar closed-minute"),
        ("feature_closed_coverage_ratio", "feature closed-minute"),
    ):
        ratio = coverage.get(key)
        if ratio is None:
            continue
        ratio_value = float(ratio)
        if ratio_value < 0.80:
            notes.append(f"Latest date {label} coverage is below 80% of expected symbol-minutes.")
            severity = "needs_attention"
        elif ratio_value < 0.95 and severity != "needs_attention":
            notes.append(f"Latest date {label} coverage is below 95% of expected symbol-minutes.")
            severity = "watch"
    return severity, notes


def _overall_assessment(
    recent_days: list[dict[str, Any]],
    *,
    latest_intraday_coverage: dict[str, Any] | None = None,
    latest_decision_lineage: dict[str, Any] | None = None,
    latest_websocket_reconnects: dict[str, Any] | None = None,
    latest_raw_gap_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not recent_days:
        return {
            "status": "no_kis_live_data",
            "severity": "CRITICAL",
            "korean_prefix": "\uc2e4\ud328",
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
    coverage_severity, coverage_notes = _coverage_assessment_notes(latest_intraday_coverage)
    notes.extend(coverage_notes)
    observability_severity = "ok"
    critical_observability = False
    lineage_status = str((latest_decision_lineage or {}).get("status") or "not_checked")
    if lineage_status in {"table_missing", "no_rows", "lineage_incomplete"}:
        notes.append(f"Latest date serving decision ledger status is {lineage_status}.")
        observability_severity = "needs_attention"
    reconnect_status = str((latest_websocket_reconnects or {}).get("status") or "not_checked")
    reconnect_count = int((latest_websocket_reconnects or {}).get("count") or 0)
    reconnect_storm_count = int((latest_websocket_reconnects or {}).get("storm_count") or 0)
    if reconnect_status == "log_missing":
        notes.append("Latest date KIS WebSocket reconnect log is missing.")
        observability_severity = "needs_attention"
    elif reconnect_status == "storm_detected" or reconnect_storm_count > 0:
        notes.append("Latest date KIS WebSocket reconnect storm was detected.")
        observability_severity = "needs_attention"
        critical_observability = True
    elif reconnect_count > 0:
        notes.append(
            f"Latest date had {reconnect_count} KIS WebSocket reconnect event(s) without a recorded storm; "
            "interpret this together with raw and derived coverage."
        )
        observability_severity = "watch"
    raw_gap_summary = latest_raw_gap_summary or {}
    if raw_gap_summary.get("status") == "gaps_detected":
        streams = raw_gap_summary.get("streams") or {}
        market_stream = streams.get("raw_market") or {}
        orderbook_stream = streams.get("raw_orderbook") or {}
        market_ranges = market_stream.get("unexpected_common_missing_ranges")
        if market_ranges is None:
            market_ranges = market_stream.get("common_missing_ranges") or []
        orderbook_ranges = orderbook_stream.get("unexpected_common_missing_ranges")
        if orderbook_ranges is None:
            orderbook_ranges = orderbook_stream.get("common_missing_ranges") or []
        if market_ranges or orderbook_ranges:
            notes.append(
                "Latest date has common raw-data gap ranges across the watchlist: "
                f"market={market_ranges}, orderbook={orderbook_ranges}."
            )
            observability_severity = "needs_attention"
            critical_observability = True
    if critical_observability:
        status = "critical"
    elif coverage_severity == "needs_attention" or observability_severity == "needs_attention":
        status = "needs_attention"
    elif not notes:
        status = "ok"
    else:
        status = "watch"
    if status == "critical":
        severity = "CRITICAL"
        korean_prefix = "\uc2e4\ud328"
    elif status in {"watch", "needs_attention"}:
        severity = "ATTENTION"
        korean_prefix = "\uc8fc\uc758"
    else:
        severity = "NORMAL"
        korean_prefix = "\uc815\uc0c1"
    return {"status": status, "severity": severity, "korean_prefix": korean_prefix, "notes": notes}


def summarize(
    database_path: Path,
    *,
    recent_days: int = 10,
    live_runtime_log_path: Path | None = None,
) -> dict[str, Any]:
    with _connect(database_path) as connection:
        trade_dates = _trade_dates(connection)
        selected_dates = trade_dates[-recent_days:] if recent_days > 0 else trade_dates
        raw_market_by_date, raw_market_symbol_minutes, raw_market_actual_minutes = _raw_minute_index(
            connection, "raw_market_ticks", selected_dates
        )
        raw_orderbook_by_date, raw_orderbook_symbol_minutes, raw_orderbook_actual_minutes = _raw_minute_index(
            connection, "raw_orderbook_ticks", selected_dates
        )
        actual_minutes_by_date = _merge_actual_minutes(raw_market_actual_minutes, raw_orderbook_actual_minutes)
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
            day_row["serving_decision_ledger"] = _decision_lineage_summary(connection, trade_date)
            reconnect_log_path = live_runtime_log_path or (
                _repo_root() / "runtime-data" / "logs" / "app" / "live-runtime.stderr.log"
            )
            day_row["websocket_reconnects"] = _websocket_reconnect_summary(reconnect_log_path, trade_date)
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
        latest_raw_gap_summary = _latest_raw_gap_summary(
            root=_repo_root(),
            trade_date=latest_trade_date,
            raw_market_actual_minutes=raw_market_actual_minutes,
            raw_orderbook_actual_minutes=raw_orderbook_actual_minutes,
        )
        source_summary = {
            "raw_market_ticks": _source_summary(connection, "raw_market_ticks"),
            "raw_orderbook_ticks": _source_summary(connection, "raw_orderbook_ticks"),
        }
    label_counter: Counter[str] = Counter()
    for day in day_rows:
        label_counter.update({key: int(value) for key, value in day.get("label_distribution_h15", {}).items()})
    latest_intraday_coverage = _latest_intraday_coverage(
        root=_repo_root(),
        latest_day=day_rows[-1] if day_rows else None,
        latest_symbol_summary=latest_symbols,
    )
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
        "latest_intraday_coverage": latest_intraday_coverage,
        "latest_session_observability": {
            "serving_decision_ledger": (day_rows[-1].get("serving_decision_ledger") if day_rows else {}),
            "websocket_reconnects": (day_rows[-1].get("websocket_reconnects") if day_rows else {}),
            "raw_minute_gaps": latest_raw_gap_summary,
        },
        "assessment": _overall_assessment(
            day_rows,
            latest_intraday_coverage=latest_intraday_coverage,
            latest_decision_lineage=(day_rows[-1].get("serving_decision_ledger") if day_rows else None),
            latest_websocket_reconnects=(day_rows[-1].get("websocket_reconnects") if day_rows else None),
            latest_raw_gap_summary=latest_raw_gap_summary,
        ),
        "next_actions": [
            "On the next market day, compare actual symbol-minutes, decision-ledger lineage, and reconnect evidence against watchdog/live-runtime status.",
            "Minute bar and feature intraday coverage are assessed against closed minutes to avoid 09:30 false alarms.",
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
        f"- severity: `{(summary.get('assessment') or {}).get('severity')}`",
        f"- korean_prefix: `{(summary.get('assessment') or {}).get('korean_prefix')}`",
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

    observability = summary.get("latest_session_observability") or {}
    decision = observability.get("serving_decision_ledger") or {}
    reconnects = observability.get("websocket_reconnects") or {}
    lines.extend(
        [
            "",
            "## Latest Session Observability",
            "",
            f"- trade_date: `{decision.get('trade_date') or reconnects.get('trade_date')}`",
            f"- decision_ledger_status: `{decision.get('status')}`",
            f"- decision_rows: `{decision.get('rows')}`",
            f"- complete_lineage_rows: `{decision.get('complete_lineage_rows')}`",
            f"- lineage_completion_ratio: `{decision.get('lineage_completion_ratio')}`",
            f"- decision_stages: `{decision.get('decision_stages')}`",
            f"- websocket_reconnect_status: `{reconnects.get('status')}`",
            f"- websocket_reconnect_count: `{reconnects.get('count')}`",
            f"- websocket_reconnect_storm_count: `{reconnects.get('storm_count')}`",
            f"- websocket_reconnect_reasons: `{reconnects.get('reasons')}`",
            f"- websocket_connected_count: `{reconnects.get('connected_count')}`",
            f"- websocket_last_connected_at: `{reconnects.get('last_connected_at')}`",
            f"- websocket_subscription_restore_count: `{reconnects.get('subscription_restore_count')}`",
            f"- websocket_last_subscription_restore_at: `{reconnects.get('last_subscription_restore_at')}`",
            f"- websocket_first_frame_after_restore_count: `{reconnects.get('first_frame_after_restore_count')}`",
            f"- websocket_last_first_frame_after_restore_at: `{reconnects.get('last_first_frame_after_restore_at')}`",
        ]
    )
    raw_gaps = observability.get("raw_minute_gaps") or {}
    gap_streams = raw_gaps.get("streams") or {}
    market_gaps = gap_streams.get("raw_market") or {}
    orderbook_gaps = gap_streams.get("raw_orderbook") or {}
    lines.extend(
        [
            f"- raw_minute_gap_status: `{raw_gaps.get('status')}`",
            f"- expected_closing_auction_window: `{raw_gaps.get('expected_closing_auction_window')}`",
            f"- raw_market_common_missing_ranges: `{market_gaps.get('common_missing_ranges')}`",
            f"- raw_market_expected_closing_auction_ranges: `{market_gaps.get('expected_closing_auction_common_missing_ranges')}`",
            f"- raw_market_unexpected_common_missing_ranges: `{market_gaps.get('unexpected_common_missing_ranges')}`",
            f"- raw_orderbook_common_missing_ranges: `{orderbook_gaps.get('common_missing_ranges')}`",
            f"- raw_orderbook_unexpected_common_missing_ranges: `{orderbook_gaps.get('unexpected_common_missing_ranges')}`",
            f"- raw_market_missing_symbol_minutes: `{market_gaps.get('total_missing_symbol_minutes')}`",
            f"- raw_orderbook_missing_symbol_minutes: `{orderbook_gaps.get('total_missing_symbol_minutes')}`",
            f"- raw_market_missing_by_symbol: `{market_gaps.get('missing_by_symbol')}`",
            f"- raw_orderbook_missing_by_symbol: `{orderbook_gaps.get('missing_by_symbol')}`",
        ]
    )

    coverage = summary.get("latest_intraday_coverage") or {}
    lines.extend(
        [
            "",
            "## Latest Intraday Coverage",
            "",
            f"- status: `{coverage.get('status')}`",
            f"- trade_date: `{coverage.get('trade_date')}`",
            f"- latest_raw_minute: `{coverage.get('latest_raw_minute')}`",
            f"- latest_raw_minute_lag_seconds: `{coverage.get('latest_raw_minute_lag_seconds')}`",
            f"- watchlist_symbols: `{coverage.get('watchlist_symbols')}`",
            f"- expected_symbol_minutes: `{coverage.get('expected_symbol_minutes')}`",
            f"- closed_expected_symbol_minutes: `{coverage.get('closed_expected_symbol_minutes')}`",
            f"- market_coverage: `{coverage.get('raw_market_coverage_ratio')}`",
            f"- orderbook_coverage: `{coverage.get('raw_orderbook_coverage_ratio')}`",
            f"- minute_bar_coverage: `{coverage.get('minute_bar_coverage_ratio')}`",
            f"- feature_coverage: `{coverage.get('feature_coverage_ratio')}`",
            f"- minute_bar_closed_coverage: `{coverage.get('minute_bar_closed_coverage_ratio')}`",
            f"- feature_closed_coverage: `{coverage.get('feature_closed_coverage_ratio')}`",
            "- note: `Raw market/orderbook coverage may exceed 100% when pre-open orderbook rows or REST snapshots are present. Minute bar and feature assessment uses closed-minute coverage.`",
        ]
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
    parser.add_argument("--live-runtime-log-path", type=Path, default=None)
    args = parser.parse_args()

    root = _repo_root()
    database_path = args.db_path or _database_path_from_env(root / "runtime-data" / "dev.db")
    output_dir = args.output_dir or (root / "runtime-data" / "reports" / "data-quality")
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = summarize(
        database_path,
        recent_days=args.recent_days,
        live_runtime_log_path=args.live_runtime_log_path,
    )
    json_path = output_dir / f"{DEFAULT_OUTPUT_NAME}.json"
    md_path = output_dir / f"{DEFAULT_OUTPUT_NAME}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "assessment": summary["assessment"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
