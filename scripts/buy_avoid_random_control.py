#!/usr/bin/env python3
"""Same-coverage random-skip control for buy-avoid style trade filters.

READ FIRST (Codex 필독): docs/Buy-Avoid-Random-Control-Methodology.md
That document is the single source of truth for the formulas below.
Do NOT change the math here without updating that document, and do NOT
change that document without re-running tests/test_buy_avoid_random_control.py.

Why this module exists
----------------------
When the baseline trade population has a negative average return, removing
ANY subset of trades mechanically improves the cumulative return of the
remaining set.  Therefore "delta vs baseline > 0" is NOT evidence that a
filter selects bad trades.  The only fair benchmark is: "did the filter's
skipped set lose more than a random skip of the same size would have?"

Sign convention (critical - do not flip):
  excess_vs_random_pct = actual_skipped_sum - expected_random_skipped_sum
  * excess < 0  -> the filter avoided trades that lost MORE than random
                   -> the filter is genuinely selective (GOOD).
  * excess > 0  -> the filter avoided trades that were BETTER than random
                   -> the filter is anti-selective (BAD).
  z_score = excess / analytic_std.  One-sided 95% boundary = 1.6449.

This module is pure stdlib (math, random) and has no repo dependencies,
so it can be unit-tested without the database.
"""

from __future__ import annotations

import math
import random
from typing import Any, Sequence

DEFAULT_N_TRIALS = 100
DEFAULT_SEED_BASE = 20260704  # date this methodology was adopted; never change silently
Z_ONE_SIDED_95 = 1.6448536269514722

