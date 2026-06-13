from __future__ import annotations

import unittest

from scripts.summarize_cybos_buy_avoid_proxy import (
    _buy_avoid_fold_result,
    _down_threshold_for_target_skip_rate,
    _runtime_baseline_replay_status,
    summarize_skip_targets,
)


class CybosBuyAvoidProxyTests(unittest.TestCase):
    def test_runtime_baseline_replay_is_not_available_without_orderbook_features(self) -> None:
        status = _runtime_baseline_replay_status(
            [
                "avg_trade_size",
                "hl_range_pct",
                "return_1m_pct",
                "close_position_pct",
                "minute_slot_pct",
                "log_volume",
                "prev_return_pct",
                "prev_hl_range_pct",
                "log_volume_delta",
            ]
        )

        self.assertFalse(status["available"])
        self.assertEqual(status["status"], "not_replayed_orderbook_features_missing")
        self.assertEqual(status["recommended_experiment_mode"], "proxy_buy_rescue")
        self.assertIn("bid_ask_imbalance", status["missing_features"])
        self.assertIn("spread_bps", status["missing_features"])

    def test_runtime_baseline_replay_is_available_when_required_features_exist(self) -> None:
        status = _runtime_baseline_replay_status(
            [
                "return_1m_pct",
                "bid_ask_imbalance",
                "spread_bps",
            ]
        )

        self.assertTrue(status["available"])
        self.assertEqual(status["status"], "replay_available")
        self.assertEqual(status["recommended_experiment_mode"], "baseline_replay_buy_rescue")

    def test_down_threshold_matches_top_skip_share(self) -> None:
        threshold = _down_threshold_for_target_skip_rate([0.10, 0.20, 0.30, 0.40, 0.50], 0.40)

        self.assertAlmostEqual(threshold or 0.0, 0.34)

    def test_buy_avoid_improvement_requires_fold_consistency(self) -> None:
        fold_summaries = [
            {
                "buy_avoid_targets": [
                    {
                        "target_skip_rate": 0.4,
                        "baseline_trades": 10,
                        "kept_trades": 6,
                        "skipped_trades": 4,
                        "actual_skip_rate": 0.4,
                        "baseline_net_return_pct": -1.0,
                        "kept_net_return_pct": 1.0,
                        "net_improvement_pct": 2.0,
                    }
                ]
            },
            {
                "buy_avoid_targets": [
                    {
                        "target_skip_rate": 0.4,
                        "baseline_trades": 10,
                        "kept_trades": 6,
                        "skipped_trades": 4,
                        "actual_skip_rate": 0.4,
                        "baseline_net_return_pct": -1.0,
                        "kept_net_return_pct": 1.0,
                        "net_improvement_pct": 2.0,
                    }
                ]
            },
            {
                "buy_avoid_targets": [
                    {
                        "target_skip_rate": 0.4,
                        "baseline_trades": 10,
                        "kept_trades": 6,
                        "skipped_trades": 4,
                        "actual_skip_rate": 0.4,
                        "baseline_net_return_pct": 1.0,
                        "kept_net_return_pct": 0.5,
                        "net_improvement_pct": -0.5,
                    }
                ]
            },
        ]

        summary = summarize_skip_targets(fold_summaries)[0]

        self.assertEqual(summary["baseline_trades"], 30)
        self.assertAlmostEqual(summary["actual_skip_rate"], 0.4)
        self.assertAlmostEqual(summary["positive_improvement_fold_share"], 2 / 3)
        self.assertEqual(summary["conclusion"], "follow_up_candidate_proxy_only")

    def test_fold_result_skips_high_down_probability_buy_candidates(self) -> None:
        calibration = [
            _row(probability_up=0.60, probability_down=0.10, future_return_pct=0.2, actual_label="up"),
            _row(probability_up=0.61, probability_down=0.20, future_return_pct=0.2, actual_label="up"),
            _row(probability_up=0.62, probability_down=0.30, future_return_pct=-0.5, actual_label="down"),
            _row(probability_up=0.63, probability_down=0.40, future_return_pct=-0.5, actual_label="down"),
        ]
        test = [
            _row(probability_up=0.60, probability_down=0.10, future_return_pct=0.5, actual_label="up"),
            _row(probability_up=0.62, probability_down=0.50, future_return_pct=-0.6, actual_label="down"),
        ]

        result = _buy_avoid_fold_result(
            scored_calibration=calibration,
            scored_test=test,
            target_skip_rates=(0.5,),
            buy_threshold=0.58,
            trade_cost_pct=0.1,
        )

        target = result["target_results"][0]
        self.assertEqual(target["baseline_trades"], 2)
        self.assertEqual(target["skipped_trades"], 1)
        self.assertGreater(target["net_improvement_pct"], 0.0)


def _row(
    *,
    probability_up: float,
    probability_down: float,
    future_return_pct: float,
    actual_label: str,
) -> dict[str, object]:
    return {
        "predicted_label": "up",
        "probability_up": probability_up,
        "probability_down": probability_down,
        "future_return_pct": future_return_pct,
        "actual_label": actual_label,
    }


if __name__ == "__main__":
    unittest.main()
