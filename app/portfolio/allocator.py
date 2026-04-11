"""Portfolio sizing helpers."""

from __future__ import annotations

from app.storage.contracts import TargetPosition, TradeSignal


class PositionAllocator:
    def __init__(self, portfolio_version: str, max_position_pct: float, lot_size: int = 1) -> None:
        self.portfolio_version = portfolio_version
        self.max_position_pct = max_position_pct
        self.lot_size = lot_size

    def allocate(
        self,
        signal: TradeSignal,
        last_price: float,
        cash_balance: float,
        target_id: str,
    ) -> TargetPosition:
        target_notional = cash_balance * self.max_position_pct if signal.allowed else 0.0
        raw_qty = int(target_notional // max(last_price, 1))
        target_qty = (raw_qty // self.lot_size) * self.lot_size
        return TargetPosition(
            target_id=target_id,
            symbol=signal.symbol,
            event_time=signal.event_time,
            side=signal.side,
            target_qty=max(target_qty, 0),
            target_notional=target_qty * last_price,
            portfolio_version=self.portfolio_version,
        )
