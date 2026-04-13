"""Realtime streaming services for WebSocket-driven processing."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.brokers.kis_auth import KisTokenManager, get_active_kis_profile
from app.brokers.kis_quote_ws import (
    DOMESTIC_ORDERBOOK_COLUMNS,
    DOMESTIC_ORDERBOOK_TR_ID,
    DOMESTIC_TRADE_COLUMNS,
    DOMESTIC_TRADE_TR_ID,
    KisApiError,
    KisWebSocketQuoteClient,
    parse_kis_ws_frame,
)
from app.collectors.market_data import market_tick_from_kis_ws_record, orderbook_from_kis_ws_record
from app.collectors.market_data import event_time_from_kis_ws_record
from app.config.settings import AppSettings, load_settings
from app.features.minute_bars import aggregate_ticks_to_minute_bar, build_feature_snapshot
from app.models.loader import load_prediction_model
from app.observability.logging import configure_logging
from app.paper_trading.book import PaperPortfolioBook
from app.paper_trading.engine import PaperTradingEngine
from app.paper_trading.signals import SignalPolicy
from app.portfolio.allocator import PositionAllocator
from app.risk.gates import SpreadRiskGate, TradingWindowGate
from app.storage.contracts import MarketTickEvent, OrderbookSnapshot, RiskEvent
from app.storage.runtime_writer import RuntimeWriter
from app.universe.watchlist import load_watchlist
from app.utils.time import now_local, parse_hhmm


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class OnlineSymbolState:
    symbol: str
    current_minute: datetime | None = None
    ticks: list[MarketTickEvent] = field(default_factory=list)
    latest_orderbook: OrderbookSnapshot | None = None


@dataclass(slots=True)
class OnlinePipelineResult:
    frames_received: int
    control_frames: int
    raw_trade_events: int
    raw_orderbook_events: int
    minute_bars_written: int
    predictions_written: int
    signals_written: int
    orders_written: int
    runtime_root: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "frames_received": self.frames_received,
            "control_frames": self.control_frames,
            "raw_trade_events": self.raw_trade_events,
            "raw_orderbook_events": self.raw_orderbook_events,
            "minute_bars_written": self.minute_bars_written,
            "predictions_written": self.predictions_written,
            "signals_written": self.signals_written,
            "orders_written": self.orders_written,
            "runtime_root": str(self.runtime_root),
        }


class OnlinePipelineProcessor:
    def __init__(
        self,
        settings: AppSettings,
        starting_cash_balance: float | None = None,
        max_hold_minutes: int | None = None,
        prediction_horizons: tuple[int, ...] = (15, 60),
        trading_horizon_min: int = 15,
        id_namespace: str = "online",
        raw_source: str = "kis-ws",
    ) -> None:
        self.settings = settings
        self.writer = RuntimeWriter.from_settings(settings)
        self.prediction_horizons = tuple(sorted({int(horizon) for horizon in prediction_horizons if int(horizon) > 0}))
        if not self.prediction_horizons:
            self.prediction_horizons = (15,)
        self.trading_horizon_min = trading_horizon_min if trading_horizon_min in self.prediction_horizons else self.prediction_horizons[0]
        self.models = {
            horizon: load_prediction_model(settings, horizon_min=horizon)
            for horizon in self.prediction_horizons
        }
        self.id_namespace = id_namespace
        self.raw_source = raw_source
        self.signal_policy = SignalPolicy(
            strategy_version=settings.strategy.strategy_version,
            min_confidence=settings.strategy.min_signal_confidence,
        )
        self.allocator = PositionAllocator(
            portfolio_version=settings.strategy.portfolio_version,
            max_position_pct=settings.strategy.max_position_pct,
        )
        self.engine = PaperTradingEngine(slippage_bps=settings.strategy.slippage_bps)
        self.portfolio_book = PaperPortfolioBook(
            initial_cash=starting_cash_balance if starting_cash_balance is not None else settings.strategy.paper_initial_cash,
            max_open_positions=settings.strategy.max_open_positions,
        )
        self.max_hold_minutes = max_hold_minutes if max_hold_minutes is not None else settings.strategy.max_hold_minutes
        self.forced_flat_time = parse_hhmm(settings.market_calendar.forced_flat_time)
        self.time_gate = TradingWindowGate(
            new_entry_start=settings.market_calendar.new_entry_start,
            new_entry_end=settings.market_calendar.new_entry_end,
        )
        self.spread_gate = SpreadRiskGate(settings.strategy.max_spread_bps)
        self.states: dict[str, OnlineSymbolState] = {}
        self.raw_trade_events = 0
        self.raw_orderbook_events = 0
        self.minute_bars_written = 0
        self.predictions_written = 0
        self.signals_written = 0
        self.orders_written = 0
        self._sequence = 0

    def _next_id(self, prefix: str) -> str:
        self._sequence += 1
        return f"{prefix}-{self._sequence:06d}"

    def _next_scoped_id(self, prefix_root: str) -> str:
        return self._next_id(f"{prefix_root}-{self.id_namespace}")

    @staticmethod
    def _minute_floor(timestamp: datetime) -> datetime:
        return timestamp.replace(second=0, microsecond=0)

    def _state(self, symbol: str) -> OnlineSymbolState:
        if symbol not in self.states:
            self.states[symbol] = OnlineSymbolState(symbol=symbol)
        return self.states[symbol]

    def process_trade_record(
        self,
        record: dict[str, str],
        event_time: datetime | None = None,
        source: str | None = None,
    ) -> None:
        event_time = event_time or event_time_from_kis_ws_record(
            record,
            timezone_name=self.settings.timezone,
            fallback=now_local(self.settings.timezone),
        )
        tick = market_tick_from_kis_ws_record(
            record,
            event_time=event_time,
            source=source or self.raw_source,
        )
        if not tick.symbol:
            return
        self.writer.write_market_tick(tick)
        self.raw_trade_events += 1

        state = self._state(tick.symbol)
        minute = self._minute_floor(tick.event_time)
        if state.current_minute is None:
            state.current_minute = minute
        elif minute != state.current_minute:
            self._finalize_symbol_minute(state)
            state.current_minute = minute
            state.ticks.clear()
        state.ticks.append(tick)

    def process_orderbook_record(
        self,
        record: dict[str, str],
        event_time: datetime | None = None,
        source: str | None = None,
    ) -> None:
        event_time = event_time or event_time_from_kis_ws_record(
            record,
            timezone_name=self.settings.timezone,
            fallback=now_local(self.settings.timezone),
        )
        snapshot = orderbook_from_kis_ws_record(
            record,
            event_time=event_time,
            source=source or self.raw_source,
        )
        if not snapshot.symbol:
            return
        self.writer.write_orderbook_snapshot(snapshot)
        self.raw_orderbook_events += 1
        state = self._state(snapshot.symbol)
        state.latest_orderbook = snapshot

    def _finalize_symbol_minute(self, state: OnlineSymbolState) -> None:
        if not state.ticks or state.latest_orderbook is None:
            return

        bar = aggregate_ticks_to_minute_bar(state.symbol, state.ticks)
        self.portfolio_book.mark_price(state.symbol, bar.close)
        close_reason = self._maybe_close_position(state.symbol, bar.close, bar.bar_time)
        features = build_feature_snapshot(bar, state.latest_orderbook, self.settings.feature_set_version)
        predictions = []
        prediction_by_horizon = {}
        for horizon in self.prediction_horizons:
            prediction = self.models[horizon].predict(
                feature_snapshot=features,
                horizon_min=horizon,
                prediction_id=self._next_scoped_id(f"pred-h{horizon}"),
            )
            predictions.append(prediction)
            prediction_by_horizon[horizon] = prediction
        prediction = prediction_by_horizon[self.trading_horizon_min]
        time_decision = self.time_gate.evaluate(prediction.event_time)
        spread_decision = self.spread_gate.evaluate(state.latest_orderbook)
        signal = self.signal_policy.evaluate(
            prediction=prediction,
            orderbook=state.latest_orderbook,
            time_gate=time_decision,
            spread_gate=spread_decision,
            signal_id=self._next_scoped_id("signal"),
        )
        target = self.allocator.allocate(
            signal=signal,
            last_price=bar.close,
            cash_balance=self.portfolio_book.cash_balance,
            target_id=self._next_scoped_id("target"),
        )

        self.writer.write_minute_bar(bar)
        self.writer.write_feature_snapshot(features)
        for prediction_row in predictions:
            self.writer.write_prediction(prediction_row)
        self.writer.write_trade_signal(signal)
        self.writer.write_target_position(target)
        self.minute_bars_written += 1
        self.predictions_written += len(predictions)
        self.signals_written += 1

        can_open, open_reason = self.portfolio_book.can_open(state.symbol)
        if close_reason is not None:
            can_open = False
            open_reason = close_reason
        if signal.allowed and self.settings.strategy.enable_paper_execution and target.target_qty > 0 and can_open:
            order = self.engine.create_order(target, signal, order_id=self._next_scoped_id("paper-order"))
            ack = self.engine.acknowledge(order, order_event_id=self._next_scoped_id("order-event"))
            execution_price = order.limit_price * (1 + (self.settings.strategy.slippage_bps / 10_000))
            fill_event, fill = self.engine.fill(
                order,
                fill_price=execution_price,
                order_event_id=self._next_scoped_id("order-event"),
                fill_id=self._next_scoped_id("fill"),
            )
            self.writer.write_paper_order(order)
            self.writer.write_order_event(ack)
            self.writer.write_order_event(fill_event)
            self.writer.write_fill(fill)
            self.portfolio_book.apply_buy_fill(symbol=state.symbol, fill=fill, fill_price=execution_price)
            self.writer.write_paper_position(
                self.portfolio_book.to_position_record(state.symbol, updated_at=fill.event_time)
            )
            self.writer.write_portfolio_snapshot(
                self.portfolio_book.to_portfolio_snapshot(
                    snapshot_id=self._next_scoped_id("portfolio"),
                    event_time=fill.event_time,
                )
            )
            self.orders_written += 1
        else:
            risk_event = RiskEvent(
                risk_event_id=self._next_scoped_id("risk"),
                symbol=state.symbol,
                event_time=prediction.event_time,
                gate="online_signal_policy",
                detail=f"signal_allowed={signal.allowed};open_reason={open_reason}",
            )
            self.writer.write_risk_event(risk_event)

    def _maybe_close_position(self, symbol: str, mark_price: float, event_time: datetime) -> str | None:
        state = self.portfolio_book.positions.get(symbol)
        if state is None or state.qty <= 0 or state.opened_at is None:
            return None

        hold_minutes = (event_time - state.opened_at).total_seconds() / 60
        is_forced_flat = event_time.timetz().replace(tzinfo=None) >= self.forced_flat_time
        if hold_minutes < self.max_hold_minutes and not is_forced_flat:
            return None

        order_id = self._next_scoped_id("paper-order-close")
        order_event_id = self._next_scoped_id("order-event-close")
        fill_event_id = self._next_scoped_id("order-event-close")
        fill_id = self._next_scoped_id("fill-close")
        target_qty = state.qty
        if target_qty <= 0:
            return

        from app.storage.contracts import PaperOrder  # local import to avoid widening top-level imports

        order = PaperOrder(
            order_id=order_id,
            symbol=symbol,
            event_time=event_time,
            side="sell",
            qty=target_qty,
            limit_price=mark_price,
            status="created",
        )
        ack = self.engine.acknowledge(order, order_event_id=order_event_id)
        fill_event, fill = self.engine.fill(
            order,
            fill_price=mark_price,
            order_event_id=fill_event_id,
            fill_id=fill_id,
        )
        self.writer.write_paper_order(order)
        self.writer.write_order_event(ack)
        self.writer.write_order_event(fill_event)
        self.writer.write_fill(fill)
        self.portfolio_book.close_position(symbol=symbol, fill=fill, fill_price=mark_price)
        self.writer.write_paper_position(self.portfolio_book.to_position_record(symbol, updated_at=event_time))
        self.writer.write_portfolio_snapshot(
            self.portfolio_book.to_portfolio_snapshot(
                snapshot_id=self._next_scoped_id("portfolio-close"),
                event_time=event_time,
            )
        )
        self.orders_written += 1
        return "recently_closed"

    def flush(self) -> OnlinePipelineResult:
        for state in self.states.values():
            self._finalize_symbol_minute(state)
            state.ticks.clear()
        return OnlinePipelineResult(
            frames_received=0,
            control_frames=0,
            raw_trade_events=self.raw_trade_events,
            raw_orderbook_events=self.raw_orderbook_events,
            minute_bars_written=self.minute_bars_written,
            predictions_written=self.predictions_written,
            signals_written=self.signals_written,
            orders_written=self.orders_written,
            runtime_root=self.settings.runtime_data_dir,
        )


def replay_ws_frames(project_root: Path, frames: list[str], max_hold_minutes: int = 20) -> OnlinePipelineResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    processor = OnlinePipelineProcessor(
        settings,
        max_hold_minutes=max_hold_minutes,
        id_namespace="replay",
        raw_source="kis-ws-replay",
    )
    frames_received = 0
    control_frames = 0

    for frame in frames:
        frames_received += 1
        parsed = parse_kis_ws_frame(frame)
        tr_id = parsed.get("tr_id")
        if parsed.get("frame_type") != "pipe-delimited" or not tr_id:
            control_frames += 1
            continue
        for record in parsed.get("records", []):
            if tr_id == DOMESTIC_TRADE_TR_ID:
                processor.process_trade_record(record)
            elif tr_id == DOMESTIC_ORDERBOOK_TR_ID:
                processor.process_orderbook_record(record)
    result = processor.flush()
    result.frames_received = frames_received
    result.control_frames = control_frames
    return result


def build_sample_ws_frames(symbol: str = "005930") -> list[str]:
    trade_rows: list[dict[str, str]] = [
        {
            "MKSC_SHRN_ISCD": symbol,
            "STCK_PRPR": "70100",
            "CNTG_VOL": "10",
            "ASKP1": "70105",
            "BIDP1": "70095",
            "STCK_CNTG_HOUR": "091500",
        },
        {
            "MKSC_SHRN_ISCD": symbol,
            "STCK_PRPR": "70120",
            "CNTG_VOL": "12",
            "ASKP1": "70125",
            "BIDP1": "70115",
            "STCK_CNTG_HOUR": "091530",
        },
        {
            "MKSC_SHRN_ISCD": symbol,
            "STCK_PRPR": "70150",
            "CNTG_VOL": "14",
            "ASKP1": "70155",
            "BIDP1": "70145",
            "STCK_CNTG_HOUR": "091601",
        },
    ]
    orderbook_rows: list[dict[str, str]] = [
        {
            "MKSC_SHRN_ISCD": symbol,
            "ASKP1": "70105",
            "BIDP1": "70095",
            "ASKP_RSQN1": "100",
            "BIDP_RSQN1": "120",
            "TOTAL_ASKP_RSQN": "1000",
            "TOTAL_BIDP_RSQN": "1200",
            "BSOP_HOUR": "091500",
        },
        {
            "MKSC_SHRN_ISCD": symbol,
            "ASKP1": "70155",
            "BIDP1": "70145",
            "ASKP_RSQN1": "90",
            "BIDP_RSQN1": "130",
            "TOTAL_ASKP_RSQN": "980",
            "TOTAL_BIDP_RSQN": "1250",
            "BSOP_HOUR": "091601",
        },
    ]
    frames = [
        _build_pipe_frame(DOMESTIC_ORDERBOOK_TR_ID, DOMESTIC_ORDERBOOK_COLUMNS, orderbook_rows[:1]),
        _build_pipe_frame(DOMESTIC_TRADE_TR_ID, DOMESTIC_TRADE_COLUMNS, trade_rows[:2]),
        _build_pipe_frame(DOMESTIC_ORDERBOOK_TR_ID, DOMESTIC_ORDERBOOK_COLUMNS, orderbook_rows[1:]),
        _build_pipe_frame(DOMESTIC_TRADE_TR_ID, DOMESTIC_TRADE_COLUMNS, trade_rows[2:]),
    ]
    return frames


async def run_kis_ws_listener(
    project_root: Path,
    symbols: list[str] | None = None,
    watchlist_path: str | Path | None = None,
    include_trade: bool = True,
    include_orderbook: bool = True,
    max_frames: int = 50,
    max_reconnects: int = 2,
) -> OnlinePipelineResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    resolved_symbols = symbols or load_watchlist(project_root=project_root, watchlist_path=watchlist_path)
    if not resolved_symbols:
        raise ValueError("No symbols were provided and watchlist is empty.")
    if not include_trade and not include_orderbook:
        raise ValueError("At least one channel must be enabled.")

    profile = get_active_kis_profile(settings)
    token_manager = KisTokenManager(profile)
    ws_client = KisWebSocketQuoteClient(profile=profile, token_manager=token_manager)
    processor = OnlinePipelineProcessor(settings)
    frames_received = 0
    control_frames = 0

    async for frame in ws_client.listen(
        symbols=resolved_symbols,
        include_trade=include_trade,
        include_orderbook=include_orderbook,
        max_frames=max_frames,
        max_reconnects=max_reconnects,
    ):
        frames_received += 1
        parsed = parse_kis_ws_frame(frame)
        tr_id = parsed.get("tr_id")
        if parsed.get("frame_type") != "pipe-delimited" or not tr_id:
            control_frames += 1
            continue
        for record in parsed.get("records", []):
            if tr_id == DOMESTIC_TRADE_TR_ID:
                processor.process_trade_record(record)
            elif tr_id == DOMESTIC_ORDERBOOK_TR_ID:
                processor.process_orderbook_record(record)
    result = processor.flush()
    result.frames_received = frames_received
    result.control_frames = control_frames
    return result


def run_kis_ws_listener_sync(
    project_root: Path,
    symbols: list[str] | None = None,
    watchlist_path: str | Path | None = None,
    include_trade: bool = True,
    include_orderbook: bool = True,
    max_frames: int = 50,
    max_reconnects: int = 2,
) -> OnlinePipelineResult:
    try:
        return asyncio.run(
            run_kis_ws_listener(
                project_root=project_root,
                symbols=symbols,
                watchlist_path=watchlist_path,
                include_trade=include_trade,
                include_orderbook=include_orderbook,
                max_frames=max_frames,
                max_reconnects=max_reconnects,
            )
        )
    except KisApiError:
        raise


def _build_pipe_frame(tr_id: str, columns: list[str], records: list[dict[str, str]]) -> str:
    tokens: list[str] = []
    for record in records:
        tokens.extend(record.get(column, "") for column in columns)
    return f"0|{tr_id}|{len(records)}|{'^'.join(tokens)}"
