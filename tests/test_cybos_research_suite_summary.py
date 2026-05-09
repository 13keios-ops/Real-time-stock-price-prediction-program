from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_cybos_research_suite import summarize


class CybosResearchSuiteSummaryTests(unittest.TestCase):
    def test_summary_holds_when_all_candidates_are_negative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "latest-cybos-bar-only-h15.json").write_text(
                json.dumps(
                    {
                        "feature_set_name": "bar_only",
                        "walk_forward": {
                            "folds": 2,
                            "rows_evaluated": 100,
                            "trades_taken": 10,
                            "overall_accuracy": 0.5,
                            "trade_hit_rate": 0.2,
                            "cumulative_net_return_pct": -3.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (report_dir / "latest-cybos-expected-value-stability-bar-context-momentum-h15.json").write_text(
                json.dumps(
                    {
                        "feature_set_name": "bar_context_momentum",
                        "cost_sweep": [
                            {
                                "trade_cost_pct": 0.13,
                                "trades_taken": 10,
                                "trade_sum_net_return_pct": -1.0,
                                "bootstrap": {"fold_sum_net_return_pct_ci95": {"low": -2.0, "high": 0.5}},
                                "fold_distribution": {
                                    "positive_net_folds": 0,
                                    "negative_net_folds": 1,
                                    "no_trade_folds": 0,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (report_dir / "latest-cybos-rule-challengers-review.json").write_text(
                json.dumps(
                    {
                        "decision": {"label": "research_only_no_promotion"},
                        "leaderboard": [
                            {
                                "strategy_name": "quiet_breakout",
                                "trades_taken": 10,
                                "trade_hit_rate": 0.1,
                                "cumulative_net_return_pct": -5.0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = summarize(report_dir)

        self.assertEqual(result["posture"], "hold_all_current_cybos_candidates")
        self.assertEqual(result["bar_experiments"][0]["status"], "hold")
        self.assertEqual(result["rule_challengers"]["best_by_net_return"]["strategy_name"], "quiet_breakout")


if __name__ == "__main__":
    unittest.main()
