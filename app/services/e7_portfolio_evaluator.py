"""Immutable E7 portfolio evaluator identity and comparison guards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
import hashlib
import json
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from app.paper_trading.costs import DOMESTIC_STOCK_COST_MODEL_VERSION
from app.services.portfolio_replay import ExecutableDecision, ReplayBar
from app.services.portfolio_replay_v2 import (
    PORTFOLIO_REPLAY_V2_BAR_TIMESTAMP_SEMANTICS,
    PORTFOLIO_REPLAY_V2_MARK_PRICE_BASIS,
    PORTFOLIO_REPLAY_V2_VALUATION_METHOD,
    PORTFOLIO_REPLAY_V2_VERSION,
    PortfolioReplayManifest,
    PortfolioReplayV2Context,
    ReplayCompatibilityError,
    assert_replay_results_compatible,
    build_v2_replay_context,
    portfolio_random_control_v2,
    replay_long_only_v2,
)


KST = ZoneInfo("Asia/Seoul")
E7_FUTURE_INTERVAL_IDS = ("future_interval_1", "future_interval_2")
E7_OFFICIAL_RESULT_ROLES = (
    "baseline",
    "e7_policy",
    "actual_portfolio_replay",
    "random_control",
)
E7_COST_SCENARIOS = ("normal", "double")
E7_RANDOM_TIME_BUCKETS = (
    "open_0830_1000",
    "morning_1000_1130",
    "midday_1130_1300",
    "afternoon_1300_1430",
    "close_1430_1530",
)


E7_PORTFOLIO_REPLAY_MANIFEST = PortfolioReplayManifest(
    manifest_version="e7-portfolio-evaluator-manifest-v1",
    evaluator_version=PORTFOLIO_REPLAY_V2_VERSION,
    valuation_method=PORTFOLIO_REPLAY_V2_VALUATION_METHOD,
    mark_price_basis=PORTFOLIO_REPLAY_V2_MARK_PRICE_BASIS,
    bar_timestamp_semantics=PORTFOLIO_REPLAY_V2_BAR_TIMESTAMP_SEMANTICS,
    stale_mark_tolerance_seconds=0,
    cost_model_version=DOMESTIC_STOCK_COST_MODEL_VERSION,
    model_version="lightgbm-h15-v1",
    threshold=0.55,
    horizon_min=15,
    future_evaluation_start=datetime(2026, 8, 31, 9, 15, tzinfo=KST),
    forced_flat_time=time(15, 20),
    initial_cash=25_000_000.0,
    slippage_bps_per_side=3.0,
    commission_rate_per_side=0.00015,
    sell_tax_rate=0.002,
    cost_sensitivity_multiplier=2.0,
    max_position_pct=0.08,
    max_open_positions=5,
    random_control_simulations=1_000,
    random_seed=202608310915,
    random_control_strata=("trade_date", "symbol", "time_bucket"),
    random_control_time_buckets=E7_RANDOM_TIME_BUCKETS,
    minimum_trading_days=10,
    minimum_episodes=100,
    minimum_symbols=5,
    future_interval_count=2,
    future_interval_rule=(
        "two chronological non-overlapping intervals whose boundaries are "
        "fixed before official evaluation"
    ),
    normal_cost_rule="canonical rates unchanged; round trip assumption 0.29 pct",
    double_cost_rule="all canonical cost components multiplied by 2; 0.58 pct",
)


@dataclass(frozen=True, slots=True)
class E7FutureInterval:
    interval_id: str
    start: datetime
    end: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "interval_id": self.interval_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }

    @property
    def sha256(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def validate_e7_future_intervals(
    intervals: Sequence[E7FutureInterval],
) -> tuple[E7FutureInterval, E7FutureInterval]:
    if len(intervals) != E7_PORTFOLIO_REPLAY_MANIFEST.future_interval_count:
        raise ReplayCompatibilityError("E7 requires exactly two future intervals")
    by_id = {item.interval_id: item for item in intervals}
    if set(by_id) != set(E7_FUTURE_INTERVAL_IDS):
        raise ReplayCompatibilityError("E7 future interval ids are incomplete")
    ordered = tuple(sorted(intervals, key=lambda item: item.start))
    for interval in ordered:
        if interval.start.tzinfo is None or interval.end.tzinfo is None:
            raise ReplayCompatibilityError("E7 interval boundaries must be timezone-aware")
        if interval.start < E7_PORTFOLIO_REPLAY_MANIFEST.future_evaluation_start:
            raise ReplayCompatibilityError("E7 interval starts before preregistered future data")
        if interval.end <= interval.start:
            raise ReplayCompatibilityError("E7 interval has a nonpositive duration")
    if ordered[0].end > ordered[1].start:
        raise ReplayCompatibilityError("E7 future intervals overlap")
    return ordered[0], ordered[1]


def e7_random_control_stratum(
    decision: ExecutableDecision,
) -> tuple[str, str, str]:
    local_time = decision.entry_time.astimezone(KST)
    clock = local_time.time()
    if clock < time(10, 0):
        bucket = "open_0830_1000"
    elif clock < time(11, 30):
        bucket = "morning_1000_1130"
    elif clock < time(13, 0):
        bucket = "midday_1130_1300"
    elif clock < time(14, 30):
        bucket = "afternoon_1300_1430"
    else:
        bucket = "close_1430_1530"
    return local_time.date().isoformat(), decision.symbol, bucket



def _validate_one_e7_future_interval(
    future_interval: E7FutureInterval,
) -> None:
    if future_interval.interval_id not in E7_FUTURE_INTERVAL_IDS:
        raise ReplayCompatibilityError("unsupported E7 future interval id")
    if future_interval.start.tzinfo is None or future_interval.end.tzinfo is None:
        raise ReplayCompatibilityError("E7 interval boundaries must be timezone-aware")
    if future_interval.start < E7_PORTFOLIO_REPLAY_MANIFEST.future_evaluation_start:
        raise ReplayCompatibilityError("E7 interval starts before preregistered future data")
    if future_interval.end <= future_interval.start:
        raise ReplayCompatibilityError("E7 interval has a nonpositive duration")


def build_e7_interval_context(
    decisions: Sequence[ExecutableDecision],
    bars_by_symbol: Mapping[str, Sequence[ReplayBar]],
    *,
    future_interval: E7FutureInterval,
) -> PortfolioReplayV2Context:
    """Validate one fixed future population and precompute marks once."""

    _validate_one_e7_future_interval(future_interval)
    if any(
        decision.signal_time < future_interval.start
        or decision.signal_time >= future_interval.end
        for decision in decisions
    ):
        raise ReplayCompatibilityError(
            "decision population falls outside the fixed E7 future interval"
        )
    return build_v2_replay_context(
        decisions,
        bars_by_symbol,
        manifest=E7_PORTFOLIO_REPLAY_MANIFEST,
    )


def run_e7_portfolio_replay(
    decisions: Sequence[ExecutableDecision],
    *,
    context: PortfolioReplayV2Context,
    future_interval: E7FutureInterval,
    result_role: str,
    cost_scenario: str,
    policy_veto_ids: Sequence[str] = (),
    respect_decision_avoid: bool,
) -> dict[str, object]:
    """Run one official non-random role without changing policy inputs."""

    if result_role not in {
        "baseline",
        "e7_policy",
        "actual_portfolio_replay",
    }:
        raise ReplayCompatibilityError("unsupported E7 portfolio replay role")
    _validate_one_e7_future_interval(future_interval)
    result = replay_long_only_v2(
        decisions,
        context=context,
        manifest=E7_PORTFOLIO_REPLAY_MANIFEST,
        cost_scenario=cost_scenario,
        policy_veto_ids=policy_veto_ids,
        respect_decision_avoid=respect_decision_avoid,
        result_role=result_role,
        future_interval_id=future_interval.interval_id,
    )
    return stamp_e7_result(
        result,
        result_role=result_role,
        future_interval=future_interval,
    )


def run_e7_random_control(
    decisions: Sequence[ExecutableDecision],
    *,
    actual_policy_result: Mapping[str, object],
    actual_policy_veto_ids: Sequence[str],
    context: PortfolioReplayV2Context,
    future_interval: E7FutureInterval,
    cost_scenario: str,
) -> dict[str, object]:
    """Run the fixed 1,000-simulation E7 control on the shared context."""

    _validate_one_e7_future_interval(future_interval)
    result = portfolio_random_control_v2(
        decisions,
        actual_policy_result=actual_policy_result,
        actual_policy_veto_ids=actual_policy_veto_ids,
        context=context,
        manifest=E7_PORTFOLIO_REPLAY_MANIFEST,
        cost_scenario=cost_scenario,
        future_interval_id=future_interval.interval_id,
        stratum_key=e7_random_control_stratum,
    )
    return stamp_e7_result(
        result,
        result_role="random_control",
        future_interval=future_interval,
    )

def stamp_e7_result(
    result: Mapping[str, object],
    *,
    result_role: str,
    future_interval: E7FutureInterval,
) -> dict[str, object]:
    if result_role not in E7_OFFICIAL_RESULT_ROLES:
        raise ReplayCompatibilityError("unsupported E7 official result role")
    if future_interval.interval_id not in E7_FUTURE_INTERVAL_IDS:
        raise ReplayCompatibilityError("unsupported E7 future interval id")
    if result.get("manifest_hash") != E7_PORTFOLIO_REPLAY_MANIFEST.sha256:
        raise ReplayCompatibilityError("cannot stamp a non-E7 manifest result")
    if result.get("future_interval_id") != future_interval.interval_id:
        raise ReplayCompatibilityError("result and E7 interval id mismatch")
    stamped = dict(result)
    stamped.update(
        {
            "result_role": result_role,
            "future_interval_definition": future_interval.to_dict(),
            "future_interval_definition_hash": future_interval.sha256,
        }
    )
    return stamped


def validate_e7_official_result_set(
    results: Sequence[Mapping[str, object]],
    *,
    future_intervals: Sequence[E7FutureInterval],
) -> dict[str, object]:
    """Fail closed unless every official comparison has one exact identity."""

    ordered_intervals = validate_e7_future_intervals(future_intervals)
    intervals_by_id = {item.interval_id: item for item in ordered_intervals}
    expected_keys = {
        (interval_id, cost_scenario, role)
        for interval_id in E7_FUTURE_INTERVAL_IDS
        for cost_scenario in E7_COST_SCENARIOS
        for role in E7_OFFICIAL_RESULT_ROLES
    }
    actual: dict[tuple[str, str, str], Mapping[str, object]] = {}
    for result in results:
        if result.get("status") != "ok":
            raise ReplayCompatibilityError(
                "invalid result cannot enter the official E7 package"
            )
        if result.get("evaluator_version") != PORTFOLIO_REPLAY_V2_VERSION:
            raise ReplayCompatibilityError("official E7 evaluator version mismatch")
        if result.get("manifest_hash") != E7_PORTFOLIO_REPLAY_MANIFEST.sha256:
            raise ReplayCompatibilityError("official E7 manifest mismatch")
        interval_id = str(result.get("future_interval_id") or "")
        role = str(result.get("result_role") or "")
        cost_model = dict(result.get("cost_model") or {})
        cost_scenario = str(cost_model.get("scenario") or "")
        key = (interval_id, cost_scenario, role)
        if key in actual:
            raise ReplayCompatibilityError("duplicate official E7 result identity")
        if key not in expected_keys:
            raise ReplayCompatibilityError("unexpected official E7 result identity")
        interval = intervals_by_id[interval_id]
        if result.get("future_interval_definition_hash") != interval.sha256:
            raise ReplayCompatibilityError("official E7 interval definition mismatch")
        expected_cost = E7_PORTFOLIO_REPLAY_MANIFEST.cost_parameters(cost_scenario)
        expected_cost_model = {
            "version": DOMESTIC_STOCK_COST_MODEL_VERSION,
            "scope": "ordinary_kospi_kosdaq_shares_2026",
            **expected_cost,
        }
        if cost_model != expected_cost_model:
            raise ReplayCompatibilityError("official E7 cost assumptions mismatch")
        expected_constraints = {
            "initial_cash": float(E7_PORTFOLIO_REPLAY_MANIFEST.initial_cash),
            "max_position_pct": float(
                E7_PORTFOLIO_REPLAY_MANIFEST.max_position_pct
            ),
            "max_open_positions": int(
                E7_PORTFOLIO_REPLAY_MANIFEST.max_open_positions
            ),
            "duplicate_symbol_positions": "blocked",
            "fractional_shares": "blocked",
            "forced_flat_time": (
                E7_PORTFOLIO_REPLAY_MANIFEST.forced_flat_time.isoformat(
                    timespec="minutes"
                )
            ),
        }
        if result.get("constraints") != expected_constraints:
            raise ReplayCompatibilityError(
                "official E7 portfolio constraints mismatch"
            )
        if (
            result.get("valuation_method")
            != E7_PORTFOLIO_REPLAY_MANIFEST.valuation_method
            or result.get("mark_price_basis")
            != E7_PORTFOLIO_REPLAY_MANIFEST.mark_price_basis
            or result.get("bar_timestamp_semantics")
            != E7_PORTFOLIO_REPLAY_MANIFEST.bar_timestamp_semantics
        ):
            raise ReplayCompatibilityError("official E7 valuation identity mismatch")
        if role == "random_control":
            if (
                result.get("simulations")
                != E7_PORTFOLIO_REPLAY_MANIFEST.random_control_simulations
                or result.get("seed")
                != E7_PORTFOLIO_REPLAY_MANIFEST.random_seed
                or result.get("random_control_strata")
                != list(E7_PORTFOLIO_REPLAY_MANIFEST.random_control_strata)
            ):
                raise ReplayCompatibilityError(
                    "official E7 random-control configuration mismatch"
                )
        actual[key] = result

    missing = expected_keys.difference(actual)
    extra = set(actual).difference(expected_keys)
    if missing or extra:
        raise ReplayCompatibilityError(
            "official E7 result package is incomplete or contains extras"
        )

    for interval_id in E7_FUTURE_INTERVAL_IDS:
        for cost_scenario in E7_COST_SCENARIOS:
            group = [
                actual[(interval_id, cost_scenario, role)]
                for role in E7_OFFICIAL_RESULT_ROLES
            ]
            assert_replay_results_compatible(group)
    assert_replay_results_compatible(
        list(actual.values()),
        allow_cost_scenario_difference=True,
    )
    package_rows = [
        "|".join(key) + ":" + str(actual[key].get("manifest_hash"))
        for key in sorted(actual)
    ]
    return {
        "status": "compatible",
        "passed": True,
        "manifest_hash": E7_PORTFOLIO_REPLAY_MANIFEST.sha256,
        "evaluator_version": PORTFOLIO_REPLAY_V2_VERSION,
        "result_count": len(actual),
        "package_identity_hash": hashlib.sha256(
            "\n".join(package_rows).encode("utf-8")
        ).hexdigest(),
    }
