"""Paper trading execution primitives."""

from __future__ import annotations

from app.storage.contracts import Fill, OrderEvent, PaperOrder, TargetPosition, TradeSignal


class PaperTradingEngine:
    def __init__(self, commission_rate: float = 0.00015, tax_rate: float = 0.00018, slippage_bps: float = 3.0) -> None:
        self.commission_rate = commission_rate
        self.tax_rate = tax_rate
        self.slippage_bps = slippage_bps

    def create_order(self, target: TargetPosition, signal: TradeSignal, order_id: str) -> PaperOrder:
        if target.target_qty <= 0:
            raise ValueError("Target quantity must be positive for an order.")
        return PaperOrder(
            order_id=order_id,
            symbol=target.symbol,
            event_time=target.event_time,
            side=signal.side,
            qty=target.target_qty,
            limit_price=target.target_notional / target.target_qty,
            status="created",
        )

    def acknowledge(self, order: PaperOrder, order_event_id: str) -> OrderEvent:
        order.status = "acknowledged"
        return OrderEvent(
            order_event_id=order_event_id,
            order_id=order.order_id,
            event_time=order.event_time,
            event_type="acknowledged",
            detail=f"qty={order.qty}",
        )

    def fill(self, order: PaperOrder, fill_price: float, order_event_id: str, fill_id: str) -> tuple[OrderEvent, Fill]:
        order.status = "filled"
        commission = fill_price * order.qty * self.commission_rate
        tax = fill_price * order.qty * self.tax_rate
        return (
            OrderEvent(
                order_event_id=order_event_id,
                order_id=order.order_id,
                event_time=order.event_time,
                event_type="filled",
                detail=f"fill_price={fill_price:.2f}",
            ),
            Fill(
                fill_id=fill_id,
                order_id=order.order_id,
                event_time=order.event_time,
                fill_price=fill_price,
                fill_qty=order.qty,
                commission=commission,
                tax=tax,
            ),
        )
