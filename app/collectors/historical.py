"""Historical data collection helpers for WSL research backfills."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
from typing import Any

from app.config.settings import load_settings
from app.observability.logging import configure_logging
from app.services.research import build_feature_dataset_from_sqlite
from app.storage.contracts import MinuteBar, OrderbookSnapshot
from app.storage.runtime_writer import get_sqlite_store
from app.universe.watchlist import load_watchlist
from app.utils.time import get_timezone, now_local


PYKRX_DAILY_PROXY_SOURCE = "pykrx-daily-proxy"
DEFAULT_START_DATE = date(2021, 1, 1)
DEFAULT_BARS_PER_DAY = 26


@dataclass(slots=True)
class HistoricalSymbolSummary:
    symbol: str
    daily_rows: int
    bars_written: int
    first_date: str | None
    last_date: str | None
    missing_or_partial_dates: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "daily_rows": self.daily_rows,
            "bars_written": self.bars_written,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "missing_or_partial_dates": self.missing_or_partial_dates,
        }


@dataclass(slots=True)
class HistoricalCollectionResult:
    source_plan: str
    source: str
    start_date: str
    end_date: str
    bars_per_day: int
    symbols: list[str]
    bars_written: int
    orderbooks_written: int
    feature_rows_written: int
    label_rows_written: int
    learning_rows_h15: int
    earliest_bar_date: str | None
    latest_bar_date: str | None
    quality: dict[str, object]
    symbol_summaries: list[HistoricalSymbolSummary]
    report_json_path: Path
    report_markdown_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "source_plan": self.source_plan,
            "source": self.source,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "bars_per_day": self.bars_per_day,
            "symbols": self.symbols,
            "bars_written": self.bars_written,
            "orderbooks_written": self.orderbooks_written,
            "feature_rows_written": self.feature_rows_written,
            "label_rows_written": self.label_rows_written,
            "learning_rows_h15": self.learning_rows_h15,
            "earliest_bar_date": self.earliest_bar_date,
            "latest_bar_date": self.latest_bar_date,
            "quality": self.quality,
            "symbol_summaries": [summary.to_dict() for summary in self.symbol_summaries],
            "report_json_path": str(self.report_json_path),
            "report_markdown_path": str(self.report_markdown_path),
        }


def parse_date_text(value: str | None, *, default: date) -> date:
    if not value:
        return default
    return date.fromisoformat(value)


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, float) and value != value:
        return 0
    return int(float(str(value).replace(",", "")))


def _market_times(bars_per_day: int) -> list[time]:
    if bars_per_day < 2:
        raise ValueError("bars_per_day must be at least 2.")
    start = datetime.combine(date(2000, 1, 1), time(9, 0))
    return [(start + timedelta(minutes=15 * index)).time() for index in range(bars_per_day)]


def _interpolate_price(index: int, anchors: list[tuple[int, float]]) -> float:
    for anchor_index, anchor_price in anchors:
        if index == anchor_index:
            return anchor_price
    for left, right in zip(anchors, anchors[1:]):
        left_index, left_price = left
        right_index, right_price = right
        if left_index <= index <= right_index:
            width = max(right_index - left_index, 1)
            ratio = (index - left_index) / width
            return left_price + ((right_price - left_price) * ratio)
    return anchors[-1][1]


def _volume_slices(total_volume: int, bars_per_day: int) -> list[int]:
    if total_volume <= 0:
        return [0 for _ in range(bars_per_day)]
    midpoint = (bars_per_day - 1) / 2
    weights = [1.0 + (abs(index - midpoint) / max(midpoint, 1.0)) for index in range(bars_per_day)]
    weight_sum = sum(weights)
    volumes = [int(total_volume * weight / weight_sum) for weight in weights]
    volumes[-1] += total_volume - sum(volumes)
    return volumes


def _tick_size(price: float) -> float:
    if price < 1_000:
        return 1.0
    if price < 5_000:
        return 5.0
    if price < 10_000:
        return 10.0
    if price < 50_000:
        return 50.0
    if price < 100_000:
        return 100.0
    if price < 500_000:
        return 500.0
    return 1_000.0


def _daily_row_to_proxy_bars(
    *,
    symbol: str,
    trade_date: date,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: int,
    bars_per_day: int,
    timezone_name: str,
) -> tuple[list[MinuteBar], list[OrderbookSnapshot]]:
    if min(open_price, high_price, low_price, close_price) <= 0:
        return [], []

    high_anchor = max(open_price, high_price, low_price, close_price)
    low_anchor = min(open_price, high_price, low_price, close_price)
    if close_price >= open_price:
        anchors = [(0, open_price), (6, low_anchor), (18, high_anchor), (bars_per_day - 1, close_price)]
    else:
        anchors = [(0, open_price), (6, high_anchor), (18, low_anchor), (bars_per_day - 1, close_price)]

    tz = get_timezone(timezone_name)
    times = _market_times(bars_per_day)
    volumes = _volume_slices(volume, bars_per_day)
    closes = [_interpolate_price(index, anchors) for index in range(bars_per_day)]

    bars: list[MinuteBar] = []
    orderbooks: list[OrderbookSnapshot] = []
    previous_close = open_price
    for index, close_value in enumerate(closes):
        bar_open = previous_close if index else open_price
        bar_close = close_value
        bar_high = max(bar_open, bar_close)
        bar_low = min(bar_open, bar_close)
        if abs(bar_close - high_anchor) < 1e-9:
            bar_high = max(bar_high, high_anchor)
        if abs(bar_close - low_anchor) < 1e-9:
            bar_low = min(bar_low, low_anchor)
        bar_time = datetime.combine(trade_date, times[index], tzinfo=tz)
        bar_volume = volumes[index]
        bars.append(
            MinuteBar(
                symbol=symbol,
                bar_time=bar_time,
                open=round(bar_open, 6),
                high=round(bar_high, 6),
                low=round(bar_low, 6),
                close=round(bar_close, 6),
                volume=bar_volume,
                trade_count=max(1, bar_volume // 1_000),
            )
        )

        tick = _tick_size(bar_close)
        book_size = max(1, bar_volume // 2)
        orderbooks.append(
            OrderbookSnapshot(
                symbol=symbol,
                event_time=bar_time,
                bid_price=max(tick, bar_close - tick),
                ask_price=bar_close + tick,
                bid_size=book_size,
                ask_size=book_size,
                source=PYKRX_DAILY_PROXY_SOURCE,
            )
        )
        previous_close = bar_close

    return bars, orderbooks


def _fetch_pykrx_daily(symbol: str, start_date: date, end_date: date):
    from pykrx import stock

    return stock.get_market_ohlcv_by_date(
        start_date.strftime("%Y%m%d"),
        end_date.strftime("%Y%m%d"),
        symbol,
    )


def _count_learning_rows(sqlite_store, *, symbols: list[str], start_date: date, end_date: date, horizon_min: int) -> int:
    placeholders = ",".join("?" for _ in symbols)
    query = f"""
        SELECT COUNT(*) AS row_count
        FROM feature_model_inputs AS inputs
        INNER JOIN feature_labels AS labels
            ON inputs.symbol = labels.symbol
           AND inputs.event_time = labels.event_time
        WHERE labels.horizon_min = ?
          AND inputs.symbol IN ({placeholders})
          AND substr(inputs.event_time, 1, 10) >= ?
          AND substr(inputs.event_time, 1, 10) <= ?
    """
    row = sqlite_store._run_safe_read_query(
        query,
        (horizon_min, *symbols, start_date.isoformat(), end_date.isoformat()),
        single=True,
        missing_tables=("feature_model_inputs", "feature_labels"),
    )
    return int(row["row_count"]) if row is not None else 0


def _build_quality_report(
    *,
    sqlite_store,
    symbols: list[str],
    start_date: date,
    end_date: date,
    bars_per_day: int,
    expected_dates_by_symbol: dict[str, set[str]],
) -> tuple[dict[str, object], str | None, str | None, list[HistoricalSymbolSummary]]:
    placeholders = ",".join("?" for _ in symbols)
    rows = sqlite_store._run_safe_read_query(
        f"""
        SELECT
            symbol,
            substr(bar_time, 1, 10) AS trade_date,
            COUNT(*) AS row_count
        FROM curated_minute_bars
        WHERE symbol IN ({placeholders})
          AND substr(bar_time, 1, 10) >= ?
          AND substr(bar_time, 1, 10) <= ?
        GROUP BY symbol, substr(bar_time, 1, 10)
        ORDER BY symbol, trade_date
        """,
        (*symbols, start_date.isoformat(), end_date.isoformat()),
        missing_tables=("curated_minute_bars",),
    )
    counts_by_symbol: dict[str, dict[str, int]] = {symbol: {} for symbol in symbols}
    for row in rows if isinstance(rows, list) else []:
        counts_by_symbol[str(row["symbol"])][str(row["trade_date"])] = int(row["row_count"])

    summaries: list[HistoricalSymbolSummary] = []
    all_dates: list[str] = []
    complete_dates = 0
    partial_dates = 0
    for symbol in symbols:
        expected_dates = sorted(expected_dates_by_symbol.get(symbol, set()))
        symbol_counts = counts_by_symbol.get(symbol, {})
        missing_or_partial = [
            day for day in expected_dates
            if symbol_counts.get(day, 0) < bars_per_day
        ]
        complete_dates += sum(1 for day in expected_dates if symbol_counts.get(day, 0) >= bars_per_day)
        partial_dates += len(missing_or_partial)
        all_dates.extend(day for day, count in symbol_counts.items() if count > 0)
        summaries.append(
            HistoricalSymbolSummary(
                symbol=symbol,
                daily_rows=len(expected_dates),
                bars_written=sum(symbol_counts.get(day, 0) for day in expected_dates),
                first_date=min(expected_dates) if expected_dates else None,
                last_date=max(expected_dates) if expected_dates else None,
                missing_or_partial_dates=missing_or_partial[:20],
            )
        )

    quality = {
        "expected_complete_symbol_dates": sum(len(value) for value in expected_dates_by_symbol.values()),
        "complete_symbol_dates": complete_dates,
        "missing_or_partial_symbol_dates": partial_dates,
        "bars_per_complete_date": bars_per_day,
        "first_missing_or_partial_dates": {
            summary.symbol: summary.missing_or_partial_dates
            for summary in summaries
            if summary.missing_or_partial_dates
        },
    }
    return quality, (min(all_dates) if all_dates else None), (max(all_dates) if all_dates else None), summaries


def _write_reports(result: HistoricalCollectionResult) -> None:
    payload = result.to_dict()
    result.report_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Historical Collection Report",
        "",
        f"- source_plan: `{result.source_plan}`",
        f"- source: `{result.source}`",
        f"- period: `{result.start_date}` ~ `{result.end_date}`",
        f"- symbols: `{', '.join(result.symbols)}`",
        f"- bars_written: `{result.bars_written}`",
        f"- learning_rows_h15: `{result.learning_rows_h15}`",
        f"- bar_date_range: `{result.earliest_bar_date}` ~ `{result.latest_bar_date}`",
        "",
        "| symbol | daily rows | bars | first | last | missing/partial shown |",
        "|---|---:|---:|---|---|---:|",
    ]
    for summary in result.symbol_summaries:
        lines.append(
            f"| {summary.symbol} | {summary.daily_rows} | {summary.bars_written} | "
            f"{summary.first_date or ''} | {summary.last_date or ''} | {len(summary.missing_or_partial_dates)} |"
        )
    result.report_markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def collect_pykrx_daily_proxy_history(
    *,
    project_root: Path,
    symbols: list[str] | None = None,
    start_date: date = DEFAULT_START_DATE,
    end_date: date | None = None,
    bars_per_day: int = DEFAULT_BARS_PER_DAY,
    build_features: bool = True,
) -> HistoricalCollectionResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    resolved_end_date = end_date or now_local(settings.timezone).date()
    resolved_symbols = symbols or load_watchlist(project_root=settings.project_root)
    if not resolved_symbols:
        raise ValueError("No symbols were provided and watchlist is empty.")

    sqlite_store = get_sqlite_store(settings, busy_timeout_ms=60_000)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for historical collection.")

    range_start_time = datetime.combine(start_date, time(0, 0), tzinfo=get_timezone(settings.timezone))
    range_end_time = datetime.combine(resolved_end_date, time(23, 59, 59), tzinfo=get_timezone(settings.timezone))

    total_bars = 0
    total_orderbooks = 0
    expected_dates_by_symbol: dict[str, set[str]] = {}
    for symbol in resolved_symbols:
        daily_frame = _fetch_pykrx_daily(symbol, start_date, resolved_end_date)
        expected_dates_by_symbol[symbol] = set()
        bars: list[MinuteBar] = []
        orderbooks: list[OrderbookSnapshot] = []
        for index, row in daily_frame.iterrows():
            trade_date = index.to_pydatetime().date()
            day_bars, day_books = _daily_row_to_proxy_bars(
                symbol=symbol,
                trade_date=trade_date,
                open_price=float(row["시가"]),
                high_price=float(row["고가"]),
                low_price=float(row["저가"]),
                close_price=float(row["종가"]),
                volume=_as_int(row["거래량"]),
                bars_per_day=bars_per_day,
                timezone_name=settings.timezone,
            )
            if day_bars:
                expected_dates_by_symbol[symbol].add(trade_date.isoformat())
            bars.extend(day_bars)
            orderbooks.extend(day_books)

        sqlite_store.delete_raw_source_rows(
            "raw_orderbook_ticks",
            source=PYKRX_DAILY_PROXY_SOURCE,
            symbol=symbol,
            start_time=range_start_time,
            end_time=range_end_time,
        )
        sqlite_store.upsert_minute_bars_many(bars)
        sqlite_store.insert_orderbook_snapshots_many(orderbooks)
        total_bars += len(bars)
        total_orderbooks += len(orderbooks)

    feature_result = None
    if build_features:
        feature_result = build_feature_dataset_from_sqlite(
            project_root=settings.project_root,
            horizons=(15, 60),
            clear_existing=False,
            persist_runtime_artifacts=False,
        )

    learning_rows_h15 = _count_learning_rows(
        sqlite_store,
        symbols=resolved_symbols,
        start_date=start_date,
        end_date=resolved_end_date,
        horizon_min=15,
    )
    quality, earliest_bar_date, latest_bar_date, symbol_summaries = _build_quality_report(
        sqlite_store=sqlite_store,
        symbols=resolved_symbols,
        start_date=start_date,
        end_date=resolved_end_date,
        bars_per_day=bars_per_day,
        expected_dates_by_symbol=expected_dates_by_symbol,
    )
    report_dir = settings.runtime_data_dir / "reports" / "historical"
    report_dir.mkdir(parents=True, exist_ok=True)
    result = HistoricalCollectionResult(
        source_plan="B: pykrx daily OHLCV to 15-minute proxy bars",
        source=PYKRX_DAILY_PROXY_SOURCE,
        start_date=start_date.isoformat(),
        end_date=resolved_end_date.isoformat(),
        bars_per_day=bars_per_day,
        symbols=resolved_symbols,
        bars_written=total_bars,
        orderbooks_written=total_orderbooks,
        feature_rows_written=feature_result.features_written if feature_result else 0,
        label_rows_written=feature_result.labels_written if feature_result else 0,
        learning_rows_h15=learning_rows_h15,
        earliest_bar_date=earliest_bar_date,
        latest_bar_date=latest_bar_date,
        quality=quality,
        symbol_summaries=symbol_summaries,
        report_json_path=report_dir / "latest-historical-collection.json",
        report_markdown_path=report_dir / "latest-historical-collection.md",
    )
    _write_reports(result)
    return result
