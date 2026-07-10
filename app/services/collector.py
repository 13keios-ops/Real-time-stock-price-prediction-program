"""Collector services for KIS snapshot ingestion."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from app.brokers.kis_auth import KisApiError
from app.brokers.kis_readonly import get_kis_readonly_client
from app.collectors.market_data import market_tick_from_kis_quote, orderbook_from_kis_quote
from app.config.settings import load_settings
from app.observability.logging import configure_logging
from app.storage.runtime_writer import RuntimeWriter
from app.universe.watchlist import load_watchlist
from app.utils.time import now_local


LOGGER = logging.getLogger(__name__)
REST_BETWEEN_REQUESTS_SECONDS = 0.35
RATE_LIMIT_RETRY_COUNT = 2
RATE_LIMIT_BACKOFF_SECONDS = 1.2


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


@dataclass(slots=True)
class WatchlistPollingResult:
    iterations_requested: int
    iterations_completed: int
    symbols_requested: list[str]
    success_events: int
    failure_events: int
    runtime_root: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "iterations_requested": self.iterations_requested,
            "iterations_completed": self.iterations_completed,
            "symbols_requested": self.symbols_requested,
            "success_events": self.success_events,
            "failure_events": self.failure_events,
            "runtime_root": str(self.runtime_root),
        }


def _is_rate_limit_error(exc: KisApiError) -> bool:
    message = str(exc)
    return "EGW00201" in message or "초당 거래건수를 초과" in message


def _call_kis_with_retry(fetch, *, symbol: str, request_name: str):
    last_exc: KisApiError | None = None
    for attempt in range(RATE_LIMIT_RETRY_COUNT + 1):
        try:
            return fetch()
        except KisApiError as exc:
            last_exc = exc
            if not _is_rate_limit_error(exc) or attempt >= RATE_LIMIT_RETRY_COUNT:
                raise
            delay_seconds = RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1)
            LOGGER.warning(
                "KIS %s rate-limited for %s on attempt %s/%s. Retrying after %.2fs.",
                request_name,
                symbol,
                attempt + 1,
                RATE_LIMIT_RETRY_COUNT + 1,
                delay_seconds,
            )
            time.sleep(delay_seconds)
    if last_exc is not None:
        raise last_exc
    raise KisApiError(f"KIS {request_name} call did not return a result for {symbol}.")


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

    client = get_kis_readonly_client(settings)
    writer = RuntimeWriter.from_settings(settings)

    succeeded: list[str] = []
    failed: list[dict[str, str]] = []

    for symbol_index, symbol in enumerate(resolved_symbols):
        try:
            current_quote = _call_kis_with_retry(
                lambda: client.get_current_price(symbol=symbol),
                symbol=symbol,
                request_name="current_price",
            )
            time.sleep(REST_BETWEEN_REQUESTS_SECONDS)
            orderbook_quote = _call_kis_with_retry(
                lambda: client.get_orderbook(symbol=symbol),
                symbol=symbol,
                request_name="orderbook",
            )
            event_time = now_local(settings.timezone)

            tick = market_tick_from_kis_quote(current_quote, event_time=event_time)
            orderbook = orderbook_from_kis_quote(orderbook_quote, event_time=event_time)
            writer.write_market_tick(tick)
            writer.write_orderbook_snapshot(orderbook)
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
        if symbol_index < len(resolved_symbols) - 1:
            time.sleep(REST_BETWEEN_REQUESTS_SECONDS)

    return WatchlistSnapshotResult(
        symbols_requested=resolved_symbols,
        symbols_succeeded=succeeded,
        failed=failed,
        runtime_root=settings.runtime_data_dir,
    )


def poll_kis_watchlist_snapshots(
    project_root: Path,
    symbols: list[str] | None = None,
    watchlist_path: str | Path | None = None,
    iterations: int = 1,
    interval_seconds: float = 0.0,
) -> WatchlistPollingResult:
    if iterations <= 0:
        raise ValueError("iterations must be positive.")
    if interval_seconds < 0:
        raise ValueError("interval_seconds cannot be negative.")

    resolved_symbols = symbols or load_watchlist(project_root=project_root, watchlist_path=watchlist_path)
    if not resolved_symbols:
        raise ValueError("No symbols were provided and watchlist is empty.")

    completed = 0
    success_events = 0
    failure_events = 0
    runtime_root = (project_root / "runtime-data").resolve()

    for iteration in range(iterations):
        result = collect_kis_watchlist_snapshots(
            project_root=project_root,
            symbols=resolved_symbols,
            watchlist_path=watchlist_path,
        )
        completed += 1
        success_events += len(result.symbols_succeeded)
        failure_events += len(result.failed)
        runtime_root = result.runtime_root
        LOGGER.info(
            "Watchlist polling iteration %s/%s complete: success=%s failure=%s",
            iteration + 1,
            iterations,
            len(result.symbols_succeeded),
            len(result.failed),
        )
        if iteration < iterations - 1 and interval_seconds > 0:
            time.sleep(interval_seconds)

    return WatchlistPollingResult(
        iterations_requested=iterations,
        iterations_completed=completed,
        symbols_requested=resolved_symbols,
        success_events=success_events,
        failure_events=failure_events,
        runtime_root=runtime_root,
    )
