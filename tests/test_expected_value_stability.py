from __future__ import annotations

import unittest

from scripts.summarize_expected_value_stability import summarize


class ExpectedValueStabilityTests(unittest.TestCase):
    def test_cost_sweep_reprices_existing_fold_selections(self) -> None:
        payload = {
            "source": "cybos-historical",
            "feature_set_name": "bar_context_momentum",
            "horizon_min": 15,
            "walk_forward": {
                "folds": 2,
                "rows_evaluated": 200,
                "trades_taken": 10,
                "overall_accuracy": 0.55,
                "trade_hit_rate": 0.4,
                "trade_sum_net_return_pct": 0.7,
                "trade_cost_pct": 0.10,
                "fold_summaries": [
                    {
                        "trades_taken": 4,
                        "cumulative_gross_return_pct": 1.0,
                        "cumulative_net_return_pct": 0.6,
                        "average_net_return_pct": 0.15,
                        "trade_hit_rate": 0.5,
                    },
                    {
                        "trades_taken": 6,
                        "cumulative_gross_return_pct": 0.7,
                        "cumulative_net_return_pct": 0.1,
                        "average_net_return_pct": 1 / 60,
                        "trade_hit_rate": 1 / 3,
                    },
                ],
            },
        }

        summary = summarize(
            payload,
            bootstrap_samples=100,
            seed=7,
            cost_sweep_pct=[0.10, 0.20],
        )

        by_cost = {item["trade_cost_pct"]: item for item in summary["cost_sweep"]}
        self.assertAlmostEqual(by_cost[0.10]["trade_sum_net_return_pct"], 0.7)
        self.assertAlmostEqual(by_cost[0.20]["trade_sum_net_return_pct"], -0.3)
        self.assertEqual(by_cost[0.10]["fold_distribution"]["positive_net_folds"], 2)
        self.assertEqual(by_cost[0.20]["fold_distribution"]["positive_net_folds"], 1)
        self.assertEqual(by_cost[0.20]["conclusion"], "hold: cost-adjusted trade-sum return is negative.")


if __name__ == "__main__":
    unittest.main()
