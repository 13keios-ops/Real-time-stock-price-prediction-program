"""Helpers for mirroring local paper orders into the broker paper account."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from datetime import timedelta

from app.brokers.kis_auth import KisApiError, KisTokenManager, get_kis_profile
from app.brokers.kis_quote_rest import (
    KisAccountBalanceSnapshot,
    KisCashOrderResult,
    KisDailyOrderFillRecord,
    KisRestQuoteClient,
)
from app.config.settings import AppSettings
from app.storage.contracts import BrokerOrderSubmission, PaperOrder
from app.utils.time import now_local


LOGGER = logging.getLogger(__name__)
ORDER_FILL_RATE_LIMIT_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0)


def is_kis_rate_limit_error(exc: KisApiError) -> bool:
    message = str(exc).lower()
    return "egw00201" in message or "rate limit" in message or "too many" in message


class BrokerPaperMirror:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.profile = get_kis_profile(settings, "paper")
        self.client = KisRestQuoteClient(profile=self.profile, token_manager=KisTokenManager(self.profile))

    @property
    def enabled(self) -> bool:
        return (
            self.settings.trading_mode == "paper"
            and self.settings.strategy.enable_broker_paper_mirroring
            and self.profile.is_configured
        )

    def submit_local_order(self, order: PaperOrder) -> BrokerOrderSubmission:
        result = self.client.submit_cash_order(
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            limit_price=order.limit_price,
            order_type="00",
        )
        return self._to_submission(order=order, result=result)

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
    def _to_submission(order: PaperOrder, result: KisCashOrderResult) -> BrokerOrderSubmission:
        detail = {
            "message_code": result.message_code,
            "message": result.message,
            "raw_output": result.raw_output,
        }
        return BrokerOrderSubmission(
            submission_id=f"broker-paper-{order.order_id}",
            local_order_id=order.order_id,
            broker_mode=result.mode,
            symbol=order.symbol,
            event_time=order.event_time,
            side=order.side,
            qty=order.qty,
            limit_price=order.limit_price,
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
