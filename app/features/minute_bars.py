"""Feature builders for minute bars and baseline engineered features."""

from __future__ import annotations

from statistics import mean

from app.storage.contracts import FeatureSnapshot, MarketTickEvent, MinuteBar, OrderbookSnapshot


def aggregate_ticks_to_minute_bar(symbol: str, ticks: list[MarketTickEvent]) -> MinuteBar:
    if not ticks:
        raise ValueError("At least one tick is required to build a minute bar.")

    ordered = sorted(ticks, key=lambda item: item.event_time)
    prices = [tick.price for tick in ordered]
    volumes = [tick.volume for tick in ordered]
    return MinuteBar(
        symbol=symbol,
        bar_time=ordered[0].event_time.replace(second=0, microsecond=0),
        open=prices[0],
        high=max(prices),
        low=min(prices),
        close=prices[-1],
        volume=sum(volumes),
        trade_count=len(ordered),
    )


def build_feature_snapshot(
    bar: MinuteBar,
    orderbook: OrderbookSnapshot,
    feature_set_version: str,
) -> FeatureSnapshot:
    imbalance = 0.0
    mid_price = 0.0
    spread_bps = 0.0
    if orderbook.is_valid_for_trading:
        total_size = orderbook.bid_size + orderbook.ask_size
        if total_size > 0:
            imbalance = (orderbook.bid_size - orderbook.ask_size) / total_size
        mid_price = mean([orderbook.bid_price, orderbook.ask_price])
        spread_bps = orderbook.spread_bps

    values = {
        "return_1m_pct": ((bar.close - bar.open) / bar.open) * 100,
        "hl_range_pct": ((bar.high - bar.low) / bar.open) * 100,
        "avg_trade_size": bar.volume / max(bar.trade_count, 1),
        "mid_price": mid_price,
        "spread_bps": spread_bps,
        "bid_ask_imbalance": imbalance,
    }
    return FeatureSnapshot(
        symbol=bar.symbol,
        event_time=bar.bar_time,
        feature_set_version=feature_set_version,
        values=values,
    )
