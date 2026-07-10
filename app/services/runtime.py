"""Runtime orchestration for the demo pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.brokers.kis_readonly import get_kis_readonly_client
from app.collectors.market_data import (
    build_sample_orderbook,
    build_sample_ticks,
    market_tick_from_kis_quote,
    orderbook_from_kis_quote,
)
from app.config.settings import load_settings
from app.features.minute_bars import aggregate_ticks_to_minute_bar, build_feature_snapshot
from app.models.loader import load_prediction_model
from app.observability.logging import configure_logging
from app.paper_trading.book import PaperPortfolioBook
from app.paper_trading.engine import PaperTradingEngine
from app.paper_trading.signals import SignalPolicy
from app.portfolio.allocator import PositionAllocator
from app.reconciliation.service import build_placeholder_reconciliation_run
from app.replay.service import build_placeholder_replay_run
from app.risk.gates import SpreadRiskGate, TradingWindowGate
from app.storage.contracts import RiskEvent
from app.storage.runtime_writer import RuntimeWriter
from app.utils.time import now_local


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DemoPipelineResult:
    symbol: str
    order_created: bool
    signal_allowed: bool
    prediction_up_probability: float
    runtime_root: Path

    def to_dict(self) -> dict[str, str | bool | float]:
        return {
            "symbol": self.symbol,
            "order_created": self.order_created,
            "signal_allowed": self.signal_allowed,
            "prediction_up_probability": round(self.prediction_up_probability, 6),
            "runtime_root": str(self.runtime_root),
        }


@dataclass(slots=True)
class KisSnapshotPipelineResult:
    symbol: str
    current_price: int
    ask_price_1: int
    bid_price_1: int
    runtime_root: Path

    def to_dict(self) -> dict[str, str | int]:
        return {
            "symbol": self.symbol,
            "current_price": self.current_price,
            "ask_price_1": self.ask_price_1,
            "bid_price_1": self.bid_price_1,
            "runtime_root": str(self.runtime_root),
        }


def run_demo_pipeline(project_root: Path, symbol: str = "005930") -> DemoPipelineResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    writer = RuntimeWriter.from_settings(settings)
    portfolio_book = PaperPortfolioBook(
        initial_cash=settings.strategy.paper_initial_cash,
        max_open_positions=settings.strategy.max_open_positions,
    )

    ticks = build_sample_ticks(symbol, timezone_name=settings.timezone)
    orderbook = build_sample_orderbook(symbol, timezone_name=settings.timezone)
    for tick in ticks:
        writer.write_market_tick(tick)
    writer.write_orderbook_snapshot(orderbook)

    bar = aggregate_ticks_to_minute_bar(symbol, ticks)
    features = build_feature_snapshot(bar, orderbook, settings.feature_set_version)
    writer.write_minute_bar(bar)
    writer.write_feature_snapshot(features)

    model = load_prediction_model(settings, horizon_min=15)
    prediction = model.predict(features, horizon_min=15, prediction_id="pred-demo-15m-001")
    writer.write_prediction(prediction)

    time_gate = TradingWindowGate(
        new_entry_start=settings.market_calendar.new_entry_start,
        new_entry_end=settings.market_calendar.new_entry_end,
    ).evaluate(prediction.event_time)
    spread_gate = SpreadRiskGate(settings.strategy.max_spread_bps).evaluate(orderbook)

    signal_policy = SignalPolicy(
        strategy_version=settings.strategy.strategy_version,
        min_confidence=settings.strategy.min_signal_confidence,
    )
    signal = signal_policy.evaluate(
        prediction=prediction,
        orderbook=orderbook,
        time_gate=time_gate,
        spread_gate=spread_gate,
        signal_id="signal-demo-001",
    )
    writer.write_trade_signal(signal)

    allocator = PositionAllocator(
        portfolio_version=settings.strategy.portfolio_version,
        max_position_pct=settings.strategy.max_position_pct,
    )
    target = allocator.allocate(
        signal,
        last_price=bar.close,
        cash_balance=settings.strategy.paper_initial_cash,
        target_id="target-demo-001",
    )
    writer.write_target_position(target)
    portfolio_book.mark_price(symbol, bar.close)

    order_created = False
    can_open, open_reason = portfolio_book.can_open(symbol)
    if signal.allowed and settings.strategy.enable_paper_execution and target.target_qty > 0 and can_open:
        engine = PaperTradingEngine(slippage_bps=settings.strategy.slippage_bps)
        order = engine.create_order(target, signal, order_id="paper-order-001")
        ack = engine.acknowledge(order, order_event_id="paper-order-event-ack-001")
        execution_price = order.limit_price * (1 + (settings.strategy.slippage_bps / 10_000))
        fill_event, fill = engine.fill(
            order,
            fill_price=execution_price,
            order_event_id="paper-order-event-fill-001",
            fill_id="paper-fill-001",
        )
        writer.write_paper_order(order)
        writer.write_order_event(ack)
        writer.write_order_event(fill_event)
        writer.write_fill(fill)
        portfolio_book.apply_buy_fill(symbol=symbol, fill=fill, fill_price=execution_price)
        writer.write_paper_position(portfolio_book.to_position_record(symbol, updated_at=fill.event_time))
        writer.write_portfolio_snapshot(
            portfolio_book.to_portfolio_snapshot(snapshot_id="portfolio-demo-001", event_time=fill.event_time)
        )
        order_created = True
        LOGGER.info("Demo paper order created for %s qty=%s", order.symbol, order.qty)
    else:
        risk_event = RiskEvent(
            risk_event_id="risk-demo-001",
            symbol=symbol,
            event_time=prediction.event_time,
            gate="signal_policy",
            detail=f"signal_allowed={signal.allowed};open_reason={open_reason}",
        )
        writer.write_risk_event(risk_event)
        LOGGER.info("Signal blocked for %s: %s", symbol, signal.reason)

    reconciliation = build_placeholder_reconciliation_run(
        as_of=prediction.event_time,
        has_order=order_created,
        reconciliation_id="recon-demo-001",
    )
    replay = build_placeholder_replay_run(as_of=prediction.event_time, replay_id="replay-demo-001")
    writer.write_reconciliation_run(reconciliation)
    writer.write_replay_run(replay)

    return DemoPipelineResult(
        symbol=symbol,
        order_created=order_created,
        signal_allowed=signal.allowed,
        prediction_up_probability=prediction.probability_up,
        runtime_root=settings.runtime_data_dir,
    )


def run_kis_snapshot_pipeline(project_root: Path, symbol: str = "005930") -> KisSnapshotPipelineResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    client = get_kis_readonly_client(settings)
    writer = RuntimeWriter.from_settings(settings)

    current_quote = client.get_current_price(symbol=symbol)
    orderbook_quote = client.get_orderbook(symbol=symbol)
    event_time = now_local(settings.timezone)

    tick = market_tick_from_kis_quote(current_quote, event_time=event_time)
    orderbook = orderbook_from_kis_quote(orderbook_quote, event_time=event_time)
    writer.write_market_tick(tick)
    writer.write_orderbook_snapshot(orderbook)

    LOGGER.info(
        "KIS snapshot stored for %s current=%s ask1=%s bid1=%s",
        symbol,
        current_quote.current_price,
        orderbook_quote.ask_price_1,
        orderbook_quote.bid_price_1,
    )
    return KisSnapshotPipelineResult(
        symbol=symbol,
        current_price=current_quote.current_price,
        ask_price_1=orderbook_quote.ask_price_1,
        bid_price_1=orderbook_quote.bid_price_1,
        runtime_root=settings.runtime_data_dir,
    )
