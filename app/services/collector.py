"""Collector services for KIS snapshot ingestion."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.brokers.kis_auth import KisApiError, KisTokenManager, get_active_kis_profile
from app.brokers.kis_quote_rest import KisRestQuoteClient
from app.collectors.market_data import market_tick_from_kis_quote, orderbook_from_kis_quote
from app.config.settings import load_settings
from app.observability.logging import configure_logging
from app.storage.jsonl_store import JsonlArtifactStore
from app.universe.watchlist import load_watchlist
from app.utils.time import now_local


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class WatchlistSnapshotResult:
    symbols_requested: list[str]
    symbols_succeeded: list[str]
    failed: list[dict[str, str]]
    runtime_root: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "symbols_requested": self.symbols_requested,
            "symbols_succeeded": self.symbols_succeeded,
            "failed": self.failed,
            "runtime_root": str(self.runtime_root),
        }


def collect_kis_watchlist_snapshots(
    project_root: Path,
    symbols: list[str] | None = None,
    watchlist_path: str | Path | None = None,
) -> WatchlistSnapshotResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    resolved_symbols = symbols or load_watchlist(project_root=project_root, watchlist_path=watchlist_path)
    if not resolved_symbols:
        raise ValueError("No symbols were provided and watchlist is empty.")

    profile = get_active_kis_profile(settings)
    token_manager = KisTokenManager(profile)
    client = KisRestQuoteClient(profile=profile, token_manager=token_manager)
    store = JsonlArtifactStore(settings.runtime_data_dir)

    succeeded: list[str] = []
    failed: list[dict[str, str]] = []

    for symbol in resolved_symbols:
        try:
            current_quote = client.get_current_price(symbol=symbol)
            orderbook_quote = client.get_orderbook(symbol=symbol)
            event_time = now_local(settings.timezone)

            tick = market_tick_from_kis_quote(current_quote, event_time=event_time)
            orderbook = orderbook_from_kis_quote(orderbook_quote, event_time=event_time)
            store.append("raw", "market_ticks", tick.to_record(), tick.event_time)
            store.append("raw", "orderbook_ticks", orderbook.to_record(), orderbook.event_time)
            succeeded.append(symbol)
            LOGGER.info(
                "Watchlist snapshot stored for %s current=%s ask1=%s bid1=%s",
                symbol,
                current_quote.current_price,
                orderbook_quote.ask_price_1,
                orderbook_quote.bid_price_1,
            )
        except KisApiError as exc:
            failed.append({"symbol": symbol, "error": str(exc)})
            LOGGER.warning("Watchlist snapshot failed for %s: %s", symbol, exc)

    return WatchlistSnapshotResult(
        symbols_requested=resolved_symbols,
        symbols_succeeded=succeeded,
        failed=failed,
        runtime_root=settings.runtime_data_dir,
    )
