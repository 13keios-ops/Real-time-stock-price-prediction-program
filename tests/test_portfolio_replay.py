from datetime import time
from datetime import datetime
import unittest

from app.services.portfolio_replay import (
    DecisionPoint,
    ExecutableDecision,
    ReplayBar,
    build_executable_decisions,
    group_decision_episodes,
    portfolio_random_control,
    replay_long_only,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class PortfolioReplayTests(unittest.TestCase):
    def test_repeated_signal_rows_collapse_to_decision_episodes(self) -> None:
        episodes = group_decision_episodes(
            [
                DecisionPoint("a-1", "A", _dt("2026-07-01T09:15:00+09:00"), avoid=True),
                DecisionPoint("a-2", "A", _dt("2026-07-01T09:16:00+09:00"), avoid=True),
                DecisionPoint("a-3", "A", _dt("2026-07-01T09:18:00+09:00"), avoid=False),
                DecisionPoint("b-1", "B", _dt("2026-07-01T09:15:00+09:00"), avoid=False),
            ]
        )

        self.assertEqual(len(episodes), 3)
        first = next(item for item in episodes if item.episode_id.startswith("A:2026-07-01T09:15"))
        self.assertEqual(first.signal_rows, 2)
        self.assertTrue(first.avoid)

    def test_execution_uses_next_minute_open_and_forced_horizon_open(self) -> None:
        episodes = group_decision_episodes(
            [DecisionPoint("a-1", "A", _dt("2026-07-01T09:15:30+09:00"))]
        )
        bars = {
            "A": [
                ReplayBar("A", _dt("2026-07-01T09:15:00+09:00"), 99.0, 99.5),
                ReplayBar("A", _dt("2026-07-01T09:16:00+09:00"), 100.0, 100.5),
                ReplayBar("A", _dt("2026-07-01T09:31:00+09:00"), 102.0, 102.5),
            ]
        }

        executable, skipped = build_executable_decisions(
            episodes,
            bars,
            horizon_min=15,
            forced_flat_time=time(15, 20),
        )

        self.assertEqual(sum(skipped.values()), 0)
        self.assertEqual(executable[0].entry_time, _dt("2026-07-01T09:16:00+09:00"))
        self.assertEqual(executable[0].entry_price, 100.0)
        self.assertEqual(executable[0].exit_time, _dt("2026-07-01T09:31:00+09:00"))
        self.assertEqual(executable[0].exit_price, 102.0)

    def test_replay_enforces_cash_position_and_cost_constraints(self) -> None:
        decisions = [
            ExecutableDecision(
                episode_id="A-1",
                symbol="A",
                signal_time=_dt("2026-07-01T09:15:00+09:00"),
                entry_time=_dt("2026-07-01T09:16:00+09:00"),
                entry_price=100.0,
                exit_time=_dt("2026-07-01T09:31:00+09:00"),
                exit_price=102.0,
                signal_rows=1,
                avoid=False,
            ),
            ExecutableDecision(
                episode_id="A-2",
                symbol="A",
                signal_time=_dt("2026-07-01T09:16:00+09:00"),
                entry_time=_dt("2026-07-01T09:17:00+09:00"),
                entry_price=101.0,
                exit_time=_dt("2026-07-01T09:32:00+09:00"),
                exit_price=103.0,
                signal_rows=1,
                avoid=False,
            ),
            ExecutableDecision(
                episode_id="B-1",
                symbol="B",
                signal_time=_dt("2026-07-01T09:16:00+09:00"),
                entry_time=_dt("2026-07-01T09:17:00+09:00"),
                entry_price=100.0,
                exit_time=_dt("2026-07-01T09:32:00+09:00"),
                exit_price=99.0,
                signal_rows=1,
                avoid=False,
            ),
        ]

        result = replay_long_only(
            decisions,
            initial_cash=1_000.0,
            max_position_pct=0.6,
            max_open_positions=1,
            slippage_bps=5.0,
        )

        self.assertEqual(result["counters"]["trades_executed"], 1)
        self.assertEqual(result["counters"]["duplicate_symbol_skips"], 1)
        self.assertEqual(result["counters"]["max_position_skips"], 1)
        self.assertGreater(result["turnover_pct"], 0.0)
        self.assertLess(
            result["closed_trades"][0]["net_return_pct"],
            2.0,
        )

    def test_random_control_is_same_count_and_deterministic(self) -> None:
        decisions = []
        for index in range(10):
            decisions.append(
                ExecutableDecision(
                    episode_id=f"E-{index}",
                    symbol=f"S-{index}",
                    signal_time=_dt(f"2026-07-0{1 + index // 5}T09:15:00+09:00"),
                    entry_time=_dt(f"2026-07-0{1 + index // 5}T09:16:00+09:00"),
                    entry_price=100.0,
                    exit_time=_dt(f"2026-07-0{1 + index // 5}T09:31:00+09:00"),
                    exit_price=98.0 if index < 3 else 101.0,
                    signal_rows=1,
                    avoid=index < 3,
                )
            )
        kwargs = {
            "initial_cash": 100_000.0,
            "max_position_pct": 0.1,
            "max_open_positions": 10,
            "slippage_bps": 0.0,
        }
        actual = replay_long_only(decisions, respect_decision_avoid=True, **kwargs)
        first = portfolio_random_control(
            decisions,
            actual_policy_return_pct=float(actual["portfolio_return_pct"]),
            veto_count=3,
            simulations=50,
            seed=7,
            replay_kwargs=kwargs,
        )
        second = portfolio_random_control(
            decisions,
            actual_policy_return_pct=float(actual["portfolio_return_pct"]),
            veto_count=3,
            simulations=50,
            seed=7,
            replay_kwargs=kwargs,
        )

        self.assertEqual(first, second)
        self.assertEqual(first["veto_count"], 3)
        self.assertEqual(first["simulations"], 50)
        self.assertEqual(first["status"], "ok")


if __name__ == "__main__":
    unittest.main()