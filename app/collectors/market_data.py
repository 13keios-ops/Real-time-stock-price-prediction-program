"""Sample market data builders used for early integration testing."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from app.brokers.kis_quote_rest import KisCurrentPriceQuote, KisOrderbookQuote
from app.storage.contracts import MarketTickEvent, OrderbookSnapshot
from app.utils.time import get_timezone


def build_sample_ticks(symbol: str, timezone_name: str = "Asia/Seoul") -> list[MarketTickEvent]:
    tz = get_timezone(timezone_name)
    base_time = datetime(2026, 4, 11, 9, 20, tzinfo=tz)
    return [
        MarketTickEvent(symbol=symbol, event_time=base_time, price=70000.0, volume=120, source="sample"),
        MarketTickEvent(symbol=symbol, event_time=base_time.replace(second=20), price=70100.0, volume=150, source="sample"),
        MarketTickEvent(symbol=symbol, event_time=base_time.replace(second=40), price=70200.0, volume=190, source="sample"),
    ]


def build_sample_orderbook(symbol: str, timezone_name: str = "Asia/Seoul") -> OrderbookSnapshot:
    tz = get_timezone(timezone_name)
    return OrderbookSnapshot(
        symbol=symbol,
        event_time=datetime(2026, 4, 11, 9, 20, 45, tzinfo=tz),
        bid_price=70150.0,
        ask_price=70200.0,
        bid_size=820,
        ask_size=470,
        source="sample",
    )


def market_tick_from_kis_quote(
    quote: KisCurrentPriceQuote,
    event_time: datetime,
    source: str = "kis-rest",
) -> MarketTickEvent:
    return MarketTickEvent(
        symbol=quote.symbol,
        event_time=event_time,
        price=float(quote.current_price),
        volume=max(quote.accumulated_volume, 0),
        source=source,
    )


def orderbook_from_kis_quote(
    quote: KisOrderbookQuote,
    event_time: datetime,
    source: str = "kis-rest",
) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        symbol=quote.symbol,
        event_time=event_time,
        bid_price=float(quote.bid_price_1),
        ask_price=float(quote.ask_price_1),
        bid_size=quote.bid_size_1,
        ask_size=quote.ask_size_1,
        source=source,
    )


def market_tick_from_kis_ws_record(
    record: Mapping[str, str],
    event_time: datetime,
    source: str = "kis-ws",
) -> MarketTickEvent:
    price = float(record.get("STCK_PRPR", "0") or 0)
    volume = int(record.get("CNTG_VOL", "0") or 0)
    symbol = str(record.get("MKSC_SHRN_ISCD", "")).strip()
    return MarketTickEvent(
        symbol=symbol,
        event_time=event_time,
        price=price,
        volume=volume,
        source=source,
    )


def orderbook_from_kis_ws_record(
    record: Mapping[str, str],
    event_time: datetime,
    source: str = "kis-ws",
) -> OrderbookSnapshot:
    symbol = str(record.get("MKSC_SHRN_ISCD", "")).strip()
    bid_price = float(record.get("BIDP1", "0") or 0)
    ask_price = float(record.get("ASKP1", "0") or 0)
    bid_size = int(record.get("BIDP_RSQN1", "0") or 0)
    ask_size = int(record.get("ASKP_RSQN1", "0") or 0)
    return OrderbookSnapshot(
        symbol=symbol,
        event_time=event_time,
        bid_price=bid_price,
        ask_price=ask_price,
        bid_size=bid_size,
        ask_size=ask_size,
        source=source,
    )


def event_time_from_kis_ws_record(
    record: Mapping[str, str],
    timezone_name: str = "Asia/Seoul",
    fallback: datetime | None = None,
) -> datetime:
    fallback = fallback or datetime.now(tz=get_timezone(timezone_name))
    date_text = str(record.get("BSOP_DATE", "")).strip()
    time_text = str(record.get("STCK_CNTG_HOUR", "") or record.get("BSOP_HOUR", "")).strip()
    if not time_text:
        return fallback

    padded_time = time_text.ljust(6, "0")[:6]
    if date_text and len(date_text) == 8 and date_text.isdigit():
        year = int(date_text[0:4])
        month = int(date_text[4:6])
        day = int(date_text[6:8])
    else:
        year = fallback.year
        month = fallback.month
        day = fallback.day

    hour = int(padded_time[0:2])
    minute = int(padded_time[2:4])
    second = int(padded_time[4:6])
    return fallback.replace(year=year, month=month, day=day, hour=hour, minute=minute, second=second, microsecond=0)
