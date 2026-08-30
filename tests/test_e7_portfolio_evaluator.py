from datetime import datetime, timedelta
import unittest

from app.services.e7_portfolio_evaluator import (
    E7_COST_SCENARIOS,
    E7_FUTURE_INTERVAL_IDS,
    E7_OFFICIAL_RESULT_ROLES,
    E7_PORTFOLIO_REPLAY_MANIFEST,
    E7FutureInterval,
    build_e7_interval_context,
    run_e7_portfolio_replay,
    stamp_e7_result,
    validate_e7_future_intervals,
    validate_e7_official_result_set,
)
from app.services.portfolio_replay import ExecutableDecision, ReplayBar
from app.services.portfolio_replay_v2 import ReplayCompatibilityError


def _intervals() -> tuple[E7FutureInterval, E7FutureInterval]:
    start = E7_PORTFOLIO_REPLAY_MANIFEST.future_evaluation_start
    return (
        E7FutureInterval(
            "future_interval_1",
            start,
            start + timedelta(days=14),
        ),
        E7FutureInterval(
            "future_interval_2",
            start + timedelta(days=14),
            start + timedelta(days=28),
        ),
    )


def _constraints() -> dict[str, object]:
    manifest = E7_PORTFOLIO_REPLAY_MANIFEST
    return {
        "initial_cash": float(manifest.initial_cash),
        "max_position_pct": float(manifest.max_position_pct),
        "max_open_positions": int(manifest.max_open_positions),
        "duplicate_symbol_positions": "blocked",
        "fractional_shares": "blocked",
        "forced_flat_time": manifest.forced_flat_time.isoformat(timespec="minutes"),
    }


def _fake_result(
    role: str,
    interval: E7FutureInterval,
    scenario: str,
) -> dict[str, object]:
    manifest = E7_PORTFOLIO_REPLAY_MANIFEST
    result = {
        "status": "ok",
        "evaluator_version": manifest.evaluator_version,
        "valuation_method": manifest.valuation_method,
        "mark_price_basis": manifest.mark_price_basis,
        "bar_timestamp_semantics": manifest.bar_timestamp_semantics,
        "manifest_hash": manifest.sha256,
        "manifest_version": manifest.manifest_version,
        "result_role": role,
        "future_interval_id": interval.interval_id,
        "portfolio_return_pct": 0.1,
        "cost_model": {
            "version": manifest.cost_model_version,
            "scope": "ordinary_kospi_kosdaq_shares_2026",
            **manifest.cost_parameters(scenario),
        },
        "constraints": _constraints(),
    }
    if role == "random_control":
        result.update(
            {
                "simulations": manifest.random_control_simulations,
                "seed": manifest.random_seed,
                "random_control_strata": list(manifest.random_control_strata),
            }
        )
    return stamp_e7_result(
        result,
        result_role=role,
        future_interval=interval,
    )


def _complete_package() -> list[dict[str, object]]:
    return [
        _fake_result(role, interval, scenario)
        for interval in _intervals()
        for scenario in E7_COST_SCENARIOS
        for role in E7_OFFICIAL_RESULT_ROLES
    ]


