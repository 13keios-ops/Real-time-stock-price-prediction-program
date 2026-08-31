"""Sanitized read-only KIS domestic-stock orderability evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.brokers.kis_quote_rest import (
    ORDERABILITY_PATH,
    ORDERABILITY_TR_ID_PAPER,
)
from app.services.broker_paper import (
    BROKER_ACCOUNT_NOT_ORDERABLE_MESSAGE,
    sanitize_broker_error_text,
)
from app.services.kis_probe_errors import build_sanitized_kis_probe_error


ORDERABILITY_STATUSES = frozenset(
    {
        "orderability_ok",
        "orderability_zero",
        "account_not_orderable",
        "auth_error",
        "invalid_request",
        "rate_limited",
        "network_error",
        "unknown_error",
    }
)


def _request_shape(
    *,
    symbol: str,
    order_price: float | None,
    order_type: str,
    product_code_present: bool,
    product_code_length: int,
    product_code_is_domestic_stock_default: bool,
) -> dict[str, Any]:
    return {
        "environment": "paper/demo",
        "endpoint_category": "domestic_stock_buy_orderability_read_only",
        "endpoint": ORDERABILITY_PATH,
        "tr_id": ORDERABILITY_TR_ID_PAPER,
        "symbol": symbol or None,
        "ord_dvsn": order_type,
        "ord_unpr_present": order_price is not None and order_price > 0,
        "product_code_shape": {
            "present": bool(product_code_present),
            "length": int(product_code_length),
            "is_domestic_stock_default": bool(
                product_code_is_domestic_stock_default
            ),
        },
        "query_fields": [
            "CANO",
            "ACNT_PRDT_CD",
            "PDNO",
            "ORD_UNPR",
            "ORD_DVSN",
            "CMA_EVLU_AMT_ICLD_YN",
            "OVRS_ICLD_YN",
        ],
        "account_identifier_in_report": False,
    }


def build_orderability_dry_run(
    *,
    symbol: str,
    order_price: float | None,
    order_type: str = "01",
    product_code_present: bool = False,
    product_code_length: int = 0,
    product_code_is_domestic_stock_default: bool = False,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    observed_at = checked_at or datetime.now(timezone.utc)
    blockers = []
    if not symbol:
        blockers.append("symbol_unavailable")
    if order_price is None or order_price <= 0:
        blockers.append("recent_reference_price_unavailable")
    if not product_code_present:
        blockers.append("paper_product_code_unavailable")
    return {
        "schema_version": 1,
        "generated_at": observed_at.isoformat(),
        "status": "dry_run",
        "passed": False,
        "execution_started": False,
        "blocking_reasons": blockers,
        "request": _request_shape(
            symbol=symbol,
            order_price=order_price,
            order_type=order_type,
            product_code_present=product_code_present,
            product_code_length=product_code_length,
            product_code_is_domestic_stock_default=(
                product_code_is_domestic_stock_default
            ),
        ),
        "safety": {
            "network_calls": 0,
            "order_calls": 0,
            "cancel_calls": 0,
            "raw_response_in_report": False,
            "secrets_in_report": False,
        },
    }


def probe_kis_paper_orderability(
    readonly_client: Any,
    *,
    symbol: str,
    order_price: float,
    order_type: str = "01",
    product_code_present: bool = True,
    product_code_length: int = 2,
    product_code_is_domestic_stock_default: bool = True,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Issue exactly one read-only orderability request and sanitize the result."""

    observed_at = checked_at or datetime.now(timezone.utc)
    request = _request_shape(
        symbol=symbol,
        order_price=order_price,
        order_type=order_type,
        product_code_present=product_code_present,
        product_code_length=product_code_length,
        product_code_is_domestic_stock_default=(
            product_code_is_domestic_stock_default
        ),
    )
    try:
        snapshot = readonly_client.get_orderability(
            symbol=symbol,
            order_price=order_price,
            order_type=order_type,
            include_cma_evaluation=False,
            include_overseas=False,
        )
    except Exception as exc:  # pragma: no cover - transport details vary.
        sanitized = build_sanitized_kis_probe_error(exc)
        status = _classify_exception(sanitized)
        return _report(
            observed_at=observed_at,
            status=status,
            request=request,
            rt_cd=None,
            message_code=(
                (sanitized.get("kis_error_codes") or [None])[0]
            ),
            message=None,
            value_presence="unavailable",
            evidence_health="probe_failed",
            error=sanitized,
        )

    rt_cd = str(getattr(snapshot, "rt_cd", "") or "")
    message_code = sanitize_broker_error_text(
        getattr(snapshot, "message_code", "")
    )
    message = sanitize_broker_error_text(getattr(snapshot, "message", ""))
    if rt_cd and rt_cd != "0":
        status = _classify_business_error(message_code, message)
        value_presence = "unavailable"
        evidence_health = "valid_broker_response"
    else:
        values = (
            int(getattr(snapshot, "orderable_cash", 0) or 0),
            int(getattr(snapshot, "non_receivable_buy_amount", 0) or 0),
            int(getattr(snapshot, "non_receivable_buy_qty", 0) or 0),
            int(getattr(snapshot, "max_buy_amount", 0) or 0),
            int(getattr(snapshot, "max_buy_qty", 0) or 0),
        )
        positive = any(value > 0 for value in values)
        status = "orderability_ok" if positive else "orderability_zero"
        value_presence = "positive" if positive else "zero"
        evidence_health = "valid_readonly_response"
    return _report(
        observed_at=observed_at,
        status=status,
        request=request,
        rt_cd=rt_cd,
        message_code=message_code,
        message=message,
        value_presence=value_presence,
        evidence_health=evidence_health,
    )


