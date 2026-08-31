"""Read-only KIS REST client wrapper for live account observation."""

from __future__ import annotations

from app.brokers.kis_auth import KisTokenManager, get_kis_profile
from app.brokers.kis_quote_rest import (
    KisAccountBalanceSnapshot,
    KisCurrentPriceQuote,
    KisDailyOrderFillRecord,
    KisIntradayMinuteRecord,
    KisOrderbookQuote,
    KisOrderabilitySnapshot,
    KisRestQuoteClient,
)
from app.config.settings import AppSettings


class KisReadOnlyClient:
    """Expose only KIS REST read operations.

    The wrapped client is intentionally private; callers should not reach into
    it to access raw order methods.
    """

    def __init__(self, client: KisRestQuoteClient) -> None:
        self._client = client

    def describe(self) -> dict[str, str]:
        description = dict(self._client.describe())
        description["access"] = "read-only"
        return description

    @property
    def last_response_headers(self) -> dict[str, str]:
        """Return a copy of the most recent read response headers."""
        return dict(self._client.last_response_headers)

    @property
    def last_daily_order_fill_query(self) -> dict[str, object]:
        """Return sanitized pagination metadata for the latest order/fill query."""
        return dict(self._client.last_daily_order_fill_query)

    def get_current_price(self, symbol: str, market_code: str = "J") -> KisCurrentPriceQuote:
        return self._client.get_current_price(symbol=symbol, market_code=market_code)

    def get_orderbook(self, symbol: str, market_code: str = "J") -> KisOrderbookQuote:
        return self._client.get_orderbook(symbol=symbol, market_code=market_code)

    def get_intraday_minute_chart(
        self,
        symbol: str,
        *,
        input_hour: str = "153000",
        market_code: str = "J",
        include_past_data: bool = True,
    ) -> list[KisIntradayMinuteRecord]:
        return self._client.get_intraday_minute_chart(
            symbol,
            input_hour=input_hour,
            market_code=market_code,
            include_past_data=include_past_data,
        )

    def get_account_balance(self, *, inqr_dvsn: str = "02", max_pages: int = 10) -> KisAccountBalanceSnapshot:
        return self._client.get_account_balance(inqr_dvsn=inqr_dvsn, max_pages=max_pages)

    def get_orderability(
        self,
        *,
        symbol: str,
        order_price: float,
        order_type: str = "01",
        include_cma_evaluation: bool = False,
        include_overseas: bool = False,
    ) -> KisOrderabilitySnapshot:
        return self._client.get_orderability(
            symbol=symbol,
            order_price=order_price,
            order_type=order_type,
            include_cma_evaluation=include_cma_evaluation,
            include_overseas=include_overseas,
        )

    def get_daily_order_fills(
        self,
        *,
        start_date: str,
        end_date: str,
        symbol: str = "",
        order_no: str = "",
        side_filter: str = "00",
        filled_filter: str = "00",
        order_filter_3: str = "00",
        order_filter_1: str = "",
        exchange_code: str = "KRX",
        max_pages: int = 10,
    ) -> list[KisDailyOrderFillRecord]:
        return self._client.get_daily_order_fills(
            start_date=start_date,
            end_date=end_date,
            symbol=symbol,
            order_no=order_no,
            side_filter=side_filter,
            filled_filter=filled_filter,
            order_filter_3=order_filter_3,
            order_filter_1=order_filter_1,
            exchange_code=exchange_code,
            max_pages=max_pages,
        )


def get_kis_readonly_client(
    settings: AppSettings,
    *,
    mode: str | None = None,
    timeout_seconds: int = 10,
) -> KisReadOnlyClient:
    resolved_mode = (mode or settings.trading_mode).strip().lower()
    if resolved_mode not in {"paper", "live"}:
        raise ValueError("KIS read-only client only supports mode='paper' or mode='live'.")
    profile = get_kis_profile(settings, resolved_mode)
    token_manager = KisTokenManager(profile)
    client = KisRestQuoteClient(profile=profile, token_manager=token_manager, timeout_seconds=timeout_seconds)
    return KisReadOnlyClient(client)


def get_kis_live_readonly_client(
    settings: AppSettings,
    *,
    mode: str = "live",
    timeout_seconds: int = 10,
) -> KisReadOnlyClient:
    resolved_mode = mode.strip().lower()
    if resolved_mode != "live":
        raise ValueError("KIS read-only live client only supports mode='live'.")
    return get_kis_readonly_client(settings, mode="live", timeout_seconds=timeout_seconds)
