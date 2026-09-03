"""Helpers for mirroring local paper orders into the broker paper account."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Any

from app.brokers.kis_auth import KisApiError, KisTokenManager, get_kis_profile
from app.brokers.kis_quote_rest import (
    KRX_INSTRUMENT_COMMON_STOCK,
    ORDER_CASH_PATH,
    ORDER_CASH_TR_ID_BUY_PAPER,
    ORDER_CASH_TR_ID_SELL_PAPER,
    KisAccountBalanceSnapshot,
    KisCashOrderResult,
    KisDailyOrderFillRecord,
    KisRestQuoteClient,
    normalize_krx_limit_price,
)
from app.config.settings import AppSettings
from app.storage.contracts import BrokerOrderSubmission, PaperOrder
from app.utils.time import now_local


LOGGER = logging.getLogger(__name__)
ORDER_FILL_RATE_LIMIT_RETRY_DELAYS_SECONDS: tuple[float, ...] = ()
BROKER_ACCOUNT_HARD_REJECTION_COOLDOWN_SECONDS = 30 * 60
BROKER_ACCOUNT_NOT_ORDERABLE_MESSAGE = (
    "\ubaa8\uc758\ud22c\uc790 \uc8fc\ubb38\uc774 "
    "\ubd88\uac00\ud55c \uacc4\uc88c"
)
BROKER_FAILURE_CATEGORIES = frozenset(
    {
        "broker_account_not_orderable",
        "broker_rate_limited",
        "broker_auth_error",
        "broker_invalid_request",
        "broker_order_rejected",
        "broker_network_error",
        "broker_unknown_error",
    }
)
_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)\b(appkey|app_key|appsecret|app_secret|authorization|token|cano|"
    r"account(?:_no)?|acnt_prdt_cd)\b[\"']?\s*[:=]\s*[\"']?[^,;\s}\"']+"
)
_ACCOUNT_IDENTIFIER_PATTERN = re.compile(r"(?<!\d)\d{8,10}(?!\d)")
_KIS_CODE_PATTERN = re.compile(r"\b(?:EGW|APBK|OPSQ|IGW)[A-Z0-9]*\d+[A-Z0-9]*\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class BrokerPaperFailure:
    category: str
    message_code: str
    message: str
    network_attempted: bool
    reason_code: str | None = None
    circuit_opened: bool = False
    retry_after_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.category not in BROKER_FAILURE_CATEGORIES:
            raise ValueError(f"Unsupported broker paper failure category: {self.category}")

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "message_code": self.message_code,
            "message": self.message,
            "network_attempted": self.network_attempted,
            "reason_code": self.reason_code,
            "circuit_opened": self.circuit_opened,
            "retry_after_seconds": self.retry_after_seconds,
        }


class BrokerPaperSubmissionError(RuntimeError):
    def __init__(
        self,
        failure: BrokerPaperFailure,
        *,
        attempt_id: str,
        request_evidence: dict[str, object],
    ) -> None:
        self.failure = failure
        self.attempt_id = attempt_id
        self.request_evidence = request_evidence
        super().__init__(f"{failure.category}: {failure.message}")


def sanitize_broker_error_text(value: object) -> str:
    text = str(value or "").strip()
    text = _SENSITIVE_VALUE_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _ACCOUNT_IDENTIFIER_PATTERN.sub("[REDACTED_ID]", text)
    return text[:500]


def _extract_kis_error_fields(exc: BaseException) -> tuple[str, str]:
    raw_text = str(exc or "")
    message_code = ""
    message = raw_text
    json_start = raw_text.find("{")
    if json_start >= 0:
        try:
            payload = json.loads(raw_text[json_start:])
        except (json.JSONDecodeError, TypeError):
            payload = None
        if isinstance(payload, dict):
            message_code = str(payload.get("msg_cd") or "").strip()
            message = str(payload.get("msg1") or payload.get("msg_cd") or raw_text).strip()
    if not message_code:
        code_match = _KIS_CODE_PATTERN.search(raw_text)
        if code_match is not None:
            message_code = code_match.group(0).upper()
    return sanitize_broker_error_text(message_code), sanitize_broker_error_text(message)


def classify_broker_paper_failure(
    exc: BaseException,
    *,
    network_attempted: bool,
    circuit_opened: bool = False,
    retry_after_seconds: int | None = None,
) -> BrokerPaperFailure:
    message_code, message = _extract_kis_error_fields(exc)
    lowered = message.lower()
    code = message_code.upper()
    reason_code: str | None = None
    if BROKER_ACCOUNT_NOT_ORDERABLE_MESSAGE in message:
        category = "broker_account_not_orderable"
    elif "\ud638\uac00\ub2e8\uc704 \uc624\ub958" in message:
        category = "broker_invalid_request"
        reason_code = "invalid_price_tick"
    elif (
        code == "EGW00201"
        or "\ucd08\ub2f9 \uac70\ub798\uac74\uc218\ub97c \ucd08\uacfc" in message
        or any(marker in lowered for marker in ("rate limit", "too many requests"))
    ):
        category = "broker_rate_limited"
    elif code in {"EGW00121", "EGW00123"} or any(
        marker in lowered for marker in ("http error 401", "http error 403", "authorization", "authentication", "token expired")
    ):
        category = "broker_auth_error"
    elif any(
        marker in lowered
        for marker in (
            "required before submitting",
            "must be either",
            "must be positive",
            "cannot be negative",
            "http error 400",
            "http error 422",
            "invalid request",
        )
    ):
        category = "broker_invalid_request"
    elif any(marker in lowered for marker in ("network error", "timed out", "timeout", "connection reset", "temporary failure")):
        category = "broker_network_error"
    elif (
        "\uac70\uc808" in message
        or ("\uc8fc\ubb38" in message and "\ubd88\uac00" in message)
        or ("order" in lowered and any(marker in lowered for marker in ("reject", "not allowed", "not orderable")))
    ):
        category = "broker_order_rejected"
    else:
        category = "broker_unknown_error"
    return BrokerPaperFailure(
        category=category,
        message_code=message_code,
        message=message or exc.__class__.__name__,
        network_attempted=network_attempted,
        reason_code=reason_code,
        circuit_opened=circuit_opened,
        retry_after_seconds=retry_after_seconds,
    )


def is_kis_rate_limit_error(exc: KisApiError) -> bool:
    return classify_broker_paper_failure(exc, network_attempted=True).category == "broker_rate_limited"


class BrokerPaperMirror:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.profile = get_kis_profile(settings, "paper")
        self.client = KisRestQuoteClient(profile=self.profile, token_manager=KisTokenManager(self.profile))
        self._account_hard_rejection_until: float | None = None

    @property
    def enabled(self) -> bool:
        return (
            self.settings.trading_mode == "paper"
            and self.settings.strategy.enable_broker_paper_mirroring
            and self.profile.is_configured
        )

    def reset_account_hard_rejection_circuit(self) -> None:
        self._account_hard_rejection_until = None

    def _request_evidence(
        self,
        order: PaperOrder,
        *,
        normalized_limit_price: int,
    ) -> dict[str, object]:
        normalized_side = order.side.strip().lower()
        tr_id = ORDER_CASH_TR_ID_BUY_PAPER if normalized_side == "buy" else ORDER_CASH_TR_ID_SELL_PAPER
        return {
            "profile": {
                "mode": self.profile.mode,
                "configured": self.profile.is_configured,
                "account_present": bool(self.profile.account_no),
                "account_length": len(self.profile.account_no),
                "product_code_present": bool(self.profile.product_code),
                "product_code_length": len(self.profile.product_code),
                "product_code_is_domestic_stock_default": self.profile.product_code == "01",
            },
            "endpoint": ORDER_CASH_PATH,
            "tr_id": tr_id,
            "body": {
                "PDNO": order.symbol,
                "ORD_DVSN": "00",
                "ORD_QTY": str(int(order.qty)),
                "ORD_UNPR": str(normalized_limit_price),
                "EXCG_ID_DVSN_CD": "KRX",
                "SLL_TYPE": "",
                "CNDT_PRIC": "",
            },
        }

    def submit_local_order(
        self,
        order: PaperOrder,
        *,
        decision_id: str | None = None,
    ) -> BrokerOrderSubmission:
        attempt_id = f"broker-paper-attempt-{order.order_id}"
        normalized_limit_price = normalize_krx_limit_price(
            order.limit_price,
            side=order.side,
            instrument_type=KRX_INSTRUMENT_COMMON_STOCK,
        )
        request_evidence = self._request_evidence(
            order,
            normalized_limit_price=normalized_limit_price,
        )
        now = time.monotonic()
        if self._account_hard_rejection_until is not None:
            if now < self._account_hard_rejection_until:
                retry_after_seconds = max(int(self._account_hard_rejection_until - now), 1)
                failure = BrokerPaperFailure(
                    category="broker_account_not_orderable",
                    message_code="",
                    message="broker paper account circuit is open after a hard account rejection",
                    network_attempted=False,
                    circuit_opened=True,
                    retry_after_seconds=retry_after_seconds,
                )
                raise BrokerPaperSubmissionError(
                    failure,
                    attempt_id=attempt_id,
                    request_evidence=request_evidence,
                )
            self._account_hard_rejection_until = None

        try:
            result = self.client.submit_cash_order(
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                limit_price=normalized_limit_price,
                order_type="00",
                instrument_type=KRX_INSTRUMENT_COMMON_STOCK,
            )
        except Exception as exc:
            failure = classify_broker_paper_failure(exc, network_attempted=True)
            if failure.category == "broker_account_not_orderable":
                self._account_hard_rejection_until = now + BROKER_ACCOUNT_HARD_REJECTION_COOLDOWN_SECONDS
                failure = BrokerPaperFailure(
                    category=failure.category,
                    message_code=failure.message_code,
                    message=failure.message,
                    network_attempted=True,
                    reason_code=failure.reason_code,
                    circuit_opened=True,
                    retry_after_seconds=BROKER_ACCOUNT_HARD_REJECTION_COOLDOWN_SECONDS,
                )
            raise BrokerPaperSubmissionError(
                failure,
                attempt_id=attempt_id,
                request_evidence=request_evidence,
            ) from exc

        self.reset_account_hard_rejection_circuit()
        return self._to_submission(
            order=order,
            result=result,
            attempt_id=attempt_id,
            decision_id=decision_id,
            request_evidence=request_evidence,
        )

    def fetch_balance_snapshot(self) -> KisAccountBalanceSnapshot:
        return self.client.get_account_balance()

    def fetch_recent_order_fills(
        self,
        *,
        lookback_days: int = 3,
        retry_delays_seconds: tuple[float, ...] | None = None,
    ) -> list[KisDailyOrderFillRecord]:
        end_date = now_local(self.settings.timezone).date()
        start_date = end_date - timedelta(days=max(lookback_days - 1, 0))
        start_date_text = start_date.strftime("%Y%m%d")
        end_date_text = end_date.strftime("%Y%m%d")
        retry_delays = (
            ORDER_FILL_RATE_LIMIT_RETRY_DELAYS_SECONDS
            if retry_delays_seconds is None
            else tuple(float(delay) for delay in retry_delays_seconds)
        )
        last_error: KisApiError | None = None
        for attempt in range(len(retry_delays) + 1):
            try:
                return self.client.get_daily_order_fills(
                    start_date=start_date_text,
                    end_date=end_date_text,
                )
            except KisApiError as exc:
                last_error = exc
                if not is_kis_rate_limit_error(exc) or attempt >= len(retry_delays):
                    raise
                delay_seconds = retry_delays[attempt]
                LOGGER.warning(
                    "KIS broker paper order-fill query rate-limited on attempt %s/%s. Retrying after %.1fs.",
                    attempt + 1,
                    len(retry_delays) + 1,
                    delay_seconds,
                )
                time.sleep(delay_seconds)
        if last_error is not None:
            raise last_error
        raise KisApiError("KIS broker paper order-fill query did not return a result.")

    def cancel_submitted_order(
        self,
        *,
        broker_branch_no: str,
        broker_order_no: str,
        order_qty: int,
    ) -> KisCashOrderResult:
        return self.client.cancel_order(
            broker_branch_no=broker_branch_no,
            broker_order_no=broker_order_no,
            order_qty=order_qty,
        )

    @staticmethod
    def _to_submission(
        *,
        order: PaperOrder,
        result: KisCashOrderResult,
        attempt_id: str,
        decision_id: str | None,
        request_evidence: dict[str, object],
    ) -> BrokerOrderSubmission:
        detail: dict[str, Any] = {
            "message_code": result.message_code,
            "message": result.message,
            "raw_output": result.raw_output,
            "attempt_id": attempt_id,
            "decision_id": decision_id,
            "prediction_id": order.prediction_id,
            "signal_id": order.signal_id,
            "target_id": order.target_id,
            "request": request_evidence,
        }
        return BrokerOrderSubmission(
            submission_id=f"broker-paper-{order.order_id}",
            local_order_id=order.order_id,
            broker_mode=result.mode,
            symbol=order.symbol,
            event_time=order.event_time,
            side=order.side,
            qty=order.qty,
            limit_price=result.limit_price,
            order_type=result.order_type,
            status="submitted",
            broker_order_no=result.broker_order_no,
            broker_branch_no=result.broker_branch_no,
            detail=detail,
        )


def broker_snapshot_to_local_rows(snapshot: KisAccountBalanceSnapshot, *, event_time: datetime) -> tuple[list[dict], dict]:
    positions: list[dict] = []
    for position in snapshot.positions:
        if int(position.holding_qty) <= 0:
            continue
        positions.append(
            {
                "symbol": position.symbol,
                "opened_at": event_time,
                "updated_at": event_time,
                "qty": int(position.holding_qty),
                "avg_price": float(position.average_buy_price),
                "last_price": float(position.current_price),
                "market_value": float(position.evaluation_amount),
                "cost_basis": float(position.buy_amount),
                "realized_pnl": 0.0,
                "unrealized_pnl": float(position.evaluation_profit_loss_amount),
            }
        )
    snapshot_row = {
        "cash_balance": float(snapshot.cash_balance),
        "gross_market_value": float(snapshot.stock_evaluation_amount),
        "net_liquidation_value": float(snapshot.total_evaluation_amount),
        "open_positions": len(positions),
        "realized_pnl": 0.0,
        "unrealized_pnl": float(snapshot.total_profit_loss_amount),
    }
    return positions, snapshot_row
