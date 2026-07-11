"""Cash- and position-constrained replay for research policy evaluation."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import math
import random
from statistics import mean, pstdev
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class DecisionPoint:
    decision_id: str
    symbol: str
    event_time: datetime
    avoid: bool = False


@dataclass(frozen=True, slots=True)
class DecisionEpisode:
    episode_id: str
    symbol: str
    event_time: datetime
    last_signal_time: datetime
    signal_rows: int
    avoid: bool


@dataclass(frozen=True, slots=True)
class ReplayBar:
    symbol: str
    bar_time: datetime
    open_price: float
    close_price: float


@dataclass(frozen=True, slots=True)
class ExecutableDecision:
    episode_id: str
    symbol: str
    signal_time: datetime
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    signal_rows: int
    avoid: bool


def group_decision_episodes(
    points: Sequence[DecisionPoint],
    *,
    max_gap_seconds: int = 90,
) -> list[DecisionEpisode]:
    """Collapse repeated minute signals into one decision episode per symbol."""
    if max_gap_seconds < 0:
        raise ValueError("max_gap_seconds must be non-negative")

    grouped: dict[str, list[DecisionPoint]] = {}
    for point in points:
        grouped.setdefault(point.symbol, []).append(point)

    episodes: list[DecisionEpisode] = []
    for symbol, symbol_points in grouped.items():
        ordered = sorted(symbol_points, key=lambda item: (item.event_time, item.decision_id))
        current: list[DecisionPoint] = []
        for point in ordered:
            if current:
                previous = current[-1]
                gap = (point.event_time - previous.event_time).total_seconds()
                same_day = point.event_time.date() == previous.event_time.date()
                if not same_day or gap > max_gap_seconds:
                    first = current[0]
                    episodes.append(
                        DecisionEpisode(
                            episode_id=f"{symbol}:{first.event_time.isoformat()}",
                            symbol=symbol,
                            event_time=first.event_time,
                            last_signal_time=current[-1].event_time,
                            signal_rows=len(current),
                            avoid=first.avoid,
                        )
                    )
                    current = []
            current.append(point)
        if current:
            first = current[0]
            episodes.append(
                DecisionEpisode(
                    episode_id=f"{symbol}:{first.event_time.isoformat()}",
                    symbol=symbol,
                    event_time=first.event_time,
                    last_signal_time=current[-1].event_time,
                    signal_rows=len(current),
                    avoid=first.avoid,
                )
            )

    return sorted(episodes, key=lambda item: (item.event_time, item.symbol, item.episode_id))


def build_executable_decisions(
    episodes: Sequence[DecisionEpisode],
    bars_by_symbol: dict[str, Sequence[ReplayBar]],
    *,
    horizon_min: int,
    forced_flat_time: time,
) -> tuple[list[ExecutableDecision], dict[str, int]]:
    """Use the next available minute open after a completed signal bar."""
    if horizon_min <= 0:
        raise ValueError("horizon_min must be positive")

    normalized: dict[str, tuple[list[datetime], list[ReplayBar]]] = {}
    for symbol, bars in bars_by_symbol.items():
        ordered = sorted(bars, key=lambda item: item.bar_time)
        normalized[symbol] = ([item.bar_time for item in ordered], ordered)

    executable: list[ExecutableDecision] = []
    skipped = {
        "missing_symbol_bars": 0,
        "missing_next_entry_bar": 0,
        "outside_entry_window": 0,
        "missing_exit_bar": 0,
        "cross_day_bar": 0,
        "invalid_price": 0,
    }
    for episode in episodes:
        bar_index = normalized.get(episode.symbol)
        if bar_index is None:
            skipped["missing_symbol_bars"] += 1
            continue
        times, bars = bar_index
        entry_index = bisect_right(times, episode.event_time)
        if entry_index >= len(bars):
            skipped["missing_next_entry_bar"] += 1
            continue
        entry_bar = bars[entry_index]
        if entry_bar.bar_time.date() != episode.event_time.date():
            skipped["cross_day_bar"] += 1
            continue

        forced_exit = datetime.combine(
            episode.event_time.date(),
            forced_flat_time,
            tzinfo=episode.event_time.tzinfo,
        )
        target_exit = min(episode.event_time + timedelta(minutes=horizon_min), forced_exit)
        if entry_bar.bar_time >= target_exit:
            skipped["outside_entry_window"] += 1
            continue
        exit_index = bisect_left(times, target_exit)
        if exit_index >= len(bars):
            skipped["missing_exit_bar"] += 1
            continue
        exit_bar = bars[exit_index]
        if exit_bar.bar_time.date() != episode.event_time.date():
            skipped["cross_day_bar"] += 1
            continue
        if entry_bar.open_price <= 0 or exit_bar.open_price <= 0:
            skipped["invalid_price"] += 1
            continue

        executable.append(
            ExecutableDecision(
                episode_id=episode.episode_id,
                symbol=episode.symbol,
                signal_time=episode.event_time,
                entry_time=entry_bar.bar_time,
                entry_price=float(entry_bar.open_price),
                exit_time=exit_bar.bar_time,
                exit_price=float(exit_bar.open_price),
                signal_rows=episode.signal_rows,
                avoid=episode.avoid,
            )
        )

    return (
        sorted(executable, key=lambda item: (item.entry_time, item.symbol, item.episode_id)),
        skipped,
    )


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, probability)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def replay_long_only(
    decisions: Sequence[ExecutableDecision],
    *,
    initial_cash: float,
    max_position_pct: float,
    max_open_positions: int,
    slippage_bps: float,
    commission_rate: float = 0.00015,
    sell_tax_rate: float = 0.00018,
    policy_veto_ids: Iterable[str] | None = None,
    respect_decision_avoid: bool = True,
) -> dict[str, object]:
    """Replay long-only decisions with cash, overlap, and execution costs."""
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if not 0 < max_position_pct <= 1:
        raise ValueError("max_position_pct must be in (0, 1]")
    if max_open_positions <= 0:
        raise ValueError("max_open_positions must be positive")

    veto_ids = set(policy_veto_ids or ())
    slip = max(float(slippage_bps), 0.0) / 10_000.0
    cash = float(initial_cash)
    active: list[dict[str, object]] = []
    closed_trades: list[dict[str, object]] = []
    daily_pnl: dict[str, float] = {}
    equity_curve: list[float] = [float(initial_cash)]
    turnover = 0.0
    counters = {
        "input_opportunities": len(decisions),
        "policy_vetoes": 0,
        "duplicate_symbol_skips": 0,
        "max_position_skips": 0,
        "insufficient_cash_skips": 0,
        "trades_executed": 0,
    }

    def current_equity() -> float:
        marked_positions = sum(
            float(position["qty"]) * float(position["entry_raw_price"])
            for position in active
        )
        return cash + marked_positions

    def observe_equity() -> None:
        equity_curve.append(current_equity())

    def close_position(position: dict[str, object]) -> None:
        nonlocal cash, turnover
        sell_price = float(position["exit_raw_price"]) * (1.0 - slip)
        qty = int(position["qty"])
        gross_proceeds = sell_price * qty
        sell_commission = gross_proceeds * commission_rate
        sell_tax = gross_proceeds * sell_tax_rate
        cash += gross_proceeds - sell_commission - sell_tax
        turnover += gross_proceeds
        entry_total_cost = float(position["entry_total_cost"])
        net_pnl = gross_proceeds - sell_commission - sell_tax - entry_total_cost
        net_return_pct = (net_pnl / entry_total_cost * 100.0) if entry_total_cost else 0.0
        exit_time = position["exit_time"]
        assert isinstance(exit_time, datetime)
        day = exit_time.date().isoformat()
        daily_pnl[day] = daily_pnl.get(day, 0.0) + net_pnl
        closed_trades.append(
            {
                "episode_id": position["episode_id"],
                "symbol": position["symbol"],
                "entry_time": position["entry_time"].isoformat(),
                "exit_time": exit_time.isoformat(),
                "qty": qty,
                "entry_price": float(position["entry_price"]),
                "exit_price": sell_price,
                "net_pnl": net_pnl,
                "net_return_pct": net_return_pct,
            }
        )

    def close_due(current_time: datetime) -> None:
        nonlocal active
        remaining: list[dict[str, object]] = []
        for position in sorted(active, key=lambda item: item["exit_time"]):
            if position["exit_time"] <= current_time:
                close_position(position)
            else:
                remaining.append(position)
        active = remaining
        observe_equity()

    for decision in decisions:
        close_due(decision.entry_time)
        should_veto = decision.episode_id in veto_ids or (
            respect_decision_avoid and decision.avoid
        )
        if should_veto:
            counters["policy_vetoes"] += 1
            continue
        if any(str(position["symbol"]) == decision.symbol for position in active):
            counters["duplicate_symbol_skips"] += 1
            continue
        if len(active) >= max_open_positions:
            counters["max_position_skips"] += 1
            continue

        equity = current_equity()
        target_notional = max(equity * max_position_pct, 0.0)
        buy_price = decision.entry_price * (1.0 + slip)
        unit_cash_cost = buy_price * (1.0 + commission_rate)
        qty = math.floor(min(target_notional, cash) / unit_cash_cost) if unit_cash_cost > 0 else 0
        if qty <= 0:
            counters["insufficient_cash_skips"] += 1
            continue
        gross_cost = buy_price * qty
        buy_commission = gross_cost * commission_rate
        entry_total_cost = gross_cost + buy_commission
        if entry_total_cost > cash:
            counters["insufficient_cash_skips"] += 1
            continue

        cash -= entry_total_cost
        turnover += gross_cost
        active.append(
            {
                "episode_id": decision.episode_id,
                "symbol": decision.symbol,
                "entry_time": decision.entry_time,
                "exit_time": decision.exit_time,
                "entry_raw_price": decision.entry_price,
                "entry_price": buy_price,
                "exit_raw_price": decision.exit_price,
                "entry_total_cost": entry_total_cost,
                "qty": qty,
            }
        )
        counters["trades_executed"] += 1
        observe_equity()

    for position in sorted(active, key=lambda item: item["exit_time"]):
        close_position(position)
        observe_equity()
    active = []

    peak = equity_curve[0]
    max_drawdown_pct = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak * 100.0)

    net_pnl = cash - initial_cash
    trade_returns = [float(item["net_return_pct"]) for item in closed_trades]
    day_values = list(daily_pnl.values())
    return {
        "status": "ok",
        "return_basis": "cash_and_position_constrained_account_equity",
        "execution_price_basis": "next_minute_open_after_completed_signal",
        "initial_cash": initial_cash,
        "final_equity": cash,
        "net_pnl": net_pnl,
        "portfolio_return_pct": net_pnl / initial_cash * 100.0,
        "max_drawdown_pct": max_drawdown_pct,
        "turnover_pct": turnover / initial_cash * 100.0,
        "average_trade_net_return_pct": mean(trade_returns) if trade_returns else 0.0,
        "win_rate": (
            sum(1 for value in trade_returns if value > 0) / len(trade_returns)
            if trade_returns
            else 0.0
        ),
        "trading_days": len(day_values),
        "nonnegative_day_share": (
            sum(1 for value in day_values if value >= 0) / len(day_values)
            if day_values
            else 0.0
        ),
        "daily_net_pnl": dict(sorted(daily_pnl.items())),
        "closed_trades": closed_trades,
        "cost_model": {
            "slippage_bps_per_side": slippage_bps,
            "commission_rate_per_side": commission_rate,
            "sell_tax_rate": sell_tax_rate,
        },
        "constraints": {
            "max_position_pct": max_position_pct,
            "max_open_positions": max_open_positions,
            "duplicate_symbol_positions": "blocked",
            "fractional_shares": "blocked",
        },
        "counters": counters,
        "limitations": [
            "minute-open execution proxy, not tick-level bid/ask queue replay",
            "partial fills and order rejection latency are not modeled",
            "open positions are marked at entry price between exits for drawdown",
        ],
    }


def portfolio_random_control(
    decisions: Sequence[ExecutableDecision],
    *,
    actual_policy_return_pct: float,
    veto_count: int,
    simulations: int,
    seed: int,
    replay_kwargs: dict[str, object],
) -> dict[str, object]:
    """Compare a policy veto with same-count random episode vetoes."""
    if not decisions or veto_count <= 0 or veto_count >= len(decisions) or simulations <= 0:
        return {
            "status": "insufficient_control_sample",
            "population_episodes": len(decisions),
            "veto_count": veto_count,
            "simulations": simulations,
            "passed": False,
        }

    episode_ids = [decision.episode_id for decision in decisions]
    rng = random.Random(seed)
    random_returns: list[float] = []
    for _ in range(simulations):
        veto_ids = set(rng.sample(episode_ids, veto_count))
        result = replay_long_only(
            decisions,
            policy_veto_ids=veto_ids,
            respect_decision_avoid=False,
            **replay_kwargs,
        )
        random_returns.append(float(result["portfolio_return_pct"]))

    expected = mean(random_returns)
    standard_deviation = pstdev(random_returns)
    z_score = (
        (actual_policy_return_pct - expected) / standard_deviation
        if standard_deviation > 0
        else 0.0
    )
    p05 = _percentile(random_returns, 0.05)
    p95 = _percentile(random_returns, 0.95)
    empirical_percentile = (
        sum(1 for value in random_returns if value <= actual_policy_return_pct)
        / len(random_returns)
    )
    if actual_policy_return_pct > p95:
        verdict = "policy_better_than_random_p95"
    elif actual_policy_return_pct < p05:
        verdict = "policy_worse_than_random_p05"
    else:
        verdict = "policy_within_random_band"
    return {
        "status": "ok",
        "population_episodes": len(decisions),
        "veto_count": veto_count,
        "simulations": simulations,
        "seed": seed,
        "actual_policy_return_pct": actual_policy_return_pct,
        "expected_random_policy_return_pct": expected,
        "random_return_std_pct": standard_deviation,
        "random_p05_pct": p05,
        "random_p95_pct": p95,
        "empirical_percentile": empirical_percentile,
        "z_score": z_score,
        "verdict": verdict,
        "passed": verdict == "policy_better_than_random_p95",
    }
