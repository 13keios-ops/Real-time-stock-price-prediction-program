"""KIS REST quote client for domestic stock market data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.brokers.kis_auth import KisApiError, KisAuthProfile, KisTokenManager


CURRENT_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
CURRENT_PRICE_TR_ID = "FHKST01010100"
ORDERBOOK_PATH = "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
ORDERBOOK_TR_ID = "FHKST01010200"


def _as_int(payload: dict, key: str) -> int:
    raw = str(payload.get(key, "0")).strip() or "0"
    return int(raw)


def _as_float(payload: dict, key: str) -> float:
    raw = str(payload.get(key, "0")).strip() or "0"
    return float(raw)


@dataclass(slots=True)
class KisCurrentPriceQuote:
    symbol: str
    market_code: str
    current_price: int
    open_price: int
    high_price: int
    low_price: int
    prev_close_price: int
    accumulated_volume: int
    accumulated_trading_value: int
    price_change_sign: str
    price_change_abs: int
    price_change_pct: float


@dataclass(slots=True)
class KisOrderbookQuote:
    symbol: str
    market_code: str
    ask_price_1: int
    bid_price_1: int
    ask_size_1: int
    bid_size_1: int
    total_ask_size: int
    total_bid_size: int
    expected_match_price: int
    expected_match_qty: int


class KisRestQuoteClient:
    def __init__(self, profile: KisAuthProfile, token_manager: KisTokenManager, timeout_seconds: int = 10) -> None:
        self.profile = profile
        self.token_manager = token_manager
        self.timeout_seconds = timeout_seconds

    def describe(self) -> dict[str, str]:
        return {
            "transport": "rest",
            "base_url": self.profile.rest_url,
            "status": "active",
        }

    def _request(self, path: str, tr_id: str, query_params: dict[str, str]) -> dict:
        token = self.token_manager.get_access_token()
        encoded_query = urlencode(query_params)
        request = Request(
            url=f"{self.profile.rest_url}{path}?{encoded_query}",
            headers={
                "authorization": token.authorization_header,
                "appkey": self.profile.app_key,
                "appsecret": self.profile.app_secret,
                "tr_id": tr_id,
                "custtype": self.profile.customer_type,
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise KisApiError(f"KIS HTTP error {exc.code}: {body}") from exc
        except URLError as exc:
            raise KisApiError(f"KIS network error: {exc}") from exc

        rt_cd = str(payload.get("rt_cd", ""))
        if rt_cd and rt_cd != "0":
            message = payload.get("msg1") or payload.get("msg_cd") or payload
            raise KisApiError(f"KIS REST quote error: {message}")
        return payload

    def get_current_price(self, symbol: str, market_code: str = "J") -> KisCurrentPriceQuote:
        payload = self._request(
            path=CURRENT_PRICE_PATH,
            tr_id=CURRENT_PRICE_TR_ID,
            query_params={
                "FID_COND_MRKT_DIV_CODE": market_code,
                "FID_INPUT_ISCD": symbol,
            },
        )
        output = payload.get("output", {})
        return KisCurrentPriceQuote(
            symbol=symbol,
            market_code=market_code,
            current_price=_as_int(output, "stck_prpr"),
            open_price=_as_int(output, "stck_oprc"),
            high_price=_as_int(output, "stck_hgpr"),
            low_price=_as_int(output, "stck_lwpr"),
            prev_close_price=_as_int(output, "stck_sdpr"),
            accumulated_volume=_as_int(output, "acml_vol"),
            accumulated_trading_value=_as_int(output, "acml_tr_pbmn"),
            price_change_sign=str(output.get("prdy_vrss_sign", "")),
            price_change_abs=_as_int(output, "prdy_vrss"),
            price_change_pct=_as_float(output, "prdy_ctrt"),
        )

    def get_orderbook(self, symbol: str, market_code: str = "J") -> KisOrderbookQuote:
        payload = self._request(
            path=ORDERBOOK_PATH,
            tr_id=ORDERBOOK_TR_ID,
            query_params={
                "FID_COND_MRKT_DIV_CODE": market_code,
                "FID_INPUT_ISCD": symbol,
            },
        )
        output = payload.get("output1", payload.get("output", {}))
        return KisOrderbookQuote(
            symbol=symbol,
            market_code=market_code,
            ask_price_1=_as_int(output, "askp1"),
            bid_price_1=_as_int(output, "bidp1"),
            ask_size_1=_as_int(output, "askp_rsqn1"),
            bid_size_1=_as_int(output, "bidp_rsqn1"),
            total_ask_size=_as_int(output, "total_askp_rsqn"),
            total_bid_size=_as_int(output, "total_bidp_rsqn"),
            expected_match_price=_as_int(output, "antc_cnpr"),
            expected_match_qty=_as_int(output, "antc_cnqn"),
        )
