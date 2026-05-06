"""Collect Cybos Plus 15-minute historical bars into a Windows-local SQLite DB.

This script is intentionally Windows-only. Cybos Plus exposes a 32-bit COM API,
so run it from Windows PowerShell with the 32-bit Python interpreter. Merge the
local DB into the WSL2 runtime DB with scripts/merge_cybos_to_main.sh afterward.
"""

from __future__ import annotations

import argparse
import ctypes
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_DB_PATH = r"C:\Temp\cybos_collect.db"
DEFAULT_SOURCE = "cybos-historical"
KST = timezone(timedelta(hours=9))


@dataclass(slots=True)
class CybosBar:
    symbol: str
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    trade_count: int


@dataclass(slots=True)
class SymbolResult:
    symbol: str
    name: str
    bars_written: int = 0
    first_time: datetime | None = None
    last_time: datetime | None = None
    requests: int = 0
    skipped: bool = False
    error: str | None = None


class CybosRateLimiter:
    """Keep Cybos requests under the documented 15 requests/second limit."""

    def __init__(self, cybos: object, *, max_per_second: int = 15) -> None:
        self.cybos = cybos
        self.min_interval_seconds = 1.0 / max(max_per_second, 1)
        self.last_request_at = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)

        try:
            remain = int(self.cybos.GetLimitRemainCount(1))
            if remain <= 0:
                wait_ms = int(getattr(self.cybos, "LimitRequestRemainTime", 1000))
                time.sleep(max(wait_ms / 1000.0, self.min_interval_seconds))
        except Exception:
            # Some Cybos installs deny the remaining-count query; the fixed
            # interval above still enforces the conservative 15/sec ceiling.
            pass

        self.last_request_at = time.monotonic()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect KOSPI200 15-minute bars through Cybos Plus StockChart.",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Collection start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--end",
        default=date.today().isoformat(),
        help="Collection end date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        help="Optional symbol list, e.g. --symbols 005930 or --symbols 005930,000660.",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help="SQLite DB path. Defaults to C:\\Temp\\cybos_collect.db.",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help="raw_market_ticks source value.",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=365,
        help="Date span per StockChart request.",
    )
    parser.add_argument(
        "--kospi200-group-code",
        type=int,
        default=180,
        help="CpCodeMgr group code used to query KOSPI200 components.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fetch even when raw_market_ticks already covers the requested range.",
    )
    return parser.parse_args(argv)


def parse_date(value: str, *, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD: {value}") from exc


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if symbol.startswith("A"):
        symbol = symbol[1:]
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError(f"Invalid Korean stock symbol: {value}")
    return symbol


def parse_symbols(values: list[str] | None) -> list[str]:
    if not values:
        return []
    symbols: list[str] = []
    for raw_value in values:
        for item in raw_value.replace(",", " ").split():
            symbols.append(normalize_symbol(item))
    return list(dict.fromkeys(symbols))


def api_symbol(symbol: str) -> str:
    return symbol if symbol.startswith("A") else f"A{symbol}"


def yyyymmdd(value: date) -> int:
    return int(value.strftime("%Y%m%d"))


def iter_date_chunks(start_date: date, end_date: date, *, chunk_days: int) -> Iterable[tuple[date, date]]:
    current = start_date
    span_days = max(chunk_days, 1)
    while current <= end_date:
        chunk_end = min(end_date, current + timedelta(days=span_days - 1))
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def iso_dt(value: datetime) -> str:
    return value.isoformat()


def is_windows_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def import_cybos_client():
    if not sys.platform.startswith("win"):
        raise RuntimeError("Cybos Plus COM API is Windows-only. Run this from Windows PowerShell.")
    try:
        import win32com.client  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "win32com.client is not available. Install pywin32 into the 32-bit Python environment."
        ) from exc
    return win32com.client


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
    connection.commit()


def connect_database(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=60)
    connection.execute("PRAGMA busy_timeout = 60000")
    ensure_schema(connection)
    return connection


def windows_path_to_wsl_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/":
        drive = normalized[0].lower()
        return f"/mnt/{drive}/{normalized[3:]}"
    return normalized


def print_merge_hint(db_path: str) -> None:
    src_path = windows_path_to_wsl_path(db_path)
    print("")
    print("Next merge command from WSL2:")
    print(
        "bash scripts/merge_cybos_to_main.sh "
        f"--src {src_path} "
        "--dst ~/projects/Real-time-stock-price-prediction-program/runtime-data/dev.db"
    )


