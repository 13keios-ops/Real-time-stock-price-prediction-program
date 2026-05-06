#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/merge_cybos_to_main.sh --src /mnt/c/Temp/cybos_collect.db --dst ~/projects/Real-time-stock-price-prediction-program/runtime-data/dev.db

Merges Cybos Plus historical collection rows into the main WSL2 runtime DB, then
deletes the source collection DB after a successful merge.
EOF
}

SRC=""
DST=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src)
      SRC="${2:-}"
      shift 2
      ;;
    --dst)
      DST="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$SRC" || -z "$DST" ]]; then
  usage >&2
  exit 2
fi

SRC="${SRC/#\~/$HOME}"
DST="${DST/#\~/$HOME}"

if [[ ! -f "$SRC" ]]; then
  echo "Source DB not found: $SRC" >&2
  exit 1
fi

mkdir -p "$(dirname "$DST")"

python - "$SRC" "$DST" <<'PY'
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


src = Path(sys.argv[1]).expanduser().resolve()
dst = Path(sys.argv[2]).expanduser().resolve()


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_market_ticks (
            symbol TEXT NOT NULL,
            event_time TEXT NOT NULL,
            price REAL NOT NULL,
            volume INTEGER NOT NULL,
            source TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_market_ticks_symbol_time
        ON raw_market_ticks(symbol, event_time)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS curated_minute_bars (
            symbol TEXT NOT NULL,
            bar_time TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER NOT NULL,
            trade_count INTEGER NOT NULL,
            PRIMARY KEY (symbol, bar_time)
        )
        """
    )


def table_exists(connection: sqlite3.Connection, schema_name: str, table_name: str) -> bool:
    row = connection.execute(
        f"SELECT 1 FROM {schema_name}.sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


connection = sqlite3.connect(str(dst), timeout=60)
attached = False
try:
    connection.execute("PRAGMA busy_timeout = 60000")
    connection.execute("PRAGMA journal_mode = WAL")
    ensure_schema(connection)
    connection.execute("ATTACH DATABASE ? AS cybos_src", (str(src),))
    attached = True

    if not table_exists(connection, "cybos_src", "raw_market_ticks"):
        raise RuntimeError(f"source DB has no raw_market_ticks table: {src}")
    if not table_exists(connection, "cybos_src", "curated_minute_bars"):
        raise RuntimeError(f"source DB has no curated_minute_bars table: {src}")

    raw_summary = connection.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(event_time), MAX(event_time)
        FROM cybos_src.raw_market_ticks
        """
    ).fetchone()
    bar_summary = connection.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(bar_time), MAX(bar_time)
        FROM cybos_src.curated_minute_bars
        """
    ).fetchone()

    with connection:
        connection.execute("DROP TABLE IF EXISTS temp.cybos_raw_keys")
        connection.execute(
            """
            CREATE TEMP TABLE cybos_raw_keys AS
            SELECT DISTINCT symbol, event_time, lower(source) AS source_key
            FROM cybos_src.raw_market_ticks
            """
        )
        connection.execute(
            """
            CREATE INDEX cybos_raw_keys_idx
            ON cybos_raw_keys(symbol, event_time, source_key)
            """
        )
        connection.execute(
            """
            DELETE FROM raw_market_ticks
            WHERE EXISTS (
                SELECT 1
                FROM temp.cybos_raw_keys AS keys
                WHERE keys.symbol = raw_market_ticks.symbol
                  AND keys.event_time = raw_market_ticks.event_time
                  AND keys.source_key = lower(raw_market_ticks.source)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO raw_market_ticks(symbol, event_time, price, volume, source)
            SELECT symbol, event_time, price, volume, source
            FROM cybos_src.raw_market_ticks
            """
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO curated_minute_bars(
                symbol, bar_time, open, high, low, close, volume, trade_count
            )
            SELECT symbol, bar_time, open, high, low, close, volume, trade_count
            FROM cybos_src.curated_minute_bars
            """
        )

    print("cybos_merge_status=ok")
    print(
        "raw_market_ticks_merged="
        f"{raw_summary[0]} symbols={raw_summary[1]} range={raw_summary[2]}..{raw_summary[3]}"
    )
    print(
        "curated_minute_bars_merged="
        f"{bar_summary[0]} symbols={bar_summary[1]} range={bar_summary[2]}..{bar_summary[3]}"
    )
    print(f"dst_db={dst}")
finally:
    if attached:
        connection.execute("DETACH DATABASE cybos_src")
    connection.close()
PY

rm -f -- "$SRC" "$SRC-wal" "$SRC-shm" "$SRC-journal"
echo "deleted_src=$SRC"
