"""Tests for the same-coverage random-skip control.

These tests verify the FORMULAS against hand-computed / combinatorially
exact values, so they run without the database and without LightGBM.
If any of these fail, do not trust random_control blocks in reports.
Spec: docs/Buy-Avoid-Random-Control-Methodology.md
"""

import unittest

from scripts.buy_avoid_random_control import (
    VERDICT_BETTER,
    VERDICT_INDISTINCT,
    VERDICT_WORSE,
    aggregate_random_control_reports,
    analytic_random_skip_moments,
    random_control_report,
)


class AnalyticMomentsTests(unittest.TestCase):
    def test_exact_small_case_enumeration(self) -> None:
        # Population [-1, 0, 1], choose 2 without replacement.
        # All C(3,2) subset sums: (-1+0)=-1, (-1+1)=0, (0+1)=1.
        # Exact mean = 0, exact variance = ((-1)^2 + 0 + 1^2) / 3 = 2/3.
        expected, variance = analytic_random_skip_moments([-1.0, 0.0, 1.0], 2)
        self.assertAlmostEqual(expected, 0.0)
        self.assertAlmostEqual(variance, 2.0 / 3.0)

    def test_full_skip_has_zero_variance(self) -> None:
        expected, variance = analytic_random_skip_moments([1.0, 2.0, 3.0], 3)
        self.assertAlmostEqual(expected, 6.0)
        self.assertAlmostEqual(variance, 0.0)

    def test_review_ver_23_kis_shadow_expectation(self) -> None:
        # Regression anchor from review_ver_23 (2026-07-04):
        # population mean -0.10634188%/trade, 6,694 skipped
        # -> expected random skipped sum ~= -711.85%p.
        population = [-0.10634187804722031] * 25198
        expected, _variance = analytic_random_skip_moments(population, 6694)
        self.assertAlmostEqual(expected, 6694 * -0.10634187804722031, places=6)
        self.assertAlmostEqual(expected, -711.85, delta=0.01)


class RandomControlReportTests(unittest.TestCase):
    def test_deterministic_given_same_seed(self) -> None:
        returns = [((index * 37) % 11) - 5.0 for index in range(200)]
        first = random_control_report(returns, 50, -10.0)
        second = random_control_report(returns, 50, -10.0)
        self.assertEqual(first, second)

    def test_self_check_passes_on_normal_population(self) -> None:
        returns = [((index * 37) % 11) - 5.0 for index in range(500)]
        report = random_control_report(returns, 100, 0.0)
        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["simulation"]["self_check_ok"])

    def test_filter_picking_worst_trades_is_better_than_random(self) -> None:
        # 100 trades: 50 at -1.0 and 50 at +1.0.  A filter that skips the
        # 30 worst trades avoided sum=-30, far below random expectation 0.
        returns = [-1.0] * 50 + [1.0] * 50
        report = random_control_report(returns, 30, -30.0)
        self.assertEqual(report["status"], "ok")
        self.assertLess(report["comparison"]["z_score"], -1.6449)
        self.assertEqual(report["comparison"]["verdict"], VERDICT_BETTER)

    def test_filter_picking_best_trades_is_worse_than_random(self) -> None:
        returns = [-1.0] * 50 + [1.0] * 50
        report = random_control_report(returns, 30, 30.0)
        self.assertGreater(report["comparison"]["z_score"], 1.6449)
        self.assertEqual(report["comparison"]["verdict"], VERDICT_WORSE)

    def test_random_like_filter_is_indistinguishable(self) -> None:
        returns = [-1.0] * 50 + [1.0] * 50
        report = random_control_report(returns, 30, 0.0)
        self.assertEqual(report["comparison"]["verdict"], VERDICT_INDISTINCT)

    def test_sign_convention_excess(self) -> None:
        # excess = actual - expected; population mean is negative here.
        returns = [-2.0, -1.0, 0.0, 1.0]  # mean -0.5
        report = random_control_report(returns, 2, -3.0)  # expected = -1.0
        self.assertAlmostEqual(report["comparison"]["excess_vs_random_pct"], -2.0)

    def test_edge_cases_are_not_applicable(self) -> None:
        self.assertEqual(random_control_report([], 0, 0.0)["status"], "not_applicable_empty_population")
        self.assertEqual(random_control_report([1.0], 0, 0.0)["status"], "not_applicable_no_skips")
        self.assertEqual(random_control_report([1.0, 2.0], 2, 3.0)["status"], "not_applicable_all_skipped")


class AggregateTests(unittest.TestCase):
    def test_aggregate_sums_expectations_and_variances(self) -> None:
        returns = [-1.0] * 50 + [1.0] * 50
        fold_a = random_control_report(returns, 30, -30.0)
        fold_b = random_control_report(returns, 30, -30.0)
        aggregate = aggregate_random_control_reports([fold_a, fold_b])
        self.assertEqual(aggregate["status"], "ok")
        self.assertAlmostEqual(aggregate["actual_skipped_cumulative_net_pct"], -60.0)
        self.assertAlmostEqual(aggregate["expected_random_skipped_sum_pct"], 0.0)
        expected_variance = fold_a["analytic"]["std_random_skipped_sum_pct"] ** 2 * 2
        self.assertAlmostEqual(aggregate["std_random_skipped_sum_pct"] ** 2, expected_variance)
        self.assertEqual(aggregate["verdict"], VERDICT_BETTER)
        self.assertEqual(aggregate["fold_verdict_counts"][VERDICT_BETTER], 2)

    def test_aggregate_skips_not_applicable_folds(self) -> None:
        returns = [-1.0] * 50 + [1.0] * 50
        fold_a = random_control_report(returns, 30, -30.0)
        fold_b = {"status": "not_applicable_no_skips"}
        aggregate = aggregate_random_control_reports([fold_a, fold_b])
        self.assertEqual(aggregate["folds_total"], 2)
        self.assertEqual(aggregate["folds_usable"], 1)

    def test_aggregate_with_no_usable_folds(self) -> None:
        aggregate = aggregate_random_control_reports([{"status": "not_applicable_no_skips"}, None])
        self.assertEqual(aggregate["status"], "not_applicable_no_usable_folds")


class ShadowScriptIntegrationTests(unittest.TestCase):
    def test_threshold_summary_includes_random_control(self) -> None:
        from scripts.summarize_lightgbm_defensive_shadow import ShadowRow, _threshold_summary

        rows = []
        for index in range(40):
            losing = index < 20
            rows.append(
                ShadowRow(
                    signal_id=f"sig-{index}",
                    symbol="005930",
                    event_time=f"2026-06-11T09:{index:02d}:00+09:00",
                    signal_confidence=0.6,
                    probability_up=0.1 if losing else 0.7,
                    probability_flat=0.2,
                    probability_down=0.7 if losing else 0.1,
                    label="down" if losing else "up",
                    future_return_pct=-1.0 if losing else 1.0,
                )
            )
        summary = _threshold_summary(rows, threshold=0.5, trade_cost_pct=0.0, require_down_argmax=True)
        control = summary["random_control"]
        self.assertEqual(control["status"], "ok")
        self.assertEqual(control["n_population"], 40)
        self.assertEqual(control["n_skip"], 20)
        # The filter skipped exactly the 20 losing trades -> sum -20 vs
        # random expectation 0 -> clearly better than random.
        self.assertAlmostEqual(control["actual_skipped_cumulative_net_pct"], -20.0)
        self.assertEqual(control["comparison"]["verdict"], VERDICT_BETTER)


if __name__ == "__main__":
    unittest.main()
