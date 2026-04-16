"""Paper portfolio accounting for positions, cash, and equity snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.storage.contracts import Fill, PaperPosition, PortfolioSnapshot


@dataclass(slots=True)
class PositionState:
    symbol: str
    opened_at: datetime | None = None
    qty: int = 0
    avg_price: float = 0.0
    last_price: float = 0.0
    realized_pnl: float = 0.0

    @property
    def market_value(self) -> float:
        return self.qty * self.last_price

    @property
    def cost_basis(self) -> float:
        return self.qty * self.avg_price

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis


@dataclass(slots=True)
class PaperPortfolioBook:
    initial_cash: float
    max_open_positions: int
    cash_balance: float = field(init=False)
    positions: dict[str, PositionState] = field(default_factory=dict)
    realized_pnl_total: float = 0.0

    def __post_init__(self) -> None:
        self.cash_balance = self.initial_cash

    def restore_from_runtime(
        self,
        *,
        latest_snapshot: dict | None,
        position_rows: list[dict],
    ) -> None:
        if latest_snapshot:
            self.cash_balance = float(latest_snapshot.get("cash_balance", self.initial_cash) or self.initial_cash)
            self.realized_pnl_total = float(latest_snapshot.get("realized_pnl", 0.0) or 0.0)
        self.positions = {}
        for row in position_rows:
            qty = int(row.get("qty", 0) or 0)
            if qty <= 0:
                continue
            opened_at = row.get("opened_at")
            if isinstance(opened_at, str) and opened_at:
                opened_at = datetime.fromisoformat(opened_at)
            self.positions[str(row.get("symbol"))] = PositionState(
                symbol=str(row.get("symbol")),
                opened_at=opened_at,
                qty=qty,
                avg_price=float(row.get("avg_price", 0.0) or 0.0),
                last_price=float(row.get("last_price", 0.0) or 0.0),
                realized_pnl=float(row.get("realized_pnl", 0.0) or 0.0),
            )

    def open_position_count(self) -> int:
        return sum(1 for position in self.positions.values() if position.qty > 0)

    def can_open(self, symbol: str) -> tuple[bool, str]:
        existing = self.positions.get(symbol)
        if existing and existing.qty > 0:
            return False, "position_already_open"
        if self.open_position_count() >= self.max_open_positions:
            return False, "max_open_positions_reached"
        return True, "ok"

    def mark_price(self, symbol: str, price: float) -> None:
        state = self.positions.get(symbol)
        if state is None:
            return
        state.last_price = price

    def apply_buy_fill(self, symbol: str, fill: Fill, fill_price: float) -> PositionState:
        state = self.positions.setdefault(symbol, PositionState(symbol=symbol))
        if state.opened_at is None:
            state.opened_at = fill.event_time
        total_cost_before = state.qty * state.avg_price
        total_cost_after = total_cost_before + (fill.fill_qty * fill_price) + fill.commission + fill.tax
        new_qty = state.qty + fill.fill_qty
        state.qty = new_qty
        state.avg_price = total_cost_after / new_qty if new_qty > 0 else 0.0
        state.last_price = fill_price
        self.cash_balance -= (fill.fill_qty * fill_price) + fill.commission + fill.tax
        return state

    def close_position(self, symbol: str, fill: Fill, fill_price: float) -> PositionState:
        state = self.positions.setdefault(symbol, PositionState(symbol=symbol))
        close_qty = min(fill.fill_qty, state.qty)
        gross_proceeds = close_qty * fill_price
        total_cost = close_qty * state.avg_price
        realized = gross_proceeds - total_cost - fill.commission - fill.tax
        state.qty -= close_qty
        state.last_price = fill_price
        state.realized_pnl += realized
        self.realized_pnl_total += realized
        self.cash_balance += gross_proceeds - fill.commission - fill.tax
        if state.qty == 0:
            state.avg_price = 0.0
            state.opened_at = None
        return state

    def to_position_record(self, symbol: str, updated_at: datetime) -> PaperPosition:
        state = self.positions[symbol]
        return PaperPosition(
            symbol=symbol,
            opened_at=state.opened_at,
            updated_at=updated_at,
            qty=state.qty,
            avg_price=state.avg_price,
            last_price=state.last_price,
            market_value=state.market_value,
            cost_basis=state.cost_basis,
            realized_pnl=state.realized_pnl,
            unrealized_pnl=state.unrealized_pnl,
        )

    def to_portfolio_snapshot(self, snapshot_id: str, event_time: datetime) -> PortfolioSnapshot:
        gross_market_value = sum(position.market_value for position in self.positions.values() if position.qty > 0)
        unrealized_pnl = sum(position.unrealized_pnl for position in self.positions.values() if position.qty > 0)
        return PortfolioSnapshot(
            snapshot_id=snapshot_id,
            event_time=event_time,
            cash_balance=self.cash_balance,
            gross_market_value=gross_market_value,
            net_liquidation_value=self.cash_balance + gross_market_value,
            open_positions=self.open_position_count(),
            realized_pnl=self.realized_pnl_total,
            unrealized_pnl=unrealized_pnl,
        )
