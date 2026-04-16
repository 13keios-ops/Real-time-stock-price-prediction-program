"""KIS REST quote client for domestic stock market data, account views, and paper/live order submission."""

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
ACCOUNT_BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
ACCOUNT_BALANCE_TR_ID_LIVE = "TTTC8434R"
ACCOUNT_BALANCE_TR_ID_PAPER = "VTTC8434R"
ORDER_CASH_PATH = "/uapi/domestic-stock/v1/trading/order-cash"
ORDER_CASH_TR_ID_BUY_LIVE = "TTTC0012U"
ORDER_CASH_TR_ID_SELL_LIVE = "TTTC0011U"
ORDER_CASH_TR_ID_BUY_PAPER = "VTTC0012U"
ORDER_CASH_TR_ID_SELL_PAPER = "VTTC0011U"


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

    def _request_response(
        self,
        path: str,
        tr_id: str,
        query_params: dict[str, str],
        *,
        extra_headers: dict[str, str] | None = None,
        allow_retry: bool = True,
    ) -> tuple[dict, dict[str, str]]:
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
                )
            raise KisApiError(f"KIS HTTP error {exc.code}: {body}") from exc
        except URLError as exc:
            raise KisApiError(f"KIS network error: {exc}") from exc

        rt_cd = str(payload.get("rt_cd", ""))
        if rt_cd and rt_cd != "0":
            message = payload.get("msg1") or payload.get("msg_cd") or payload
            raise KisApiError(f"KIS REST quote error: {message}")
        return payload, response_headers

    def _post_response(
        self,
        path: str,
        tr_id: str,
        body: dict[str, str],
        *,
        allow_retry: bool = True,
    ) -> tuple[dict, dict[str, str]]:
        token = self.token_manager.get_access_token()
        headers = {
            "authorization": token.authorization_header,
            "appkey": self.profile.app_key,
            "appsecret": self.profile.app_secret,
            "tr_id": tr_id,
            "custtype": self.profile.customer_type,
            "content-type": "application/json; charset=utf-8",
        }
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
                return self._post_response(path=path, tr_id=tr_id, body=body, allow_retry=False)
            raise KisApiError(f"KIS HTTP error {exc.code}: {body_text}") from exc
        except URLError as exc:
            raise KisApiError(f"KIS network error: {exc}") from exc

        rt_cd = str(payload.get("rt_cd", ""))
        if rt_cd and rt_cd != "0":
            message = payload.get("msg1") or payload.get("msg_cd") or payload
            raise KisApiError(f"KIS REST quote error: {message}")
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
                "ORD_UNPR": str(int(round(limit_price))),
                "EXCG_ID_DVSN_CD": exchange_code,
                "SLL_TYPE": sell_type,
                "CNDT_PRIC": condition_price,
            },
        )
        output = payload.get("output", {}) or {}
        return KisCashOrderResult(
            mode=self.profile.mode,
            side=normalized_side,
            symbol=symbol,
            qty=int(qty),
            order_type=order_type,
            limit_price=float(limit_price),
            broker_order_no=_as_text(output, "ODNO"),
            broker_branch_no=_as_text(output, "KRX_FWDG_ORD_ORGNO"),
            order_time=_as_text(output, "ORD_TMD"),
            message_code=_as_text(payload, "msg_cd"),
            message=_as_text(payload, "msg1"),
            raw_output=dict(output),
        )