def existing_source_range(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    source: str,
) -> tuple[int, str | None, str | None]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS row_count,
               MIN(substr(event_time, 1, 10)) AS first_date,
               MAX(substr(event_time, 1, 10)) AS last_date
        FROM raw_market_ticks
        WHERE symbol = ?
          AND lower(source) = lower(?)
        """,
        (symbol, source),
    ).fetchone()
    if row is None:
        return 0, None, None
    return int(row[0] or 0), row[1], row[2]


def already_covers_requested_range(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    source: str,
    start_date: date,
    end_date: date,
) -> bool:
    row_count, first_date, last_date = existing_source_range(connection, symbol=symbol, source=source)
    if row_count <= 0 or first_date is None or last_date is None:
        return False
    return first_date <= start_date.isoformat() and last_date >= end_date.isoformat()


def load_kospi200_symbols(code_mgr: object, *, group_code: int) -> list[str]:
    raw_codes = list(code_mgr.GetGroupCodeList(group_code))
    symbols = [normalize_symbol(str(code)) for code in raw_codes]
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        raise RuntimeError(
            f"CpCodeMgr.GetGroupCodeList({group_code}) returned no symbols. "
            "Check the Cybos KOSPI200 group code and login state."
        )
    return symbols


def code_name(code_mgr: object, symbol: str) -> str:
    for candidate in (api_symbol(symbol), symbol):
        try:
            name = str(code_mgr.CodeToName(candidate)).strip()
            if name:
                return name
        except Exception:
            continue
    return ""


def request_stockchart_bars(
    *,
    chart: object,
    limiter: CybosRateLimiter,
    symbol: str,
    start_date: date,
    end_date: date,
) -> tuple[list[CybosBar], int]:
    chart.SetInputValue(0, api_symbol(symbol))
    chart.SetInputValue(1, ord("1"))
    chart.SetInputValue(2, yyyymmdd(end_date))
    chart.SetInputValue(3, yyyymmdd(start_date))
    chart.SetInputValue(5, (0, 1, 2, 3, 4, 5, 8))
    chart.SetInputValue(6, ord("m"))
    chart.SetInputValue(7, 15)
    chart.SetInputValue(9, ord("1"))

    limiter.wait()
    chart.BlockRequest()

    status = int(chart.GetDibStatus())
    message = str(chart.GetDibMsg1())
    if status != 0:
        raise RuntimeError(f"StockChart request failed status={status} message={message}")

    row_count = int(chart.GetHeaderValue(3) or 0)
    bars: list[CybosBar] = []
    seen: set[datetime] = set()
    for index in range(row_count):
        try:
            trade_date = int(chart.GetDataValue(0, index))
            trade_time = int(chart.GetDataValue(1, index))
            open_price = float(chart.GetDataValue(2, index))
            high_price = float(chart.GetDataValue(3, index))
            low_price = float(chart.GetDataValue(4, index))
            close_price = float(chart.GetDataValue(5, index))
            volume = int(chart.GetDataValue(6, index) or 0)
        except (TypeError, ValueError):
            continue

        if trade_time <= 0 or min(open_price, high_price, low_price, close_price) <= 0:
            continue

        try:
            bar_time = datetime.strptime(f"{trade_date}{trade_time:04d}", "%Y%m%d%H%M").replace(tzinfo=KST)
        except ValueError:
            continue

        if bar_time.date() < start_date or bar_time.date() > end_date:
            continue
        if bar_time in seen:
            continue
        seen.add(bar_time)

        bars.append(
            CybosBar(
                symbol=symbol,
                bar_time=bar_time,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
                trade_count=max(1, volume // 1_000),
            )
        )

    bars.sort(key=lambda item: item.bar_time)
    return bars, row_count


def write_bars(
    connection: sqlite3.Connection,
    *,
    bars: list[CybosBar],
    source: str,
) -> int:
    if not bars:
        return 0

    symbol = bars[0].symbol
    first_time = iso_dt(min(bar.bar_time for bar in bars))
    last_time = iso_dt(max(bar.bar_time for bar in bars))
    minute_rows = [
        (
            bar.symbol,
            iso_dt(bar.bar_time),
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.trade_count,
        )
        for bar in bars
    ]
    tick_rows = [
        (
            bar.symbol,
            iso_dt(bar.bar_time),
            bar.close,
            bar.volume,
            source,
        )
        for bar in bars
    ]

    with connection:
        connection.execute(
            """
            DELETE FROM raw_market_ticks
            WHERE symbol = ?
              AND lower(source) = lower(?)
              AND event_time >= ?
              AND event_time <= ?
            """,
            (symbol, source, first_time, last_time),
        )
        connection.executemany(
            """
            INSERT INTO raw_market_ticks(symbol, event_time, price, volume, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            tick_rows,
        )
        connection.executemany(
            """
            INSERT OR REPLACE INTO curated_minute_bars(
                symbol, bar_time, open, high, low, close, volume, trade_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            minute_rows,
        )
    return len(bars)


def collect_symbol(
    *,
    connection: sqlite3.Connection,
    chart: object,
    limiter: CybosRateLimiter,
    symbol: str,
    name: str,
    start_date: date,
    end_date: date,
    chunk_days: int,
    source: str,
    force: bool,
) -> SymbolResult:
    result = SymbolResult(symbol=symbol, name=name)
    if not force and already_covers_requested_range(
        connection,
        symbol=symbol,
        source=source,
        start_date=start_date,
        end_date=end_date,
    ):
        result.skipped = True
        row_count, first_date, last_date = existing_source_range(connection, symbol=symbol, source=source)
        result.bars_written = 0
        print(f"  skip: already collected rows={row_count} range={first_date}..{last_date}")
        return result

    all_bars_by_key: dict[tuple[str, str], CybosBar] = {}
    for chunk_start, chunk_end in iter_date_chunks(start_date, end_date, chunk_days=chunk_days):
        print(f"  request {chunk_start.isoformat()}..{chunk_end.isoformat()}")
        bars, raw_count = request_stockchart_bars(
            chart=chart,
            limiter=limiter,
            symbol=symbol,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        result.requests += 1
        print(f"    received raw_rows={raw_count} valid_bars={len(bars)}")
        for bar in bars:
            all_bars_by_key[(bar.symbol, iso_dt(bar.bar_time))] = bar

    all_bars = sorted(all_bars_by_key.values(), key=lambda item: item.bar_time)
    result.bars_written = write_bars(connection, bars=all_bars, source=source)
    if all_bars:
        result.first_time = all_bars[0].bar_time
        result.last_time = all_bars[-1].bar_time
    return result


def print_summary(results: list[SymbolResult]) -> None:
    failures = [result for result in results if result.error]
    print("")
    print("===== Cybos historical collection summary =====")
    for result in results:
        range_text = "-"
        if result.first_time and result.last_time:
            range_text = f"{result.first_time.isoformat()}..{result.last_time.isoformat()}"
        state = "skipped" if result.skipped else "ok"
        if result.error:
            state = "failed"
        name_text = f" {result.name}" if result.name else ""
        print(
            f"{result.symbol}{name_text}: status={state} "
            f"bars_written={result.bars_written} requests={result.requests} range={range_text}"
        )
        if result.error:
            print(f"  error={result.error}")

    print(f"total_symbols={len(results)} failures={len(failures)}")
    if failures:
        print("failed_symbols=" + ", ".join(result.symbol for result in failures))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    start_date = parse_date(args.start, field_name="--start")
    end_date = parse_date(args.end, field_name="--end")
    if start_date > end_date:
        raise ValueError("--start must be earlier than or equal to --end")

    if not is_windows_admin():
        print("warning: Cybos Plus usually requires an elevated Windows session.", file=sys.stderr)

    win32com_client = import_cybos_client()
    cybos = win32com_client.Dispatch("CpUtil.CpCybos")
    if int(cybos.IsConnect) == 0:
        raise RuntimeError("Cybos Plus is not connected. Log in to Cybos Plus, then rerun this script.")

    code_mgr = win32com_client.Dispatch("CpUtil.CpCodeMgr")
    chart = win32com_client.Dispatch("CpSysDib.StockChart")
    limiter = CybosRateLimiter(cybos)

    requested_symbols = parse_symbols(args.symbols)
    symbols = requested_symbols or load_kospi200_symbols(code_mgr, group_code=args.kospi200_group_code)
    print(
        f"collecting symbols={len(symbols)} start={start_date.isoformat()} "
        f"end={end_date.isoformat()} source={args.source}"
    )
    print(f"db_path={args.db_path}")

    connection = connect_database(args.db_path)
    results: list[SymbolResult] = []
    try:
        for index, symbol in enumerate(symbols, start=1):
            name = code_name(code_mgr, symbol)
            display_name = f" {name}" if name else ""
            print("")
            print(f"[{index}/{len(symbols)}] {symbol}{display_name}")
            try:
                result = collect_symbol(
                    connection=connection,
                    chart=chart,
                    limiter=limiter,
                    symbol=symbol,
                    name=name,
                    start_date=start_date,
                    end_date=end_date,
                    chunk_days=args.chunk_days,
                    source=args.source,
                    force=bool(args.force),
                )
                range_text = "-"
                if result.first_time and result.last_time:
                    range_text = f"{result.first_time.isoformat()}..{result.last_time.isoformat()}"
                print(f"  done: bars_written={result.bars_written} range={range_text}")
            except Exception as exc:
                result = SymbolResult(symbol=symbol, name=name, error=str(exc))
                print(f"  failed: {exc}", file=sys.stderr)
            results.append(result)
    finally:
        connection.close()

    print_summary(results)
    print_merge_hint(args.db_path)
    return 1 if any(result.error for result in results) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise SystemExit(2)