VERDICT_BETTER = "filter_better_than_random_p95"
VERDICT_WORSE = "filter_worse_than_random_p95"
VERDICT_INDISTINCT = "not_distinguishable_from_random"
VERDICT_NOT_APPLICABLE = "not_applicable"


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Linear-interpolation percentile on an already-sorted list."""
    if not sorted_values:
        raise ValueError("percentile of empty list")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = fraction * (len(sorted_values) - 1)
    lower = int(math.floor(position))
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight)


def analytic_random_skip_moments(net_returns: Sequence[float], n_skip: int) -> tuple[float, float]:
    """Exact mean and variance of the SUM of ``n_skip`` returns drawn
    uniformly WITHOUT replacement from ``net_returns``.

    mean     = n_skip * population_mean
    variance = n_skip * population_variance * (N - n_skip) / (N - 1)
               (finite population correction; population_variance divides by N)

    These are textbook simple-random-sampling identities; the simulation in
    ``random_control_report`` must agree with them (self-check).
    """
    population = len(net_returns)
    if population <= 0 or n_skip < 0 or n_skip > population:
        raise ValueError(f"invalid n_skip={n_skip} for population={population}")
    mean = sum(net_returns) / population
    expected_sum = n_skip * mean
    population_variance = sum((value - mean) ** 2 for value in net_returns) / population
    if population <= 1 or n_skip in (0, population):
        variance_sum = 0.0
    else:
        variance_sum = n_skip * population_variance * (population - n_skip) / (population - 1)
    return expected_sum, variance_sum


def random_control_report(
    net_returns: Sequence[float],
    n_skip: int,
    actual_skipped_sum: float,
    *,
    n_trials: int = DEFAULT_N_TRIALS,
    seed_base: int = DEFAULT_SEED_BASE,
) -> dict[str, Any]:
    """Build the ``random_control`` JSON block for one filter evaluation.

    Parameters
    ----------
    net_returns:        per-trade NET returns (%) of the FULL baseline
                        population the filter chose from (cost already
                        subtracted, same as the report's other numbers).
    n_skip:             how many trades the filter actually skipped.
    actual_skipped_sum: cumulative net return (%) of the skipped set.
    """
    population = len(net_returns)
    if population == 0:
        return {"status": "not_applicable_empty_population"}
    if n_skip <= 0:
        return {"status": "not_applicable_no_skips", "n_population": population}
    if n_skip >= population:
        return {"status": "not_applicable_all_skipped", "n_population": population, "n_skip": n_skip}

    expected_sum, variance_sum = analytic_random_skip_moments(net_returns, n_skip)
    std_sum = math.sqrt(variance_sum)
    population_mean = expected_sum / n_skip

    values = list(net_returns)
    trial_sums: list[float] = []
    for trial_index in range(n_trials):
        rng = random.Random(seed_base + trial_index)
        picked = rng.sample(range(population), n_skip)
        trial_sums.append(sum(values[index] for index in picked))
    trial_sums_sorted = sorted(trial_sums)
    simulation_mean = sum(trial_sums) / n_trials
    if n_trials > 1:
        simulation_std = math.sqrt(sum((value - simulation_mean) ** 2 for value in trial_sums) / (n_trials - 1))
    else:
        simulation_std = 0.0

    # Self-check: the simulation mean must sit within 5 standard errors of
    # the analytic expectation.  If this fails the implementation is broken
    # (wrong population, wrong n_skip, or biased sampling) - treat the whole
    # block as unusable rather than trusting either half.
    standard_error = std_sum / math.sqrt(n_trials) if n_trials > 0 else 0.0
    if std_sum == 0.0:
        self_check_ok = abs(simulation_mean - expected_sum) < 1e-9
    else:
        self_check_ok = abs(simulation_mean - expected_sum) <= 5.0 * standard_error

    excess = actual_skipped_sum - expected_sum
    if std_sum > 0.0:
        z_score: float | None = excess / std_sum
    else:
        z_score = None
    empirical_below = sum(1 for value in trial_sums if value <= actual_skipped_sum)
    empirical_percentile = empirical_below / n_trials

    if not self_check_ok:
        verdict = "self_check_failed_do_not_use"
    elif z_score is None:
        verdict = VERDICT_NOT_APPLICABLE
    elif z_score <= -Z_ONE_SIDED_95:
        verdict = VERDICT_BETTER
    elif z_score >= Z_ONE_SIDED_95:
        verdict = VERDICT_WORSE
    else:
        verdict = VERDICT_INDISTINCT

    return {
        "status": "ok",
        "method": "same_coverage_random_skip_v1",
        "n_population": population,
        "n_skip": n_skip,
        "actual_skipped_cumulative_net_pct": actual_skipped_sum,
        "analytic": {
            "expected_random_skipped_sum_pct": expected_sum,
            "std_random_skipped_sum_pct": std_sum,
            "population_mean_net_pct": population_mean,
        },
        "simulation": {
            "n_trials": n_trials,
            "seed_base": seed_base,
            "mean_pct": simulation_mean,
            "std_pct": simulation_std,
            "p05_pct": _percentile(trial_sums_sorted, 0.05),
            "p50_pct": _percentile(trial_sums_sorted, 0.50),
            "p95_pct": _percentile(trial_sums_sorted, 0.95),
            "self_check_ok": self_check_ok,
        },
        "comparison": {
            "excess_vs_random_pct": excess,
            "z_score": z_score,
            "empirical_percentile": empirical_percentile,
            "verdict": verdict,
            "sign_convention": "excess<0 means the filter skipped worse-than-random trades (good)",
        },
    }


def aggregate_random_control_reports(reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Combine per-fold ``random_control`` blocks into one aggregate verdict.

    Folds are independent, so expectations and variances ADD.  The aggregate
    z uses the summed analytic moments; per-fold verdicts are also counted so
    a single dominant fold cannot hide inconsistency.
    """
    usable = [report for report in reports if isinstance(report, dict) and report.get("status") == "ok"]
    if not usable:
        return {"status": "not_applicable_no_usable_folds", "folds_total": len(reports)}
    actual_total = sum(float(report["actual_skipped_cumulative_net_pct"]) for report in usable)
    expected_total = sum(float(report["analytic"]["expected_random_skipped_sum_pct"]) for report in usable)
    variance_total = sum(float(report["analytic"]["std_random_skipped_sum_pct"]) ** 2 for report in usable)
    std_total = math.sqrt(variance_total)
    excess = actual_total - expected_total
    z_score = (excess / std_total) if std_total > 0.0 else None
    if z_score is None:
        verdict = VERDICT_NOT_APPLICABLE
    elif z_score <= -Z_ONE_SIDED_95:
        verdict = VERDICT_BETTER
    elif z_score >= Z_ONE_SIDED_95:
        verdict = VERDICT_WORSE
    else:
        verdict = VERDICT_INDISTINCT
    verdict_counts: dict[str, int] = {}
    for report in usable:
        fold_verdict = str(report.get("comparison", {}).get("verdict"))
        verdict_counts[fold_verdict] = verdict_counts.get(fold_verdict, 0) + 1
    return {
        "status": "ok",
        "method": "same_coverage_random_skip_v1_fold_aggregate",
        "folds_total": len(reports),
        "folds_usable": len(usable),
        "actual_skipped_cumulative_net_pct": actual_total,
        "expected_random_skipped_sum_pct": expected_total,
        "std_random_skipped_sum_pct": std_total,
        "excess_vs_random_pct": excess,
        "z_score": z_score,
        "verdict": verdict,
        "fold_verdict_counts": verdict_counts,
        "sign_convention": "excess<0 means the filter skipped worse-than-random trades (good)",
    }