class E7PortfolioEvaluatorTests(unittest.TestCase):
    def test_manifest_locks_preregistered_e7_identity(self) -> None:
        manifest = E7_PORTFOLIO_REPLAY_MANIFEST

        self.assertEqual(manifest.evaluator_version, "portfolio-replay-v2-minute-mtm")
        self.assertEqual(manifest.model_version, "lightgbm-h15-v1")
        self.assertEqual(manifest.threshold, 0.55)
        self.assertEqual(manifest.horizon_min, 15)
        self.assertEqual(
            manifest.future_evaluation_start.isoformat(),
            "2026-08-31T09:15:00+09:00",
        )
        self.assertEqual(manifest.forced_flat_time.isoformat(), "15:20:00")
        self.assertEqual(manifest.initial_cash, 25_000_000.0)
        self.assertEqual(manifest.max_position_pct, 0.08)
        self.assertEqual(manifest.max_open_positions, 5)
        self.assertEqual(manifest.random_control_simulations, 1_000)
        self.assertEqual(manifest.minimum_trading_days, 10)
        self.assertEqual(manifest.minimum_episodes, 100)
        self.assertEqual(manifest.minimum_symbols, 5)
        self.assertEqual(manifest.future_interval_count, 2)
        self.assertEqual(manifest.cost_parameters("normal")["slippage_bps_per_side"], 3.0)
        self.assertEqual(manifest.cost_parameters("double")["slippage_bps_per_side"], 6.0)

    def test_two_future_intervals_must_be_nonoverlapping_and_future(self) -> None:
        first, second = _intervals()
        self.assertEqual(
            validate_e7_future_intervals((first, second)),
            (first, second),
        )

        overlap = E7FutureInterval(
            "future_interval_2",
            first.end - timedelta(seconds=1),
            second.end,
        )
        with self.assertRaises(ReplayCompatibilityError):
            validate_e7_future_intervals((first, overlap))

        before = E7FutureInterval(
            "future_interval_1",
            E7_PORTFOLIO_REPLAY_MANIFEST.future_evaluation_start
            - timedelta(minutes=1),
            first.end,
        )
        with self.assertRaises(ReplayCompatibilityError):
            validate_e7_future_intervals((before, second))

    def test_complete_official_package_is_compatible(self) -> None:
        result = validate_e7_official_result_set(
            _complete_package(),
            future_intervals=_intervals(),
        )

        self.assertEqual(result["status"], "compatible")
        self.assertTrue(result["passed"])
        self.assertEqual(result["result_count"], 16)
        self.assertEqual(
            result["manifest_hash"],
            E7_PORTFOLIO_REPLAY_MANIFEST.sha256,
        )

    def test_missing_role_or_mixed_identity_fails_closed(self) -> None:
        package = _complete_package()
        with self.assertRaises(ReplayCompatibilityError):
            validate_e7_official_result_set(
                package[:-1],
                future_intervals=_intervals(),
            )

        drifted = [dict(item) for item in package]
        drifted[0]["manifest_hash"] = "v1-or-other-manifest"
        with self.assertRaises(ReplayCompatibilityError):
            validate_e7_official_result_set(
                drifted,
                future_intervals=_intervals(),
            )

    def test_cost_constraints_interval_and_random_config_drift_fail(self) -> None:
        mutations = []

        cost = [dict(item) for item in _complete_package()]
        cost[0] = dict(cost[0])
        cost[0]["cost_model"] = dict(cost[0]["cost_model"])
        cost[0]["cost_model"]["sell_tax_rate"] = 0.0
        mutations.append(cost)

        constraints = [dict(item) for item in _complete_package()]
        constraints[0] = dict(constraints[0])
        constraints[0]["constraints"] = dict(constraints[0]["constraints"])
        constraints[0]["constraints"]["max_open_positions"] = 4
        mutations.append(constraints)

        interval = [dict(item) for item in _complete_package()]
        interval[0] = dict(interval[0])
        interval[0]["future_interval_definition_hash"] = "different"
        mutations.append(interval)

        random_config = [dict(item) for item in _complete_package()]
        index = next(
            idx
            for idx, item in enumerate(random_config)
            if item["result_role"] == "random_control"
        )
        random_config[index] = dict(random_config[index])
        random_config[index]["simulations"] = 999
        mutations.append(random_config)

        for package in mutations:
            with self.subTest():
                with self.assertRaises(ReplayCompatibilityError):
                    validate_e7_official_result_set(
                        package,
                        future_intervals=_intervals(),
                    )


    def test_official_wrapper_locks_interval_context_and_result_stamp(self) -> None:
        future_interval = _intervals()[0]
        start = E7_PORTFOLIO_REPLAY_MANIFEST.future_evaluation_start
        entry = start + timedelta(minutes=1)
        exit_at = start + timedelta(minutes=3)
        decisions = [
            ExecutableDecision(
                episode_id="A-1",
                symbol="A",
                signal_time=start,
                entry_time=entry,
                entry_price=100.0,
                exit_time=exit_at,
                exit_price=101.0,
                signal_rows=1,
                avoid=False,
            )
        ]
        bars = {
            "A": [
                ReplayBar(
                    "A",
                    entry + timedelta(minutes=index),
                    100.0,
                    100.0,
                )
                for index in range(3)
            ]
        }
        context = build_e7_interval_context(
            decisions,
            bars,
            future_interval=future_interval,
        )

        result = run_e7_portfolio_replay(
            decisions,
            context=context,
            future_interval=future_interval,
            result_role="baseline",
            cost_scenario="normal",
            respect_decision_avoid=False,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result_role"], "baseline")
        self.assertEqual(
            result["future_interval_definition_hash"],
            future_interval.sha256,
        )
        self.assertEqual(
            result["manifest_hash"],
            E7_PORTFOLIO_REPLAY_MANIFEST.sha256,
        )

        outside = [
            ExecutableDecision(
                episode_id="outside",
                symbol="A",
                signal_time=start - timedelta(seconds=1),
                entry_time=entry,
                entry_price=100.0,
                exit_time=exit_at,
                exit_price=101.0,
                signal_rows=1,
                avoid=False,
            )
        ]
        with self.assertRaises(ReplayCompatibilityError):
            build_e7_interval_context(
                outside,
                bars,
                future_interval=future_interval,
            )



if __name__ == "__main__":
    unittest.main()
