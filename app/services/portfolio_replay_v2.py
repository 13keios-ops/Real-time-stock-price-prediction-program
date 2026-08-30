"""Minute mark-to-market portfolio replay evaluator v2."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
import hashlib
import json
import math
import random
from statistics import mean, pstdev
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

from app.paper_trading.costs import (
    DEFAULT_COMMISSION_RATE,
    DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE,
    DOMESTIC_STOCK_COST_MODEL_VERSION,
)
from app.services.portfolio_replay import (
    ExecutableDecision,
    ReplayBar,
    _percentile,
    replay_long_only,
)


PORTFOLIO_REPLAY_V1_VERSION = "portfolio-replay-v1-entry-mark"
PORTFOLIO_REPLAY_V2_VERSION = "portfolio-replay-v2-minute-mtm"
PORTFOLIO_REPLAY_V2_VALUATION_METHOD = (
    "cash_plus_active_positions_marked_to_observable_minute_market_price"
)
PORTFOLIO_REPLAY_V2_MARK_PRICE_BASIS = (
    "prior_completed_minute_close_available_at_next_minute_boundary;"
    "transaction_minute_open_for_entry_and_exit"
)
PORTFOLIO_REPLAY_V2_BAR_TIMESTAMP_SEMANTICS = (
    "bar_time_is_minute_start;close_is_available_at_bar_time_plus_one_minute"
)


class ReplayCompatibilityError(ValueError):
    """Raised when an official comparison would mix replay identities."""


@dataclass(frozen=True, slots=True)
class PortfolioReplayManifest:
    manifest_version: str
    evaluator_version: str
    valuation_method: str
    mark_price_basis: str
    bar_timestamp_semantics: str
    stale_mark_tolerance_seconds: int
    cost_model_version: str
    model_version: str
    threshold: float
    horizon_min: int
    future_evaluation_start: datetime
    forced_flat_time: time
    initial_cash: float
    slippage_bps_per_side: float
    commission_rate_per_side: float
    sell_tax_rate: float
    cost_sensitivity_multiplier: float
    max_position_pct: float
    max_open_positions: int
    random_control_simulations: int
    random_seed: int
    random_control_strata: tuple[str, ...]
    random_control_time_buckets: tuple[str, ...]
    minimum_trading_days: int
    minimum_episodes: int
    minimum_symbols: int
    future_interval_count: int
    future_interval_rule: str
    normal_cost_rule: str
    double_cost_rule: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["future_evaluation_start"] = self.future_evaluation_start.isoformat()
        payload["forced_flat_time"] = self.forced_flat_time.isoformat(timespec="minutes")
        return payload

    @property
    def sha256(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def cost_parameters(self, scenario: str) -> dict[str, float | str]:
        if scenario == "normal":
            multiplier = 1.0
        elif scenario == "double":
            multiplier = float(self.cost_sensitivity_multiplier)
        else:
            raise ReplayCompatibilityError(f"unsupported cost scenario: {scenario}")
        return {
            "scenario": scenario,
            "sensitivity_multiplier": multiplier,
            "slippage_bps_per_side": float(self.slippage_bps_per_side) * multiplier,
            "commission_rate_per_side": float(self.commission_rate_per_side) * multiplier,
            "sell_tax_rate": float(self.sell_tax_rate) * multiplier,
        }


@dataclass(frozen=True, slots=True)
class MarkResolution:
    status: str
    price: float | None
    source_bar_time: datetime | None
    availability_time: datetime | None
    age_seconds: float | None


@dataclass(frozen=True, slots=True)
class MinuteMarkIndex:
    """Immutable close-price index keyed by the time each close becomes knowable."""

    prices: Mapping[tuple[str, datetime], float | None]
    times_by_symbol: Mapping[str, tuple[datetime, ...]]
    source_bar_count: int

    @classmethod
    def from_bars(
        cls,
        bars_by_symbol: Mapping[str, Sequence[ReplayBar]],
    ) -> "MinuteMarkIndex":
        prices: dict[tuple[str, datetime], float | None] = {}
        times_by_symbol: dict[str, list[datetime]] = {}
        source_bar_count = 0
        for symbol, bars in bars_by_symbol.items():
            for bar in sorted(bars, key=lambda item: item.bar_time):
                source_bar_count += 1
                availability_time = bar.bar_time + timedelta(minutes=1)
                key = (str(symbol), availability_time)
                price = float(bar.close_price)
                normalized_price = price if math.isfinite(price) and price > 0 else None
                if key in prices and prices[key] != normalized_price:
                    raise ReplayCompatibilityError(
                        "conflicting minute close for "
                        f"symbol={symbol} availability_time={availability_time.isoformat()}"
                    )
                if key not in prices:
                    times_by_symbol.setdefault(str(symbol), []).append(availability_time)
                prices[key] = normalized_price
        frozen_times = {
            symbol: tuple(sorted(set(times)))
            for symbol, times in times_by_symbol.items()
        }
        return cls(
            prices=MappingProxyType(prices),
            times_by_symbol=MappingProxyType(frozen_times),
            source_bar_count=source_bar_count,
        )

    def resolve(
        self,
        symbol: str,
        observation_time: datetime,
        *,
        max_staleness_seconds: int,
    ) -> MarkResolution:
        key = (symbol, observation_time)
        if key in self.prices:
            price = self.prices[key]
            if price is None:
                return MarkResolution(
                    status="invalid_exact_mark",
                    price=None,
                    source_bar_time=observation_time - timedelta(minutes=1),
                    availability_time=observation_time,
                    age_seconds=0.0,
                )
            return MarkResolution(
                status="exact",
                price=float(price),
                source_bar_time=observation_time - timedelta(minutes=1),
                availability_time=observation_time,
                age_seconds=0.0,
            )

        times = self.times_by_symbol.get(symbol, ())
        index = bisect_right(times, observation_time) - 1
        if index < 0:
            return MarkResolution(
                status="missing",
                price=None,
                source_bar_time=None,
                availability_time=None,
                age_seconds=None,
            )

        availability_time = times[index]
        age_seconds = (observation_time - availability_time).total_seconds()
        price = self.prices.get((symbol, availability_time))
        if price is None:
            return MarkResolution(
                status="invalid_stale_mark",
                price=None,
                source_bar_time=availability_time - timedelta(minutes=1),
                availability_time=availability_time,
                age_seconds=age_seconds,
            )
        if age_seconds <= max(float(max_staleness_seconds), 0.0):
            return MarkResolution(
                status="stale",
                price=float(price),
                source_bar_time=availability_time - timedelta(minutes=1),
                availability_time=availability_time,
                age_seconds=age_seconds,
            )
        return MarkResolution(
            status="stale_beyond_tolerance",
            price=None,
            source_bar_time=availability_time - timedelta(minutes=1),
            availability_time=availability_time,
            age_seconds=age_seconds,
        )


@dataclass(frozen=True, slots=True)
class MarkCoverage:
    required_mark_count: int
    mark_observation_count: int
    missing_mark_count: int
    stale_mark_count: int
    invalid_mark_count: int
    invalid_reasons: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return self.invalid_mark_count == 0


@dataclass(frozen=True, slots=True)
class PortfolioReplayV2Context:
    """Precomputed marks and timeline reused by actual and random replays."""

    mark_index: MinuteMarkIndex
    timeline: tuple[datetime, ...]
    decision_fingerprint: str
    coverage: MarkCoverage
    manifest_hash: str


def _stable_id_hash(values: Iterable[str]) -> str:
    encoded = json.dumps(
        sorted(str(value) for value in values),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decision_fingerprint(decisions: Sequence[ExecutableDecision]) -> str:
    payload = [
        {
            "episode_id": item.episode_id,
            "symbol": item.symbol,
            "signal_time": item.signal_time.isoformat(),
            "entry_time": item.entry_time.isoformat(),
            "entry_price": float(item.entry_price),
            "exit_time": item.exit_time.isoformat(),
            "exit_price": float(item.exit_price),
            "signal_rows": int(item.signal_rows),
            "avoid": bool(item.avoid),
        }
        for item in sorted(
            decisions,
            key=lambda value: (
                value.entry_time,
                value.symbol,
                value.episode_id,
            ),
        )
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_v2_manifest(manifest: PortfolioReplayManifest) -> None:
    if manifest.evaluator_version != PORTFOLIO_REPLAY_V2_VERSION:
        raise ReplayCompatibilityError("v2 replay requires the v2 evaluator version")
    if manifest.valuation_method != PORTFOLIO_REPLAY_V2_VALUATION_METHOD:
        raise ReplayCompatibilityError("v2 replay valuation method mismatch")
    if manifest.mark_price_basis != PORTFOLIO_REPLAY_V2_MARK_PRICE_BASIS:
        raise ReplayCompatibilityError("v2 replay mark-price basis mismatch")
    if manifest.bar_timestamp_semantics != PORTFOLIO_REPLAY_V2_BAR_TIMESTAMP_SEMANTICS:
        raise ReplayCompatibilityError("v2 replay bar timestamp semantics mismatch")
    if manifest.cost_model_version != DOMESTIC_STOCK_COST_MODEL_VERSION:
        raise ReplayCompatibilityError("v2 replay cost model mismatch")
    if manifest.stale_mark_tolerance_seconds < 0:
        raise ReplayCompatibilityError("stale mark tolerance must be non-negative")
    if manifest.initial_cash <= 0:
        raise ReplayCompatibilityError("initial cash must be positive")
    if not 0 < manifest.max_position_pct <= 1:
        raise ReplayCompatibilityError("max position pct must be in (0, 1]")
    if manifest.max_open_positions <= 0:
        raise ReplayCompatibilityError("max open positions must be positive")


def build_v2_replay_context(
    decisions: Sequence[ExecutableDecision],
    bars_by_symbol: Mapping[str, Sequence[ReplayBar]],
    *,
    manifest: PortfolioReplayManifest,
) -> PortfolioReplayV2Context:
    """Build one immutable market index and validate all potential active paths."""

    _validate_v2_manifest(manifest)
    mark_index = MinuteMarkIndex.from_bars(bars_by_symbol)
    timeline: set[datetime] = set()
    required_mark_count = 0
    mark_observation_count = 0
    missing_mark_count = 0
    stale_mark_count = 0
    invalid_mark_count = 0
    invalid_reasons: set[str] = set()

    for decision in decisions:
        if decision.signal_time < manifest.future_evaluation_start:
            invalid_mark_count += 1
            invalid_reasons.add("decision_before_manifest_future_start")
        if decision.entry_time.date() != decision.exit_time.date():
            invalid_mark_count += 1
            invalid_reasons.add("cross_day_decision_not_supported")
        if decision.exit_time <= decision.entry_time:
            invalid_mark_count += 1
            invalid_reasons.add("nonpositive_holding_interval")
        if decision.exit_time.time() > manifest.forced_flat_time:
            invalid_mark_count += 1
            invalid_reasons.add("exit_after_manifest_forced_flat")
        if (
            not math.isfinite(float(decision.entry_price))
            or not math.isfinite(float(decision.exit_price))
            or decision.entry_price <= 0
            or decision.exit_price <= 0
        ):
            invalid_mark_count += 1
            invalid_reasons.add("invalid_transaction_price")

        event_time = decision.entry_time
        while event_time <= decision.exit_time:
            timeline.add(event_time)
            event_time += timedelta(minutes=1)

        mark_time = decision.entry_time + timedelta(minutes=1)
        while mark_time <= decision.exit_time:
            required_mark_count += 1
            resolution = mark_index.resolve(
                decision.symbol,
                mark_time,
                max_staleness_seconds=manifest.stale_mark_tolerance_seconds,
            )
            if resolution.status == "exact":
                mark_observation_count += 1
            elif resolution.status == "stale":
                mark_observation_count += 1
                stale_mark_count += 1
            elif resolution.status == "missing":
                missing_mark_count += 1
                invalid_mark_count += 1
                invalid_reasons.add("missing_active_position_mark")
            elif resolution.status == "stale_beyond_tolerance":
                stale_mark_count += 1
                invalid_mark_count += 1
                invalid_reasons.add("stale_active_position_mark_beyond_tolerance")
            else:
                invalid_mark_count += 1
                invalid_reasons.add("invalid_active_position_mark")
            mark_time += timedelta(minutes=1)

    coverage = MarkCoverage(
        required_mark_count=required_mark_count,
        mark_observation_count=mark_observation_count,
        missing_mark_count=missing_mark_count,
        stale_mark_count=stale_mark_count,
        invalid_mark_count=invalid_mark_count,
        invalid_reasons=tuple(sorted(invalid_reasons)),
    )
    return PortfolioReplayV2Context(
        mark_index=mark_index,
        timeline=tuple(sorted(timeline)),
        decision_fingerprint=_decision_fingerprint(decisions),
        coverage=coverage,
        manifest_hash=manifest.sha256,
    )


def replay_result_evaluator_version(result: Mapping[str, object]) -> str:
    value = result.get("evaluator_version")
    return str(value) if value else PORTFOLIO_REPLAY_V1_VERSION


def assert_replay_results_compatible(
    results: Sequence[Mapping[str, object]],
    *,
    allow_cost_scenario_difference: bool = False,
) -> None:
    if not results:
        raise ReplayCompatibilityError("at least one replay result is required")
    versions = {replay_result_evaluator_version(result) for result in results}
    if len(versions) != 1:
        raise ReplayCompatibilityError("mixed evaluator versions are not comparable")
    version = next(iter(versions))
    if version == PORTFOLIO_REPLAY_V1_VERSION:
        return
    if version != PORTFOLIO_REPLAY_V2_VERSION:
        raise ReplayCompatibilityError(f"unknown evaluator version: {version}")

    if any(result.get("status") != "ok" for result in results):
        raise ReplayCompatibilityError("invalid replay result cannot enter an official comparison")
    manifest_hashes = {str(result.get("manifest_hash") or "") for result in results}
    if "" in manifest_hashes or len(manifest_hashes) != 1:
        raise ReplayCompatibilityError("mixed or missing manifest hashes are not comparable")
    cost_models = {
        json.dumps(result.get("cost_model"), sort_keys=True, default=str)
        for result in results
    }
    if allow_cost_scenario_difference:
        cost_models = {
            json.dumps(
                {
                    key: value
                    for key, value in dict(result.get("cost_model") or {}).items()
                    if key not in {
                        "scenario",
                        "sensitivity_multiplier",
                        "slippage_bps_per_side",
                        "commission_rate_per_side",
                        "sell_tax_rate",
                    }
                },
                sort_keys=True,
                default=str,
            )
            for result in results
        }
    if len(cost_models) != 1:
        raise ReplayCompatibilityError("mixed cost assumptions are not comparable")
    constraints = {
        json.dumps(result.get("constraints"), sort_keys=True, default=str)
        for result in results
    }
    if len(constraints) != 1:
        raise ReplayCompatibilityError("mixed portfolio constraints are not comparable")


replay_long_only_v1 = replay_long_only


def _v2_metadata(
    manifest: PortfolioReplayManifest,
    *,
    cost_scenario: str,
) -> tuple[dict[str, object], dict[str, object]]:
    cost = manifest.cost_parameters(cost_scenario)
    cost_model = {
        "version": manifest.cost_model_version,
        "scope": "ordinary_kospi_kosdaq_shares_2026",
        **cost,
    }
    constraints = {
        "initial_cash": float(manifest.initial_cash),
        "max_position_pct": float(manifest.max_position_pct),
        "max_open_positions": int(manifest.max_open_positions),
        "duplicate_symbol_positions": "blocked",
        "fractional_shares": "blocked",
        "forced_flat_time": manifest.forced_flat_time.isoformat(timespec="minutes"),
    }
    return cost_model, constraints


def _invalid_v2_result(
    *,
    manifest: PortfolioReplayManifest,
    cost_scenario: str,
    result_role: str,
    future_interval_id: str,
    reason: str,
    coverage: MarkCoverage,
) -> dict[str, object]:
    cost_model, constraints = _v2_metadata(manifest, cost_scenario=cost_scenario)
    return {
        "status": "invalid_evaluation",
        "invalid_evaluation_reason": reason,
        "evaluator_version": manifest.evaluator_version,
        "valuation_method": manifest.valuation_method,
        "mark_price_basis": manifest.mark_price_basis,
        "bar_timestamp_semantics": manifest.bar_timestamp_semantics,
        "manifest_hash": manifest.sha256,
        "manifest_version": manifest.manifest_version,
        "result_role": result_role,
        "future_interval_id": future_interval_id,
        "cost_model": cost_model,
        "constraints": constraints,
        "mark_observation_count": int(coverage.mark_observation_count),
        "missing_mark_count": int(coverage.missing_mark_count),
        "stale_mark_count": int(coverage.stale_mark_count),
        "invalid_mark_count": int(coverage.invalid_mark_count),
        "invalid_mark_reasons": list(coverage.invalid_reasons),
    }


def replay_long_only_v2(
    decisions: Sequence[ExecutableDecision],
    *,
    context: PortfolioReplayV2Context,
    manifest: PortfolioReplayManifest,
    cost_scenario: str = "normal",
    policy_veto_ids: Iterable[str] | None = None,
    respect_decision_avoid: bool = True,
    result_role: str = "portfolio_replay",
    future_interval_id: str = "unassigned",
) -> dict[str, object]:
    """Replay with minute MTM marks available at each minute boundary.

    At time T, an already-open position is marked with the close of the bar
    starting at T-1 minute. That close becomes available only at T. Entry and
    exit execution retain the v1 transaction convention: the current bar open.
    """

    _validate_v2_manifest(manifest)
    if context.manifest_hash != manifest.sha256:
        raise ReplayCompatibilityError("replay context manifest mismatch")
    if context.decision_fingerprint != _decision_fingerprint(decisions):
        raise ReplayCompatibilityError("replay context decision population mismatch")
    cost_model, constraints = _v2_metadata(manifest, cost_scenario=cost_scenario)
    if not context.coverage.valid:
        return _invalid_v2_result(
            manifest=manifest,
            cost_scenario=cost_scenario,
            result_role=result_role,
            future_interval_id=future_interval_id,
            reason=";".join(context.coverage.invalid_reasons) or "invalid_mark_coverage",
            coverage=context.coverage,
        )

    slippage = (
        float(cost_model["slippage_bps_per_side"]) / 10_000.0
    )
    commission_rate = float(cost_model["commission_rate_per_side"])
    sell_tax_rate = float(cost_model["sell_tax_rate"])
    veto_ids = set(str(value) for value in (policy_veto_ids or ()))
    effective_veto_ids = set(veto_ids)
    if respect_decision_avoid:
        effective_veto_ids.update(
            decision.episode_id for decision in decisions if decision.avoid
        )
    cash = float(manifest.initial_cash)
    active: list[dict[str, object]] = []
    closed_trades: list[dict[str, object]] = []
    daily_pnl: dict[str, float] = {}
    equity_curve: list[dict[str, object]] = []
    sizing_events: list[dict[str, object]] = []
    turnover = 0.0
    observed_marks = 0
    stale_marks = 0
    missing_marks = 0
    invalid_marks = 0
    counters = {
        "input_opportunities": len(decisions),
        "policy_vetoes": 0,
        "duplicate_symbol_skips": 0,
        "max_position_skips": 0,
        "insufficient_cash_skips": 0,
        "trades_executed": 0,
    }
    decisions_by_entry: dict[datetime, list[ExecutableDecision]] = {}
    for decision in sorted(
        decisions,
        key=lambda item: (item.entry_time, item.symbol, item.episode_id),
    ):
        decisions_by_entry.setdefault(decision.entry_time, []).append(decision)

    def portfolio_state() -> tuple[float, float, float]:
        position_values = [
            int(position["qty"]) * float(position["mark_price"])
            for position in active
        ]
        gross_exposure = sum(position_values)
        equity = cash + gross_exposure
        concentration_pct = (
            max(position_values) / equity * 100.0
            if position_values and equity > 0
            else 0.0
        )
        return equity, gross_exposure, concentration_pct

    def observe(at: datetime, phase: str) -> None:
        equity, gross_exposure, concentration_pct = portfolio_state()
        equity_curve.append(
            {
                "observed_at": at.isoformat(),
                "phase": phase,
                "equity": equity,
                "cash": cash,
                "gross_exposure": gross_exposure,
                "gross_exposure_pct": (
                    gross_exposure / equity * 100.0 if equity > 0 else 0.0
                ),
                "concentration_pct": concentration_pct,
                "open_positions": len(active),
            }
        )

    def mark_active(at: datetime) -> str | None:
        nonlocal observed_marks, stale_marks, missing_marks, invalid_marks
        for position in active:
            entry_time = position["entry_time"]
            assert isinstance(entry_time, datetime)
            if entry_time >= at:
                continue
            resolution = context.mark_index.resolve(
                str(position["symbol"]),
                at,
                max_staleness_seconds=manifest.stale_mark_tolerance_seconds,
            )
            if resolution.status == "exact":
                observed_marks += 1
            elif resolution.status == "stale":
                observed_marks += 1
                stale_marks += 1
            elif resolution.status == "missing":
                missing_marks += 1
                invalid_marks += 1
                return "missing_active_position_mark"
            elif resolution.status == "stale_beyond_tolerance":
                stale_marks += 1
                invalid_marks += 1
                return "stale_active_position_mark_beyond_tolerance"
            else:
                invalid_marks += 1
                return "invalid_active_position_mark"
            if resolution.price is None:
                invalid_marks += 1
                return "invalid_active_position_mark"
            position["mark_price"] = float(resolution.price)
            position["mark_source_bar_time"] = (
                resolution.source_bar_time.isoformat()
                if resolution.source_bar_time is not None
                else None
            )
        return None

    def close_position(position: dict[str, object]) -> None:
        nonlocal cash, turnover
        sell_price = float(position["exit_raw_price"]) * (1.0 - slippage)
        qty = int(position["qty"])
        gross_proceeds = sell_price * qty
        sell_commission = gross_proceeds * commission_rate
        sell_tax = gross_proceeds * sell_tax_rate
        cash += gross_proceeds - sell_commission - sell_tax
        turnover += gross_proceeds
        entry_total_cost = float(position["entry_total_cost"])
        net_pnl = gross_proceeds - sell_commission - sell_tax - entry_total_cost
        net_return_pct = (
            net_pnl / entry_total_cost * 100.0 if entry_total_cost else 0.0
        )
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

    observe(manifest.future_evaluation_start, "initial")
    for current_time in context.timeline:
        mark_error = mark_active(current_time)
        if mark_error is not None:
            coverage = MarkCoverage(
                required_mark_count=context.coverage.required_mark_count,
                mark_observation_count=observed_marks,
                missing_mark_count=missing_marks,
                stale_mark_count=stale_marks,
                invalid_mark_count=invalid_marks,
                invalid_reasons=(mark_error,),
            )
            return _invalid_v2_result(
                manifest=manifest,
                cost_scenario=cost_scenario,
                result_role=result_role,
                future_interval_id=future_interval_id,
                reason=mark_error,
                coverage=coverage,
            )
        observe(current_time, "minute_mark_pre_transactions")

        due = [
            position
            for position in active
            if position["exit_time"] <= current_time
        ]
        if due:
            due_ids = {str(position["episode_id"]) for position in due}
            for position in sorted(due, key=lambda item: str(item["episode_id"])):
                close_position(position)
            active = [
                position
                for position in active
                if str(position["episode_id"]) not in due_ids
            ]

        entered = False
        for decision in decisions_by_entry.get(current_time, ()):
            should_veto = decision.episode_id in effective_veto_ids
            if should_veto:
                counters["policy_vetoes"] += 1
                continue
            if any(
                str(position["symbol"]) == decision.symbol
                for position in active
            ):
                counters["duplicate_symbol_skips"] += 1
                continue
            if len(active) >= manifest.max_open_positions:
                counters["max_position_skips"] += 1
                continue

            equity, gross_before, _ = portfolio_state()
            target_notional = max(equity * manifest.max_position_pct, 0.0)
            buy_price = float(decision.entry_price) * (1.0 + slippage)
            unit_cash_cost = buy_price * (1.0 + commission_rate)
            qty = (
                math.floor(min(target_notional, cash) / unit_cash_cost)
                if unit_cash_cost > 0
                else 0
            )
            sizing_events.append(
                {
                    "episode_id": decision.episode_id,
                    "symbol": decision.symbol,
                    "entry_time": decision.entry_time.isoformat(),
                    "mtm_equity_used": equity,
                    "gross_exposure_before": gross_before,
                    "target_notional": target_notional,
                    "qty": qty,
                }
            )
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
                    "entry_raw_price": float(decision.entry_price),
                    "entry_price": buy_price,
                    "exit_raw_price": float(decision.exit_price),
                    "entry_total_cost": entry_total_cost,
                    "qty": qty,
                    "mark_price": float(decision.entry_price),
                    "mark_source_bar_time": None,
                }
            )
            counters["trades_executed"] += 1
            entered = True
        if due or entered:
            observe(current_time, "post_transactions")

    if active:
        coverage = MarkCoverage(
            required_mark_count=context.coverage.required_mark_count,
            mark_observation_count=observed_marks,
            missing_mark_count=missing_marks,
            stale_mark_count=stale_marks,
            invalid_mark_count=invalid_marks + 1,
            invalid_reasons=("positions_remain_after_replay_timeline",),
        )
        return _invalid_v2_result(
            manifest=manifest,
            cost_scenario=cost_scenario,
            result_role=result_role,
            future_interval_id=future_interval_id,
            reason="positions_remain_after_replay_timeline",
            coverage=coverage,
        )

    equity_values = [float(item["equity"]) for item in equity_curve]
    peak_equity = equity_values[0]
    trough_equity = equity_values[0]
    max_drawdown_pct = 0.0
    for equity in equity_values:
        peak_equity = max(peak_equity, equity)
        trough_equity = min(trough_equity, equity)
        if peak_equity > 0:
            max_drawdown_pct = max(
                max_drawdown_pct,
                (peak_equity - equity) / peak_equity * 100.0,
            )

    net_pnl = cash - manifest.initial_cash
    trade_returns = [float(item["net_return_pct"]) for item in closed_trades]
    day_values = list(daily_pnl.values())
    max_gross_exposure_pct = max(
        (float(item["gross_exposure_pct"]) for item in equity_curve),
        default=0.0,
    )
    max_concentration_pct = max(
        (float(item["concentration_pct"]) for item in equity_curve),
        default=0.0,
    )
    return {
        "status": "ok",
        "evaluator_version": manifest.evaluator_version,
        "valuation_method": manifest.valuation_method,
        "mark_price_basis": manifest.mark_price_basis,
        "bar_timestamp_semantics": manifest.bar_timestamp_semantics,
        "manifest_version": manifest.manifest_version,
        "manifest_hash": manifest.sha256,
        "result_role": result_role,
        "future_interval_id": future_interval_id,
        "return_basis": "cash_and_minute_mtm_position_constrained_account_equity",
        "execution_price_basis": "next_minute_open_after_completed_signal",
        "initial_cash": float(manifest.initial_cash),
        "final_equity": cash,
        "net_pnl": net_pnl,
        "portfolio_return_pct": net_pnl / manifest.initial_cash * 100.0,
        "peak_equity": max(equity_values),
        "trough_equity": trough_equity,
        "max_drawdown_pct": max_drawdown_pct,
        "turnover_pct": turnover / manifest.initial_cash * 100.0,
        "max_gross_exposure_pct": max_gross_exposure_pct,
        "max_concentration_pct": max_concentration_pct,
        "average_trade_net_return_pct": (
            mean(trade_returns) if trade_returns else 0.0
        ),
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
        "equity_curve": equity_curve,
        "equity_observation_count": len(equity_curve),
        "position_sizing_events": sizing_events,
        "mark_observation_count": observed_marks,
        "missing_mark_count": missing_marks,
        "stale_mark_count": stale_marks,
        "invalid_mark_count": invalid_marks,
        "invalid_evaluation_reason": None,
        "cost_model": cost_model,
        "constraints": constraints,
        "counters": counters,
        "lineage": {
            "decision_fingerprint": context.decision_fingerprint,
            "policy_veto_ids_hash": _stable_id_hash(effective_veto_ids),
            "policy_veto_count": len(effective_veto_ids),
            "source_bar_count": context.mark_index.source_bar_count,
            "required_mark_count": context.coverage.required_mark_count,
            "precomputed_mark_observation_count": (
                context.coverage.mark_observation_count
            ),
        },
        "limitations": [
            "minute-open execution proxy, not tick-level bid/ask queue replay",
            "partial fills and order rejection latency are not modeled",
            "MTM uses only the prior completed minute close available at the boundary",
        ],
    }



def portfolio_random_control_v2(
    decisions: Sequence[ExecutableDecision],
    *,
    actual_policy_result: Mapping[str, object],
    actual_policy_veto_ids: Iterable[str],
    context: PortfolioReplayV2Context,
    manifest: PortfolioReplayManifest,
    cost_scenario: str,
    future_interval_id: str,
    stratum_key: Callable[[ExecutableDecision], tuple[str, ...]] | None = None,
) -> dict[str, object]:
    """Run deterministic same-count random vetoes on one shared MTM context."""

    _validate_v2_manifest(manifest)
    expected_cost_model, constraints = _v2_metadata(
        manifest,
        cost_scenario=cost_scenario,
    )
    if actual_policy_result.get("status") != "ok":
        raise ReplayCompatibilityError("actual policy result must be valid")
    if replay_result_evaluator_version(actual_policy_result) != manifest.evaluator_version:
        raise ReplayCompatibilityError("actual policy evaluator mismatch")
    if actual_policy_result.get("manifest_hash") != manifest.sha256:
        raise ReplayCompatibilityError("actual policy manifest mismatch")
    if actual_policy_result.get("future_interval_id") != future_interval_id:
        raise ReplayCompatibilityError("actual policy future interval mismatch")
    if actual_policy_result.get("cost_model") != expected_cost_model:
        raise ReplayCompatibilityError("actual policy cost scenario mismatch")
    if actual_policy_result.get("constraints") != constraints:
        raise ReplayCompatibilityError("actual policy portfolio constraints mismatch")
    if context.manifest_hash != manifest.sha256:
        raise ReplayCompatibilityError("random control context manifest mismatch")
    if context.decision_fingerprint != _decision_fingerprint(decisions):
        raise ReplayCompatibilityError("random control decision population mismatch")

    episode_ids = [str(decision.episode_id) for decision in decisions]
    if len(episode_ids) != len(set(episode_ids)):
        raise ReplayCompatibilityError("duplicate episode ids in random population")
    veto_ids = set(str(value) for value in actual_policy_veto_ids)
    actual_lineage = dict(actual_policy_result.get("lineage") or {})
    if actual_lineage.get("policy_veto_ids_hash") != _stable_id_hash(veto_ids):
        raise ReplayCompatibilityError(
            "actual policy veto lineage does not match random-control veto ids"
        )
    if actual_lineage.get("policy_veto_count") != len(veto_ids):
        raise ReplayCompatibilityError(
            "actual policy veto count does not match random-control veto ids"
        )
    unknown_veto_ids = veto_ids.difference(episode_ids)
    if unknown_veto_ids:
        raise ReplayCompatibilityError("policy veto ids missing from random population")

    key_fn = stratum_key or (lambda _decision: ("all",))
    strata: dict[tuple[str, ...], list[str]] = {}
    veto_count_by_stratum: dict[tuple[str, ...], int] = {}
    assignment_rows: list[str] = []
    for decision in sorted(
        decisions,
        key=lambda item: (item.entry_time, item.symbol, item.episode_id),
    ):
        key = tuple(str(value) for value in key_fn(decision))
        if not key:
            raise ReplayCompatibilityError("random-control stratum key cannot be empty")
        strata.setdefault(key, []).append(decision.episode_id)
        if decision.episode_id in veto_ids:
            veto_count_by_stratum[key] = veto_count_by_stratum.get(key, 0) + 1
        assignment_rows.append(f"{decision.episode_id}|{'|'.join(key)}")

    simulations = int(manifest.random_control_simulations)
    if (
        not decisions
        or not veto_ids
        or len(veto_ids) >= len(decisions)
        or simulations <= 0
    ):
        return {
            "status": "insufficient_control_sample",
            "evaluator_version": manifest.evaluator_version,
            "manifest_hash": manifest.sha256,
            "manifest_version": manifest.manifest_version,
            "result_role": "random_control",
            "future_interval_id": future_interval_id,
            "cost_model": expected_cost_model,
            "constraints": constraints,
            "population_episodes": len(decisions),
            "veto_count": len(veto_ids),
            "simulations": simulations,
            "seed": manifest.random_seed,
            "passed": False,
        }

    rng = random.Random(manifest.random_seed)
    random_returns: list[float] = []
    replay_hash_rows: list[str] = []
    for simulation_index in range(simulations):
        sampled_veto_ids: set[str] = set()
        for key in sorted(strata):
            population = sorted(strata[key])
            count = veto_count_by_stratum.get(key, 0)
            if count > len(population):
                raise ReplayCompatibilityError(
                    "random-control veto count exceeds stratum population"
                )
            if count:
                sampled_veto_ids.update(rng.sample(population, count))
        result = replay_long_only_v2(
            decisions,
            context=context,
            manifest=manifest,
            cost_scenario=cost_scenario,
            policy_veto_ids=sampled_veto_ids,
            respect_decision_avoid=False,
            result_role="random_control_simulation",
            future_interval_id=future_interval_id,
        )
        if result.get("status") != "ok":
            raise ReplayCompatibilityError(
                "invalid simulation result cannot enter random control"
            )
        if result.get("manifest_hash") != manifest.sha256:
            raise ReplayCompatibilityError("random simulation manifest drift")
        value = float(result["portfolio_return_pct"])
        random_returns.append(value)
        replay_hash_rows.append(
            f"{simulation_index}:{_stable_id_hash(sampled_veto_ids)}:{value:.12f}"
        )

    actual_return = float(actual_policy_result["portfolio_return_pct"])
    expected = mean(random_returns)
    standard_deviation = pstdev(random_returns)
    p05 = _percentile(random_returns, 0.05)
    p95 = _percentile(random_returns, 0.95)
    empirical_percentile = (
        sum(1 for value in random_returns if value <= actual_return)
        / len(random_returns)
    )
    z_score = (
        (actual_return - expected) / standard_deviation
        if standard_deviation > 0
        else 0.0
    )
    if actual_return > p95:
        verdict = "policy_better_than_random_p95"
    elif actual_return < p05:
        verdict = "policy_worse_than_random_p05"
    else:
        verdict = "policy_within_random_band"
    return {
        "status": "ok",
        "evaluator_version": manifest.evaluator_version,
        "valuation_method": manifest.valuation_method,
        "mark_price_basis": manifest.mark_price_basis,
        "bar_timestamp_semantics": manifest.bar_timestamp_semantics,
        "manifest_hash": manifest.sha256,
        "manifest_version": manifest.manifest_version,
        "result_role": "random_control",
        "future_interval_id": future_interval_id,
        "cost_model": expected_cost_model,
        "constraints": constraints,
        "population_episodes": len(decisions),
        "veto_count": len(veto_ids),
        "veto_count_by_stratum": {
            "|".join(key): veto_count_by_stratum.get(key, 0)
            for key in sorted(strata)
        },
        "stratum_assignment_hash": _stable_id_hash(assignment_rows),
        "simulations": simulations,
        "seed": manifest.random_seed,
        "actual_policy_return_pct": actual_return,
        "expected_random_policy_return_pct": expected,
        "random_return_std_pct": standard_deviation,
        "random_p05_pct": p05,
        "random_p95_pct": p95,
        "empirical_percentile": empirical_percentile,
        "z_score": z_score,
        "verdict": verdict,
        "passed": verdict == "policy_better_than_random_p95",
        "simulation_returns_hash": _stable_id_hash(replay_hash_rows),
        "shared_precomputed_mark_context": True,
        "random_control_strata": list(manifest.random_control_strata),
    }