def _report(
    *,
    observed_at: datetime,
    status: str,
    request: dict[str, Any],
    rt_cd: str | None,
    message_code: str | None,
    message: str | None,
    value_presence: str,
    evidence_health: str,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in ORDERABILITY_STATUSES:
        raise ValueError(f"unsupported orderability status: {status}")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": observed_at.isoformat(),
        "status": status,
        "passed": status == "orderability_ok",
        "execution_started": True,
        "evidence_health": evidence_health,
        "request": request,
        "response": {
            "transport_success": error is None,
            "api_success": status in {"orderability_ok", "orderability_zero"},
            "http_or_api_success": status in {"orderability_ok", "orderability_zero"},
            "rt_cd": rt_cd,
            "msg_cd": message_code or None,
            "msg1": message or None,
            "orderability_value_presence": value_presence,
        },
        "cash_order_failure_taxonomy": (
            "broker_account_not_orderable"
            if status == "account_not_orderable"
            else "not_reproduced_by_readonly_orderability"
            if status == "orderability_ok"
            else "orderability_zero"
            if status == "orderability_zero"
            else f"broker_{status}"
        ),
        "safety": {
            "network_calls": 1,
            "order_calls": 0,
            "cancel_calls": 0,
            "raw_response_in_report": False,
            "secrets_in_report": False,
        },
    }
    if error:
        payload["error"] = dict(error)
    return payload


def _classify_business_error(message_code: str, message: str) -> str:
    code = message_code.upper()
    lowered = message.lower()
    if BROKER_ACCOUNT_NOT_ORDERABLE_MESSAGE in message:
        return "account_not_orderable"
    if code == "EGW00201" or "초당 거래건수" in message or "rate limit" in lowered:
        return "rate_limited"
    if code in {"EGW00121", "EGW00123"} or any(
        marker in lowered for marker in ("authorization", "authentication", "token")
    ):
        return "auth_error"
    if any(marker in lowered for marker in ("invalid", "필수", "잘못", "유효하지")):
        return "invalid_request"
    return "unknown_error"


def _classify_exception(error: dict[str, Any]) -> str:
    category = str(error.get("error_category") or "")
    if category == "rate_limited":
        return "rate_limited"
    if category in {"token_invalid_or_expired", "missing_quote_credentials"}:
        return "auth_error"
    if category == "missing_account_credentials":
        return "invalid_request"
    if category in {"network_error", "http_error"}:
        return "network_error"
    return "unknown_error"
