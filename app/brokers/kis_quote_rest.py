"""KIS REST quote client for domestic stock market data, account views, and paper/live order submission."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.brokers.kis_auth import KisApiError, KisAuthProfile, KisTokenManager


CURRENT_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
CURRENT_PRICE_TR_ID = "FHKST01010100"
ORDERBOOK_PATH = "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
ORDERBOOK_TR_ID = "FHKST01010200"
INTRADAY_MINUTE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
INTRADAY_MINUTE_TR_ID = "FHKST03010200"
ACCOUNT_BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
ACCOUNT_BALANCE_TR_ID_LIVE = "TTTC8434R"
ACCOUNT_BALANCE_TR_ID_PAPER = "VTTC8434R"
ORDER_CASH_PATH = "/uapi/domestic-stock/v1/trading/order-cash"
ORDER_CASH_TR_ID_BUY_LIVE = "TTTC0012U"
ORDER_CASH_TR_ID_SELL_LIVE = "TTTC0011U"
ORDER_CASH_TR_ID_BUY_PAPER = "VTTC0012U"
ORDER_CASH_TR_ID_SELL_PAPER = "VTTC0011U"
ORDER_RVSECNCL_PATH = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
ORDER_RVSECNCL_TR_ID_LIVE = "TTTC0803U"
ORDER_RVSECNCL_TR_ID_PAPER = "VTTC0803U"
ORDER_DAILY_CCLD_PATH = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
ORDER_DAILY_CCLD_TR_ID_LIVE = "TTTC0081R"
ORDER_DAILY_CCLD_TR_ID_PAPER = "VTTC0081R"
ORDERABILITY_PATH = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
ORDERABILITY_TR_ID_LIVE = "TTTC8908R"
ORDERABILITY_TR_ID_PAPER = "VTTC8908R"
KRX_INSTRUMENT_COMMON_STOCK = "common_stock"
KRX_INSTRUMENT_ETF_ETN = "etf_etn"
KRX_SUPPORTED_INSTRUMENT_TYPES = frozenset(
    {KRX_INSTRUMENT_COMMON_STOCK, KRX_INSTRUMENT_ETF_ETN}
)


def krx_tick_size(price: float | int | Decimal, *, instrument_type: str) -> int:
    """Return the KRX quotation unit for an explicitly classified instrument."""

    try:
        value = Decimal(str(price))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Order limit price must be a finite positive number.") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError("Order limit price must be a finite positive number.")
    if instrument_type not in KRX_SUPPORTED_INSTRUMENT_TYPES:
        raise ValueError(f"Unsupported KRX instrument type: {instrument_type}")
    if instrument_type == KRX_INSTRUMENT_ETF_ETN:
        return 1 if value < Decimal("2000") else 5
    if value < Decimal("2000"):
        return 1
    if value < Decimal("5000"):
        return 5
    if value < Decimal("20000"):
        return 10
    if value < Decimal("50000"):
        return 50
    if value < Decimal("200000"):
        return 100
    if value < Decimal("500000"):
        return 500
    return 1000


def normalize_krx_limit_price(
    price: float | int | Decimal,
    *,
    side: str,
    instrument_type: str,
) -> int:
    """Snap a max-buy/min-sell limit to a valid KRX quotation price."""

    normalized_side = side.strip().lower()
    if normalized_side not in {"buy", "sell"}:
        raise ValueError("Order side must be either 'buy' or 'sell'.")
    tick = Decimal(krx_tick_size(price, instrument_type=instrument_type))
    value = Decimal(str(price))
    rounding = ROUND_FLOOR if normalized_side == "buy" else ROUND_CEILING
    normalized = int((value / tick).to_integral_value(rounding=rounding) * tick)
    if normalized <= 0:
        raise ValueError("Normalized order limit price must be positive.")
    return normalized


def _business_error_detail(payload: dict) -> str:
    return json.dumps(
        {
            "rt_cd": str(payload.get("rt_cd") or ""),
            "msg_cd": str(payload.get("msg_cd") or ""),
            "msg1": str(payload.get("msg1") or ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _as_int(payload: dict, key: str) -> int:
    raw = str(payload.get(key, "0")).strip().replace(",", "") or "0"
    return int(float(raw))


def _as_float(payload: dict, key: str) -> float:
    raw = str(payload.get(key, "0")).strip().replace(",", "") or "0"
    return float(raw)


def _as_text(payload: dict, key: str) -> str:
    return str(payload.get(key, "")).strip()


def _mask_account(account_no: str) -> str:
    if len(account_no) <= 4:
        return "*" * len(account_no)
    return f"{account_no[:4]}{'*' * max(len(account_no) - 4, 0)}"


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


@dataclass(slots=True)
class KisIntradayMinuteRecord:
    symbol: str
    market_code: str
    trade_date: str
    trade_time: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    raw_output: dict


@dataclass(slots=True)
class KisBalancePosition:
    symbol: str
    name: str
    holding_qty: int
    orderable_qty: int
    average_buy_price: float
    buy_amount: int
    current_price: int
    evaluation_amount: int
    evaluation_profit_loss_amount: int
    evaluation_profit_loss_pct: float


@dataclass(slots=True)
class KisAccountBalanceSnapshot:
    mode: str
    account_no_masked: str
    product_code: str
    positions: list[KisBalancePosition]
    cash_balance: int
    stock_evaluation_amount: int
    total_evaluation_amount: int
    total_purchase_amount: int
    total_profit_loss_amount: int
    total_asset_amount: int
    summary_row_count: int
    position_row_count: int


@dataclass(slots=True)
class KisOrderabilitySnapshot:
    mode: str
    symbol: str
    order_price: float
    order_type: str
    rt_cd: str
    message_code: str
    message: str
    orderable_cash: int
    non_receivable_buy_amount: int
    non_receivable_buy_qty: int
    max_buy_amount: int
    max_buy_qty: int


@dataclass(slots=True)
class KisCashOrderResult:
    mode: str
    side: str
    symbol: str
    qty: int
    order_type: str
    limit_price: float
    broker_order_no: str
    broker_branch_no: str
    order_time: str
    message_code: str
    message: str
    raw_output: dict


@dataclass(slots=True)
class KisDailyOrderFillRecord:
    mode: str
    order_date: str
    broker_branch_no: str
    broker_order_no: str
    original_order_no: str
    symbol: str
    symbol_name: str
    side: str
    side_name: str
    order_type_code: str
    order_type_name: str
    order_time: str
    order_qty: int
    order_price: float
    filled_qty: int
    remaining_qty: int
    avg_fill_price: float
    filled_amount: float
    cancel_confirm_qty: int
    reject_qty: int
    cancel_yn: bool
    exchange_id: str
    raw_output: dict


def _as_bool(payload: dict, key: str) -> bool:
    value = str(payload.get(key, "")).strip().upper()
    return value in {"Y", "1", "TRUE", "T"}


def _first_present(payload: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in payload and str(payload.get(key, "")).strip():
            return str(payload.get(key, "")).strip()
    return ""


def _first_int(payload: dict, keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in payload and str(payload.get(key, "")).strip():
            return _as_int(payload, key)
    return 0


def _first_float(payload: dict, keys: tuple[str, ...]) -> float:
    for key in keys:
        if key in payload and str(payload.get(key, "")).strip():
            return _as_float(payload, key)
    return 0.0


class KisRestQuoteClient:
    def __init__(self, profile: KisAuthProfile, token_manager: KisTokenManager, timeout_seconds: int = 10) -> None:
        self.profile = profile
        self.token_manager = token_manager
        self.timeout_seconds = timeout_seconds
        self._last_response_headers: dict[str, str] = {}
        self._last_daily_order_fill_query: dict[str, object] = {}

    def describe(self) -> dict[str, str]:
        return {
            "transport": "rest",
            "base_url": self.profile.rest_url,
            "status": "active",
        }

    @property
    def last_response_headers(self) -> dict[str, str]:
        """Return a copy of the last successful response headers for read-only diagnostics."""
        return dict(self._last_response_headers)

    @property
    def last_daily_order_fill_query(self) -> dict[str, object]:
        """Return sanitized pagination metadata for the latest order/fill query."""
        return dict(self._last_daily_order_fill_query)

    def _request_response(
        self,
        path: str,
        tr_id: str,
        query_params: dict[str, str],
        *,
        extra_headers: dict[str, str] | None = None,
        allow_retry: bool = True,
        allow_business_error: bool = False,
    ) -> tuple[dict, dict[str, str]]:
        self._last_response_headers = {}
        token = self.token_manager.get_access_token()
        encoded_query = urlencode(query_params)
        headers = {
            "authorization": token.authorization_header,
            "appkey": self.profile.app_key,
            "appsecret": self.profile.app_secret,
            "tr_id": tr_id,
            "custtype": self.profile.customer_type,
        }
        if extra_headers:
            headers.update(extra_headers)
        request = Request(
            url=f"{self.profile.rest_url}{path}?{encoded_query}",
            headers=headers,
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
                response_headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            if allow_retry and any(code in body for code in ("EGW00121", "EGW00123")):
                self.token_manager.get_access_token(force_refresh=True)
                return self._request_response(
                    path=path,
                    tr_id=tr_id,
                    query_params=query_params,
                    extra_headers=extra_headers,
                    allow_retry=False,
                    allow_business_error=allow_business_error,
                )
            raise KisApiError(f"KIS HTTP error {exc.code}: {body}") from exc
        except URLError as exc:
            raise KisApiError(f"KIS network error: {exc}") from exc

        rt_cd = str(payload.get("rt_cd", ""))
        if rt_cd and rt_cd != "0" and not allow_business_error:
            raise KisApiError(f"KIS REST quote error: {_business_error_detail(payload)}")
        self._last_response_headers = response_headers
        return payload, response_headers

    def _post_response(
        self,
        path: str,
        tr_id: str,
        body: dict[str, str],
        *,
        include_hashkey: bool = False,
        allow_retry: bool = True,
    ) -> tuple[dict, dict[str, str]]:
        self._last_response_headers = {}
        token = self.token_manager.get_access_token()
        headers = {
            "authorization": token.authorization_header,
            "appkey": self.profile.app_key,
            "appsecret": self.profile.app_secret,
            "tr_id": tr_id,
            "custtype": self.profile.customer_type,
            "content-type": "application/json; charset=utf-8",
        }
        if include_hashkey:
            headers["hashkey"] = self.token_manager.issue_hashkey(body)
        request = Request(
            url=f"{self.profile.rest_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
                response_headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        except HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="ignore")
            if allow_retry and any(code in body_text for code in ("EGW00121", "EGW00123")):
                self.token_manager.get_access_token(force_refresh=True)
                return self._post_response(
                    path=path,
                    tr_id=tr_id,
                    body=body,
                    include_hashkey=include_hashkey,
                    allow_retry=False,
                )
            raise KisApiError(f"KIS HTTP error {exc.code}: {body_text}") from exc
        except URLError as exc:
            raise KisApiError(f"KIS network error: {exc}") from exc

        rt_cd = str(payload.get("rt_cd", ""))
        if rt_cd and rt_cd != "0":
            raise KisApiError(f"KIS REST quote error: {_business_error_detail(payload)}")
        self._last_response_headers = response_headers
        return payload, response_headers

    def _request(self, path: str, tr_id: str, query_params: dict[str, str], *, extra_headers: dict[str, str] | None = None) -> dict:
        payload, _ = self._request_response(path=path, tr_id=tr_id, query_params=query_params, extra_headers=extra_headers)
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

    def get_intraday_minute_chart(
        self,
        symbol: str,
        *,
        input_hour: str = "153000",
        market_code: str = "J",
        include_past_data: bool = True,
    ) -> list[KisIntradayMinuteRecord]:
        payload = self._request(
            path=INTRADAY_MINUTE_PATH,
            tr_id=INTRADAY_MINUTE_TR_ID,
            query_params={
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": market_code,
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_HOUR_1": input_hour,
                "FID_PW_DATA_INCU_YN": "Y" if include_past_data else "N",
            },
        )
        output_rows = list(payload.get("output2", []) or [])
        records: list[KisIntradayMinuteRecord] = []
        for row in output_rows:
            trade_date = _first_present(row, ("stck_bsop_date", "bsop_date"))
            trade_time = _first_present(row, ("stck_cntg_hour", "cntg_hour"))
            if not trade_date or not trade_time:
                continue
            records.append(
                KisIntradayMinuteRecord(
                    symbol=symbol,
                    market_code=market_code,
                    trade_date=trade_date,
                    trade_time=trade_time,
                    open_price=_first_float(row, ("stck_oprc", "oprc")),
                    high_price=_first_float(row, ("stck_hgpr", "hgpr")),
                    low_price=_first_float(row, ("stck_lwpr", "lwpr")),
                    close_price=_first_float(row, ("stck_prpr", "prpr")),
                    volume=_first_int(row, ("cntg_vol", "acml_vol", "vol")),
                    raw_output=dict(row),
                )
            )
        return records

    def get_account_balance(self, *, inqr_dvsn: str = "02", max_pages: int = 10) -> KisAccountBalanceSnapshot:
        if not self.profile.is_configured:
            raise KisApiError("KIS account number and product code are required before requesting account balance.")

        positions_payload: list[dict] = []
        summary_payload: list[dict] = []
        ctx_area_fk100 = ""
        ctx_area_nk100 = ""
        tr_cont = ""
        tr_id = ACCOUNT_BALANCE_TR_ID_LIVE if self.profile.mode == "live" else ACCOUNT_BALANCE_TR_ID_PAPER

        for _ in range(max_pages):
            payload, response_headers = self._request_response(
                path=ACCOUNT_BALANCE_PATH,
                tr_id=tr_id,
                query_params={
                    "CANO": self.profile.account_no,
                    "ACNT_PRDT_CD": self.profile.product_code,
                    "AFHR_FLPR_YN": "N",
                    "OFL_YN": "",
                    "INQR_DVSN": inqr_dvsn,
                    "UNPR_DVSN": "01",
                    "FUND_STTL_ICLD_YN": "N",
                    "FNCG_AMT_AUTO_RDPT_YN": "N",
                    "PRCS_DVSN": "00",
                    "CTX_AREA_FK100": ctx_area_fk100,
                    "CTX_AREA_NK100": ctx_area_nk100,
                },
                extra_headers={"tr_cont": tr_cont} if tr_cont else None,
            )
            positions_payload.extend(list(payload.get("output1", []) or []))
            summary_payload.extend(list(payload.get("output2", []) or []))
            ctx_area_fk100 = _as_text(payload, "ctx_area_fk100")
            ctx_area_nk100 = _as_text(payload, "ctx_area_nk100")
            next_tr_cont = response_headers.get("tr_cont", "").upper()
            if next_tr_cont in {"M", "F"} and (ctx_area_fk100 or ctx_area_nk100):
                tr_cont = "N"
                continue
            break

        summary = summary_payload[0] if summary_payload else {}
        positions = [
            KisBalancePosition(
                symbol=_as_text(row, "pdno"),
                name=_as_text(row, "prdt_name"),
                holding_qty=_as_int(row, "hldg_qty"),
                orderable_qty=_as_int(row, "ord_psbl_qty"),
                average_buy_price=_as_float(row, "pchs_avg_pric"),
                buy_amount=_as_int(row, "pchs_amt"),
                current_price=_as_int(row, "prpr"),
                evaluation_amount=_as_int(row, "evlu_amt"),
                evaluation_profit_loss_amount=_as_int(row, "evlu_pfls_amt"),
                evaluation_profit_loss_pct=_as_float(row, "evlu_pfls_rt"),
            )
            for row in positions_payload
            if _as_text(row, "pdno")
        ]

        return KisAccountBalanceSnapshot(
            mode=self.profile.mode,
            account_no_masked=_mask_account(self.profile.account_no),
            product_code=self.profile.product_code,
            positions=positions,
            cash_balance=_as_int(summary, "dnca_tot_amt"),
            stock_evaluation_amount=_as_int(summary, "scts_evlu_amt") or _as_int(summary, "evlu_amt_smtl_amt"),
            total_evaluation_amount=_as_int(summary, "tot_evlu_amt") or _as_int(summary, "evlu_amt_smtl_amt"),
            total_purchase_amount=_as_int(summary, "pchs_amt_smtl_amt"),
            total_profit_loss_amount=_as_int(summary, "evlu_pfls_smtl_amt"),
            total_asset_amount=_as_int(summary, "nass_amt") or _as_int(summary, "tot_evlu_amt"),
            summary_row_count=len(summary_payload),
            position_row_count=len(positions),
        )

    def get_orderability(
        self,
        *,
        symbol: str,
        order_price: float,
        order_type: str = "01",
        include_cma_evaluation: bool = False,
        include_overseas: bool = False,
    ) -> KisOrderabilitySnapshot:
        """Read domestic-stock buy orderability without submitting an order."""

        if not self.profile.is_configured:
            raise KisApiError(
                "KIS account number and product code are required before requesting orderability."
            )
        if not symbol:
            raise KisApiError("Orderability symbol is required.")
        if order_price <= 0:
            raise KisApiError("Orderability price must be positive.")
        if not order_type:
            raise KisApiError("Orderability order type is required.")

        tr_id = (
            ORDERABILITY_TR_ID_LIVE
            if self.profile.mode == "live"
            else ORDERABILITY_TR_ID_PAPER
        )
        payload, _ = self._request_response(
            path=ORDERABILITY_PATH,
            tr_id=tr_id,
            query_params={
                "CANO": self.profile.account_no,
                "ACNT_PRDT_CD": self.profile.product_code,
                "PDNO": symbol,
                "ORD_UNPR": str(int(round(order_price))),
                "ORD_DVSN": order_type,
                "CMA_EVLU_AMT_ICLD_YN": "Y" if include_cma_evaluation else "N",
                "OVRS_ICLD_YN": "Y" if include_overseas else "N",
            },
            allow_retry=False,
            allow_business_error=True,
        )
        output = payload.get("output", {}) or {}
        return KisOrderabilitySnapshot(
            mode=self.profile.mode,
            symbol=symbol,
            order_price=float(order_price),
            order_type=order_type,
            rt_cd=_as_text(payload, "rt_cd"),
            message_code=_as_text(payload, "msg_cd"),
            message=_as_text(payload, "msg1"),
            orderable_cash=_as_int(output, "ord_psbl_cash"),
            non_receivable_buy_amount=_as_int(output, "nrcvb_buy_amt"),
            non_receivable_buy_qty=_as_int(output, "nrcvb_buy_qty"),
            max_buy_amount=_as_int(output, "max_buy_amt"),
            max_buy_qty=_as_int(output, "max_buy_qty"),
        )

    def submit_cash_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: int,
        limit_price: float,
        order_type: str = "00",
        exchange_code: str = "KRX",
        sell_type: str = "",
        condition_price: str = "",
        instrument_type: str = KRX_INSTRUMENT_COMMON_STOCK,
    ) -> KisCashOrderResult:
        if not self.profile.is_configured:
            raise KisApiError("KIS account number and product code are required before submitting an order.")
        normalized_side = side.strip().lower()
        if normalized_side not in {"buy", "sell"}:
            raise KisApiError("Order side must be either 'buy' or 'sell'.")
        if qty <= 0:
            raise KisApiError("Order quantity must be positive.")
        if limit_price < 0:
            raise KisApiError("Order limit price cannot be negative.")

        normalized_limit_price = (
            normalize_krx_limit_price(
                limit_price,
                side=normalized_side,
                instrument_type=instrument_type,
            )
            if order_type == "00"
            else int(round(limit_price))
        )

        tr_id = (
            ORDER_CASH_TR_ID_BUY_LIVE
            if self.profile.mode == "live" and normalized_side == "buy"
            else ORDER_CASH_TR_ID_SELL_LIVE
            if self.profile.mode == "live"
            else ORDER_CASH_TR_ID_BUY_PAPER
            if normalized_side == "buy"
            else ORDER_CASH_TR_ID_SELL_PAPER
        )

        payload, _ = self._post_response(
            path=ORDER_CASH_PATH,
            tr_id=tr_id,
            body={
                "CANO": self.profile.account_no,
                "ACNT_PRDT_CD": self.profile.product_code,
                "PDNO": symbol,
                "ORD_DVSN": order_type,
                "ORD_QTY": str(int(qty)),
                "ORD_UNPR": str(normalized_limit_price),
                "EXCG_ID_DVSN_CD": exchange_code,
                "SLL_TYPE": sell_type,
                "CNDT_PRIC": condition_price,
            },
            include_hashkey=True,
        )
        output = payload.get("output", {}) or {}
        return KisCashOrderResult(
            mode=self.profile.mode,
            side=normalized_side,
            symbol=symbol,
            qty=int(qty),
            order_type=order_type,
            limit_price=float(normalized_limit_price),
            broker_order_no=_as_text(output, "ODNO"),
            broker_branch_no=_as_text(output, "KRX_FWDG_ORD_ORGNO"),
            order_time=_as_text(output, "ORD_TMD"),
            message_code=_as_text(payload, "msg_cd"),
            message=_as_text(payload, "msg1"),
            raw_output=dict(output),
        )

    def cancel_order(
        self,
        *,
        broker_branch_no: str,
        broker_order_no: str,
        order_qty: int,
        qty_all_order: bool = True,
        order_type: str = "00",
        cancel_code: str = "02",
        order_price: float = 0.0,
    ) -> KisCashOrderResult:
        if not self.profile.is_configured:
            raise KisApiError("KIS account number and product code are required before cancelling an order.")
        if not broker_branch_no or not broker_order_no:
            raise KisApiError("Broker branch/order number are required before cancelling an order.")
        if order_qty <= 0:
            raise KisApiError("Cancellation quantity must be positive.")

        tr_id = ORDER_RVSECNCL_TR_ID_LIVE if self.profile.mode == "live" else ORDER_RVSECNCL_TR_ID_PAPER
        payload, _ = self._post_response(
            path=ORDER_RVSECNCL_PATH,
            tr_id=tr_id,
            body={
                "CANO": self.profile.account_no,
                "ACNT_PRDT_CD": self.profile.product_code,
                "KRX_FWDG_ORD_ORGNO": broker_branch_no,
                "ORGN_ODNO": broker_order_no,
                "ORD_DVSN": order_type,
                "RVSE_CNCL_DVSN_CD": cancel_code,
                "ORD_QTY": str(int(order_qty)),
                "ORD_UNPR": str(int(round(order_price))),
                "QTY_ALL_ORD_YN": "Y" if qty_all_order else "N",
            },
            include_hashkey=True,
        )
        output = payload.get("output", {}) or {}
        return KisCashOrderResult(
            mode=self.profile.mode,
            side="cancel",
            symbol="",
            qty=int(order_qty),
            order_type=order_type,
            limit_price=float(order_price),
            broker_order_no=_as_text(output, "ODNO"),
            broker_branch_no=_as_text(output, "KRX_FWDG_ORD_ORGNO"),
            order_time=_as_text(output, "ORD_TMD"),
            message_code=_as_text(payload, "msg_cd"),
            message=_as_text(payload, "msg1"),
            raw_output=dict(output),
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
        if not self.profile.is_configured:
            raise KisApiError("KIS account number and product code are required before requesting order fills.")

        max_pages = max(int(max_pages), 1)
        ctx_area_fk100 = ""
        ctx_area_nk100 = ""
        tr_cont = ""
        tr_id = ORDER_DAILY_CCLD_TR_ID_LIVE if self.profile.mode == "live" else ORDER_DAILY_CCLD_TR_ID_PAPER
        records: list[KisDailyOrderFillRecord] = []
        pages_fetched = 0
        pagination_complete = False
        page_limit_reached = False
        self._last_daily_order_fill_query = {
            "start_date": start_date,
            "end_date": end_date,
            "max_pages": max_pages,
            "pages_fetched": 0,
            "records_returned": 0,
            "pagination_complete": False,
            "page_limit_reached": False,
        }

        for page_index in range(max_pages):
            payload, response_headers = self._request_response(
                path=ORDER_DAILY_CCLD_PATH,
                tr_id=tr_id,
                query_params={
                    "CANO": self.profile.account_no,
                    "ACNT_PRDT_CD": self.profile.product_code,
                    "INQR_STRT_DT": start_date,
                    "INQR_END_DT": end_date,
                    "SLL_BUY_DVSN_CD": side_filter,
                    "INQR_DVSN": "00",
                    "PDNO": symbol,
                    "CCLD_DVSN": filled_filter,
                    "ORD_GNO_BRNO": "",
                    "ODNO": order_no,
                    "INQR_DVSN_3": order_filter_3,
                    "INQR_DVSN_1": order_filter_1,
                    "CTX_AREA_FK100": ctx_area_fk100,
                    "CTX_AREA_NK100": ctx_area_nk100,
                    "EXCG_ID_DVSN_CD": exchange_code,
                },
                extra_headers={"tr_cont": tr_cont} if tr_cont else None,
            )
            pages_fetched += 1
            for row in list(payload.get("output1", []) or []):
                records.append(
                    KisDailyOrderFillRecord(
                        mode=self.profile.mode,
                        order_date=_as_text(row, "ord_dt"),
                        broker_branch_no=_first_present(row, ("ord_gno_brno", "ord_orgno")),
                        broker_order_no=_as_text(row, "odno"),
                        original_order_no=_as_text(row, "orgn_odno"),
                        symbol=_as_text(row, "pdno"),
                        symbol_name=_as_text(row, "prdt_name"),
                        side=_as_text(row, "sll_buy_dvsn_cd"),
                        side_name=_as_text(row, "sll_buy_dvsn_cd_name"),
                        order_type_code=_as_text(row, "ord_dvsn_cd"),
                        order_type_name=_first_present(row, ("ord_dvsn_name", "ord_dvsn_cd_name")),
                        order_time=_as_text(row, "ord_tmd"),
                        order_qty=_as_int(row, "ord_qty"),
                        order_price=_as_float(row, "ord_unpr"),
                        filled_qty=_first_int(row, ("tot_ccld_qty", "ccld_qty")),
                        remaining_qty=_first_int(row, ("rmn_qty", "ord_remn_qty")),
                        avg_fill_price=_first_float(row, ("avg_prvs", "avg_ccld_unpr")),
                        filled_amount=_first_float(row, ("tot_ccld_amt",)),
                        cancel_confirm_qty=_first_int(row, ("cncl_cfrm_qty",)),
                        reject_qty=_first_int(row, ("rjct_qty",)),
                        cancel_yn=_as_bool(row, "cncl_yn"),
                        exchange_id=_first_present(row, ("excg_id_dvsn_cd", "excg_dvsn_cd")),
                        raw_output=dict(row),
                    )
                )
            ctx_area_fk100 = _as_text(payload, "ctx_area_fk100")
            ctx_area_nk100 = _as_text(payload, "ctx_area_nk100")
            next_tr_cont = response_headers.get("tr_cont", "").upper()
            if next_tr_cont in {"M", "F"} and (ctx_area_fk100 or ctx_area_nk100):
                if page_index + 1 >= max_pages:
                    page_limit_reached = True
                    break
                tr_cont = "N"
                continue
            pagination_complete = True
            break

        self._last_daily_order_fill_query = {
            "start_date": start_date,
            "end_date": end_date,
            "max_pages": max_pages,
            "pages_fetched": pages_fetched,
            "records_returned": len(records),
            "pagination_complete": pagination_complete,
            "page_limit_reached": page_limit_reached,
        }
        return records
