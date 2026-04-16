"""Helpers for mirroring local paper orders into the broker paper account."""

from __future__ import annotations

from datetime import datetime

from app.brokers.kis_auth import KisTokenManager, get_kis_profile
from app.brokers.kis_quote_rest import KisAccountBalanceSnapshot, KisCashOrderResult, KisRestQuoteClient
from app.config.settings import AppSettings
from app.storage.contracts import BrokerOrderSubmission, PaperOrder


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
