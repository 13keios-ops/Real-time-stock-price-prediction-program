from dataclasses import replace
from datetime import datetime, time, timedelta
import unittest

from app.services.e7_portfolio_evaluator import (
    E7_PORTFOLIO_REPLAY_MANIFEST,
    e7_random_control_stratum,
)
from app.services.portfolio_replay import (
    ExecutableDecision,
    ReplayBar,
    replay_long_only,
)
from app.services.portfolio_replay_v2 import (
    PORTFOLIO_REPLAY_V1_VERSION,
    ReplayCompatibilityError,
    assert_replay_results_compatible,
    build_v2_replay_context,
    portfolio_random_control_v2,
    replay_long_only_v1,
    replay_long_only_v2,
    replay_result_evaluator_version,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _manifest(
    start: datetime,
    *,
    initial_cash: float = 1_000.0,
    max_position_pct: float = 1.0,
    max_open_positions: int = 5,
    costs: bool = False,
    simulations: int = 1_000,
):
    return replace(
        E7_PORTFOLIO_REPLAY_MANIFEST,
        manifest_version="synthetic-v2-test",
        future_evaluation_start=start,
        initial_cash=initial_cash,
        max_position_pct=max_position_pct,
        max_open_positions=max_open_positions,
        slippage_bps_per_side=(
            E7_PORTFOLIO_REPLAY_MANIFEST.slippage_bps_per_side if costs else 0.0
        ),
        commission_rate_per_side=(
            E7_PORTFOLIO_REPLAY_MANIFEST.commission_rate_per_side if costs else 0.0
        ),
        sell_tax_rate=(
            E7_PORTFOLIO_REPLAY_MANIFEST.sell_tax_rate if costs else 0.0
        ),
        random_control_simulations=simulations,
        random_seed=17,
    )


def _decision(
    episode_id: str,
    symbol: str,
    entry: datetime,
    exit_at: datetime,
    *,
    entry_price: float = 100.0,
    exit_price: float = 100.0,
    avoid: bool = False,
) -> ExecutableDecision:
    return ExecutableDecision(
        episode_id=episode_id,
        symbol=symbol,
        signal_time=entry - timedelta(minutes=1),
        entry_time=entry,
        entry_price=entry_price,
        exit_time=exit_at,
        exit_price=exit_price,
        signal_rows=1,
        avoid=avoid,
    )


def _bars(
    symbol: str,
    start: datetime,
    closes: list[float],
    *,
    open_price: float = 100.0,
) -> list[ReplayBar]:
    return [
        ReplayBar(
            symbol=symbol,
            bar_time=start + timedelta(minutes=index),
            open_price=open_price,
            close_price=close,
        )
        for index, close in enumerate(closes)
    ]


def _pre_equity(result: dict[str, object], at: datetime) -> float:
    for row in result["equity_curve"]:
        if (
            row["observed_at"] == at.isoformat()
            and row["phase"] == "minute_mark_pre_transactions"
        ):
            return float(row["equity"])
    raise AssertionError(f"missing equity observation at {at.isoformat()}")


class PortfolioReplayV2Tests(unittest.TestCase):
    def test_v1_entry_mark_result_remains_legacy_and_unchanged(self) -> None:
        decisions = [
            _decision(
                "A-1",
                "A",
                _dt("2026-08-31T09:16:00+09:00"),
                _dt("2026-08-31T09:19:00+09:00"),
                exit_price=110.0,
            )
        ]
        kwargs = {
            "initial_cash": 1_000.0,
            "max_position_pct": 1.0,
            "max_open_positions": 1,
            "slippage_bps": 0.0,
            "commission_rate": 0.0,
            "sell_tax_rate": 0.0,
        }

        original = replay_long_only(decisions, **kwargs)
        explicit_v1 = replay_long_only_v1(decisions, **kwargs)

        self.assertEqual(original, explicit_v1)
        self.assertEqual(
            replay_result_evaluator_version(original),
            PORTFOLIO_REPLAY_V1_VERSION,
        )
        self.assertNotIn("evaluator_version", original)
        self.assertNotIn("equity_curve", original)
        self.assertIn(
            "open positions are marked at entry price between exits for drawdown",
            original["limitations"],
        )

    def test_intratrade_drawdown_uses_minute_marks(self) -> None:
        start = _dt("2026-08-31T09:15:00+09:00")
        entry = start + timedelta(minutes=1)
        exit_at = start + timedelta(minutes=4)
        decisions = [
            _decision("A-1", "A", entry, exit_at, exit_price=110.0)
        ]
        bars = {"A": _bars("A", entry, [100.0, 80.0, 80.0, 110.0])}
        manifest = _manifest(start)
        context = build_v2_replay_context(decisions, bars, manifest=manifest)

        result = replay_long_only_v2(
            decisions,
            context=context,
            manifest=manifest,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(_pre_equity(result, entry + timedelta(minutes=2)), 800.0)
        self.assertEqual(result["initial_cash"], 1_000.0)
        self.assertEqual(result["trough_equity"], 800.0)
        self.assertEqual(result["peak_equity"], 1_100.0)
        self.assertAlmostEqual(result["max_drawdown_pct"], 20.0)
        self.assertEqual(result["final_equity"], 1_100.0)
        self.assertAlmostEqual(result["portfolio_return_pct"], 10.0)

        v1 = replay_long_only(
            decisions,
            initial_cash=1_000.0,
            max_position_pct=1.0,
            max_open_positions=5,
            slippage_bps=0.0,
            commission_rate=0.0,
            sell_tax_rate=0.0,
        )
        self.assertEqual(v1["max_drawdown_pct"], 0.0)
        self.assertEqual(v1["final_equity"], result["final_equity"])

    def test_gradual_path_creates_each_intratrade_observation(self) -> None:
        start = _dt("2026-08-31T09:15:00+09:00")
        entry = start + timedelta(minutes=1)
        exit_at = start + timedelta(minutes=6)
        decisions = [
            _decision("A-1", "A", entry, exit_at, exit_price=110.0)
        ]
        bars = {"A": _bars("A", entry, [95.0, 90.0, 80.0, 105.0, 109.0, 110.0])}
        manifest = _manifest(start)
        context = build_v2_replay_context(decisions, bars, manifest=manifest)

        result = replay_long_only_v2(decisions, context=context, manifest=manifest)

        observed = [
            _pre_equity(result, entry + timedelta(minutes=offset))
            for offset in range(1, 6)
        ]
        self.assertEqual(observed, [950.0, 900.0, 800.0, 1_050.0, 1_090.0])
        self.assertGreaterEqual(result["equity_observation_count"], 8)
        self.assertEqual(result["mark_observation_count"], 5)

    def test_missing_and_stale_marks_fail_closed_without_entry_fallback(self) -> None:
        start = _dt("2026-08-31T09:15:00+09:00")
        entry = start + timedelta(minutes=1)
        exit_at = start + timedelta(minutes=3)
        decisions = [_decision("A-1", "A", entry, exit_at)]

        missing_bars = {
            "A": [
                ReplayBar(
                    "A",
                    entry + timedelta(minutes=1),
                    100.0,
                    100.0,
                )
            ]
        }
        manifest = _manifest(start)
        missing_context = build_v2_replay_context(
            decisions,
            missing_bars,
            manifest=manifest,
        )
        missing = replay_long_only_v2(
            decisions,
            context=missing_context,
            manifest=manifest,
        )
        self.assertEqual(missing["status"], "invalid_evaluation")
        self.assertGreater(missing["missing_mark_count"], 0)
        self.assertEqual(missing["closed_trades"] if "closed_trades" in missing else [], [])

        stale_bars = {
            "A": [
                ReplayBar("A", entry, 100.0, 90.0),
                ReplayBar(
                    "A",
                    entry + timedelta(minutes=2),
                    100.0,
                    100.0,
                ),
            ]
        }
        stale_context = build_v2_replay_context(
            decisions,
            stale_bars,
            manifest=manifest,
        )
        stale = replay_long_only_v2(
            decisions,
            context=stale_context,
            manifest=manifest,
        )
        self.assertEqual(stale["status"], "invalid_evaluation")
        self.assertGreater(stale["stale_mark_count"], 0)
        self.assertIn(
            "stale_active_position_mark_beyond_tolerance",
            stale["invalid_evaluation_reason"],
        )

    def test_no_lookahead_and_same_minute_boundary(self) -> None:
        start = _dt("2026-08-31T09:15:00+09:00")
        entry = start + timedelta(minutes=1)
        exit_at = start + timedelta(minutes=3)
        decisions = [_decision("A-1", "A", entry, exit_at)]
        bars = {
            "A": [
                ReplayBar("A", entry, 100.0, 90.0),
                ReplayBar(
                    "A",
                    entry + timedelta(minutes=1),
                    100.0,
                    1_000.0,
                ),
                ReplayBar(
                    "A",
                    entry + timedelta(minutes=2),
                    100.0,
                    100.0,
                ),
            ]
        }
        manifest = _manifest(start)
        context = build_v2_replay_context(decisions, bars, manifest=manifest)

        result = replay_long_only_v2(decisions, context=context, manifest=manifest)

        self.assertEqual(_pre_equity(result, entry + timedelta(minutes=1)), 900.0)
        self.assertEqual(
            _pre_equity(result, entry + timedelta(minutes=2)),
            10_000.0,
        )


    def _overlap_result(self, first_mark: float) -> dict[str, object]:
        start = _dt("2026-08-31T09:15:00+09:00")
        first_entry = start + timedelta(minutes=1)
        second_entry = start + timedelta(minutes=3)
        decisions = [
            _decision(
                "A-1",
                "A",
                first_entry,
                start + timedelta(minutes=5),
            ),
            _decision(
                "B-1",
                "B",
                second_entry,
                start + timedelta(minutes=6),
            ),
        ]
        bars = {
            "A": _bars(
                "A",
                first_entry,
                [100.0, first_mark, first_mark, 100.0, 100.0],
            ),
            "B": _bars(
                "B",
                second_entry,
                [120.0, 120.0, 100.0, 100.0],
            ),
        }
        manifest = _manifest(
            start,
            initial_cash=10_000.0,
            max_position_pct=0.25,
        )
        context = build_v2_replay_context(decisions, bars, manifest=manifest)
        return replay_long_only_v2(
            decisions,
            context=context,
            manifest=manifest,
        )

    def test_overlapping_position_sizing_uses_down_and_up_mtm_equity(self) -> None:
        down = self._overlap_result(80.0)
        up = self._overlap_result(120.0)

        down_second = down["position_sizing_events"][1]
        up_second = up["position_sizing_events"][1]
        self.assertEqual(down_second["mtm_equity_used"], 9_500.0)
        self.assertEqual(down_second["target_notional"], 2_375.0)
        self.assertEqual(down_second["qty"], 23)
        self.assertEqual(up_second["mtm_equity_used"], 10_500.0)
        self.assertEqual(up_second["target_notional"], 2_625.0)
        self.assertEqual(up_second["qty"], 26)

    def test_multiple_position_marks_sum_into_equity_and_exposure(self) -> None:
        result = self._overlap_result(80.0)
        at = _dt("2026-08-31T09:19:00+09:00")

        self.assertEqual(_pre_equity(result, at), 9_960.0)
        row = next(
            row
            for row in result["equity_curve"]
            if row["observed_at"] == at.isoformat()
            and row["phase"] == "minute_mark_pre_transactions"
        )
        self.assertEqual(row["gross_exposure"], 4_760.0)
        self.assertEqual(row["open_positions"], 2)
        self.assertAlmostEqual(
            row["concentration_pct"],
            2_760.0 / 9_960.0 * 100.0,
        )

    def test_forced_flat_boundary_marks_then_exits_at_current_open(self) -> None:
        start = _dt("2026-08-31T15:17:00+09:00")
        entry = _dt("2026-08-31T15:18:00+09:00")
        exit_at = _dt("2026-08-31T15:20:00+09:00")
        decisions = [
            _decision(
                "A-1",
                "A",
                entry,
                exit_at,
                exit_price=105.0,
            )
        ]
        bars = {"A": _bars("A", entry, [90.0, 95.0, 105.0])}
        manifest = replace(
            _manifest(start),
            forced_flat_time=time(15, 20),
        )
        context = build_v2_replay_context(decisions, bars, manifest=manifest)

        result = replay_long_only_v2(decisions, context=context, manifest=manifest)

        self.assertEqual(_pre_equity(result, exit_at), 950.0)
        self.assertEqual(result["closed_trades"][0]["exit_time"], exit_at.isoformat())
        self.assertEqual(result["final_equity"], 1_050.0)
        self.assertEqual(result["equity_curve"][-1]["open_positions"], 0)

    def test_normal_costs_match_v1_and_double_cost_is_separate(self) -> None:
        start = _dt("2026-08-31T09:15:00+09:00")
        entry = start + timedelta(minutes=1)
        exit_at = start + timedelta(minutes=3)
        decisions = [
            _decision(
                "A-1",
                "A",
                entry,
                exit_at,
                exit_price=110.0,
            )
        ]
        bars = {"A": _bars("A", entry, [100.0, 100.0, 110.0])}
        manifest = _manifest(
            start,
            initial_cash=25_000_000.0,
            max_position_pct=0.08,
            costs=True,
        )
        context = build_v2_replay_context(decisions, bars, manifest=manifest)

        normal = replay_long_only_v2(
            decisions,
            context=context,
            manifest=manifest,
            cost_scenario="normal",
        )
        double = replay_long_only_v2(
            decisions,
            context=context,
            manifest=manifest,
            cost_scenario="double",
        )
        v1 = replay_long_only(
            decisions,
            initial_cash=manifest.initial_cash,
            max_position_pct=manifest.max_position_pct,
            max_open_positions=manifest.max_open_positions,
            slippage_bps=manifest.slippage_bps_per_side,
            commission_rate=manifest.commission_rate_per_side,
            sell_tax_rate=manifest.sell_tax_rate,
        )

        self.assertAlmostEqual(normal["final_equity"], v1["final_equity"])
        self.assertAlmostEqual(normal["net_pnl"], v1["net_pnl"])
        self.assertEqual(
            normal["cost_model"]["version"],
            "krx-common-stock-2026-v1",
        )
        self.assertEqual(
            normal["cost_model"]["commission_rate_per_side"],
            0.00015,
        )
        self.assertEqual(normal["cost_model"]["sell_tax_rate"], 0.002)
        self.assertEqual(normal["cost_model"]["slippage_bps_per_side"], 3.0)
        self.assertEqual(double["cost_model"]["slippage_bps_per_side"], 6.0)
        self.assertEqual(double["cost_model"]["commission_rate_per_side"], 0.0003)
        self.assertEqual(double["cost_model"]["sell_tax_rate"], 0.004)
        self.assertLess(double["final_equity"], normal["final_equity"])

    def test_evaluator_and_manifest_mixing_is_rejected(self) -> None:
        start = _dt("2026-08-31T09:15:00+09:00")
        entry = start + timedelta(minutes=1)
        exit_at = start + timedelta(minutes=3)
        decisions = [_decision("A-1", "A", entry, exit_at)]
        bars = {"A": _bars("A", entry, [100.0, 100.0, 100.0])}
        manifest = _manifest(start)
        context = build_v2_replay_context(decisions, bars, manifest=manifest)
        v2 = replay_long_only_v2(decisions, context=context, manifest=manifest)
        v1 = replay_long_only(
            decisions,
            initial_cash=1_000.0,
            max_position_pct=1.0,
            max_open_positions=5,
            slippage_bps=0.0,
            commission_rate=0.0,
            sell_tax_rate=0.0,
        )

        with self.assertRaises(ReplayCompatibilityError):
            assert_replay_results_compatible([v1, v2])

        drifted = dict(v2)
        drifted["manifest_hash"] = "different"
        with self.assertRaises(ReplayCompatibilityError):
            assert_replay_results_compatible([v2, drifted])

    def test_random_control_runs_1000_deterministic_v2_replays(self) -> None:
        start = _dt("2026-08-31T09:15:00+09:00")
        decisions = []
        for index in range(10):
            entry = start + timedelta(minutes=1 + index * 3)
            decisions.append(
                _decision(
                    f"A-{index}",
                    "A",
                    entry,
                    entry + timedelta(minutes=2),
                    exit_price=98.0 if index < 3 else 101.0,
                )
            )
        bars = {"A": _bars("A", start + timedelta(minutes=1), [100.0] * 30)}
        manifest = _manifest(
            start,
            initial_cash=100_000.0,
            max_position_pct=0.1,
            simulations=1_000,
        )
        context = build_v2_replay_context(decisions, bars, manifest=manifest)
        veto_ids = {"A-0", "A-1"}
        actual = replay_long_only_v2(
            decisions,
            context=context,
            manifest=manifest,
            policy_veto_ids=veto_ids,
            respect_decision_avoid=False,
            result_role="e7_policy",
            future_interval_id="future_interval_1",
        )

        first = portfolio_random_control_v2(
            decisions,
            actual_policy_result=actual,
            actual_policy_veto_ids=veto_ids,
            context=context,
            manifest=manifest,
            cost_scenario="normal",
            future_interval_id="future_interval_1",
            stratum_key=e7_random_control_stratum,
        )
        second = portfolio_random_control_v2(
            decisions,
            actual_policy_result=actual,
            actual_policy_veto_ids=veto_ids,
            context=context,
            manifest=manifest,
            cost_scenario="normal",
            future_interval_id="future_interval_1",
            stratum_key=e7_random_control_stratum,
        )

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["simulations"], 1_000)
        self.assertEqual(first["veto_count"], 2)
        self.assertTrue(first["shared_precomputed_mark_context"])
        self.assertEqual(first["manifest_hash"], manifest.sha256)
        self.assertEqual(
            first["random_control_strata"],
            ["trade_date", "symbol", "time_bucket"],
        )

        with self.assertRaises(ReplayCompatibilityError):
            portfolio_random_control_v2(
                decisions,
                actual_policy_result=actual,
                actual_policy_veto_ids={"A-0"},
                context=context,
                manifest=manifest,
                cost_scenario="normal",
                future_interval_id="future_interval_1",
                stratum_key=e7_random_control_stratum,
            )


if __name__ == "__main__":
    unittest.main()
