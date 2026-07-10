"""Synthetic market data generators for local development."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from pathlib import Path

from app.config.settings import load_settings
from app.observability.logging import configure_logging
from app.storage.contracts import MarketTickEvent, OrderbookSnapshot
from app.storage.runtime_writer import RuntimeWriter
from app.utils.time import get_timezone


@dataclass(slots=True)
class SyntheticSeedResult:
    symbol: str
    minutes_seeded: int
    runtime_root: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "minutes_seeded": self.minutes_seeded,
            "runtime_root": str(self.runtime_root),
        }


def seed_synthetic_intraday_data(project_root: Path, symbol: str = "005930", minutes: int = 80) -> SyntheticSeedResult:
    if minutes <= 0:
        raise ValueError("minutes must be positive.")

    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    writer = RuntimeWriter.from_settings(settings)
    kst = get_timezone(settings.timezone)
    base_time = datetime(2026, 4, 11, 9, 15, tzinfo=kst)

    for minute_index in range(minutes):
        event_time = base_time + timedelta(minutes=minute_index)
        # Keep all three direction labels present in a short development run.
        # Regime boundaries are continuous so the down segment is not masked by
        # an artificial upward jump at the next segment.
        segment = minute_index // 12
        local_index = minute_index % 12
        regime = segment % 3
        regime_base = (0, 720, 0)[regime]
        slope = (60, -60, 0)[regime]
        drift = regime_base + local_index * slope

        wave = math.sin(minute_index / 3) * 55
        micro = ((minute_index % 5) - 2) * 6
        base_price = 70000 + drift + wave + micro
        spread = 8 + (minute_index % 3)
        bid_size = 950 + ((regime + 1) * 40) + (minute_index % 7) * 12
        ask_size = 900 + ((3 - regime) * 35) + (minute_index % 5) * 10
        writer.write_market_tick(
            MarketTickEvent(
                symbol=symbol,
                event_time=event_time,
                price=float(round(base_price, 2)),
                volume=120 + (minute_index * 3) + (regime * 15),
                source="synthetic",
            )
        )
        writer.write_orderbook_snapshot(
            OrderbookSnapshot(
                symbol=symbol,
                event_time=event_time,
                bid_price=float(round(base_price - spread, 2)),
                ask_price=float(round(base_price + spread, 2)),
                bid_size=bid_size,
                ask_size=ask_size,
                source="synthetic",
            )
        )

    return SyntheticSeedResult(
        symbol=symbol,
        minutes_seeded=minutes,
        runtime_root=settings.runtime_data_dir,
    )
