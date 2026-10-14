"""Read-only KIS REST client wrapper for live account observation."""

from __future__ import annotations

from urllib.parse import urlsplit

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

    def get_candidate_response(self, *, path, tr_id, query_params):
        allowed = {
            '/uapi/domestic-stock/v1/quotations/inquire-index-price': 'FHPUP02100000',
            '/uapi/domestic-stock/v1/quotations/volume-rank': 'FHPST01710000',
            '/uapi/domestic-stock/v1/quotations/inquire-price': 'FHKST01010100',
            '/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn': 'FHKST01010200',
        }
        if allowed.get(path) != tr_id:
            raise ValueError('Only candidate quote GET endpoints allowed')
        return self._client._request_response(path=path, tr_id=tr_id, query_params=query_params,
            allow_retry=False, allow_business_error=True)

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


def get_kis_paper_candidate_client(profile, token_manager):
    url = urlsplit(profile.rest_url)
    if (profile.mode != 'paper' or url.scheme != 'https'
            or url.hostname != 'openapivts.koreainvestment.com' or url.port != 29443
            or url.username or url.password or url.query or url.fragment or url.path not in ('', '/')):
        raise ValueError('Official paper endpoint required')
    if getattr(token_manager, 'profile', profile) != profile:
        raise ValueError('Token profile mismatch')

    class CachedOnly:
        def get_access_token(self, force_refresh=False):
            if force_refresh:
                raise ValueError('Token refresh forbidden')
            token = token_manager.load_cached_token()
            if token is None or token.is_expired:
                raise ValueError('Valid cached token required')
            return token

    return KisReadOnlyClient(KisRestQuoteClient(profile=profile,
        token_manager=CachedOnly(), timeout_seconds=3))


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
