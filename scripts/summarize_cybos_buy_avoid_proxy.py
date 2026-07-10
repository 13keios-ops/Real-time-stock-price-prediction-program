#!/usr/bin/env python3
"""Cybos 5y buy-avoid proxy and regime diagnostics.

This script is research-only. It reads the local SQLite runtime store,
reuses the existing Cybos bar_context_momentum LightGBM profile, and writes
diagnostic reports. It does not promote models, change gates, submit orders,
or update runtime config.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.observability.logging import configure_logging
from app.services.research import (
    CYBOS_PROFITABILITY_COST_PCT,
    CYBOS_HISTORICAL_SOURCE,
    _cybos_feature_set_names,
    _effective_signal_confidence,
    _effective_trade_cost_pct,
    _fit_lightgbm_model,
    _get_research_sqlite_store,
    _has_complete_direction_labels,
    _metrics_from_scored_predictions,
    _purged_walk_forward_slices,
    _score_rows_with_model,
    _source_bar_train_validation_rows,
)
from app.utils.time import now_local

# REPO_ROOT is already on sys.path above, so the scripts.* import always works here.
from scripts.buy_avoid_random_control import (
    aggregate_random_control_reports,
    random_control_report,
)


DEFAULT_TARGET_SKIP_RATES = (0.20, 0.30, 0.3665, 0.40, 0.50)
DEFAULT_TARGET_RESCUE_RATES = (0.05, 0.10, 0.20, 0.30)
DEFAULT_PRECISION_TARGET_RESCUE_RATES = (0.001, 0.0025, 0.005, 0.01, 0.02, 0.03, 0.05)
COMPARABLE_SKIP_RATE_MIN = 0.20
COMPARABLE_SKIP_RATE_MAX = 0.50
COMPARABLE_RESCUE_RATE_MIN = 0.05
COMPARABLE_RESCUE_RATE_MAX = 0.30
PRECISION_RESCUE_RATE_MIN = 0.001
PRECISION_RESCUE_RATE_MAX = 0.05
FOLLOW_UP_FOLD_SHARE_MIN = 2 / 3
BUY_RESCUE_MIN_TRADES = 500
BUY_RESCUE_PRECISION_MIN_TRADES = 100
BUY_RESCUE_PRECISION_MIN_NET_PER_TRADE_PCT = 0.03
FOLD_CONCENTRATION_MAX_SHARE = 0.50
RUNTIME_BASELINE_REQUIRED_FEATURES = ("return_1m_pct", "bid_ask_imbalance", "spread_bps")


@dataclass(frozen=True)
class TradeMetrics:
    trades: int
    gross_return_pct: float
    net_return_pct: float
    hit_rate: float
    win_rate: float


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _quantile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    bounded = min(1.0, max(0.0, percentile))
    position = bounded * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _down_threshold_for_target_skip_rate(down_probabilities: list[float], target_skip_rate: float) -> float | None:
    """Return a down-probability threshold that skips the highest target share."""
    if not down_probabilities:
        return None
    target = min(1.0, max(0.0, float(target_skip_rate)))
    if target <= 0:
        return max(down_probabilities) + 1.0
    if target >= 1:
        return min(down_probabilities) - 1.0
    return _quantile(down_probabilities, 1.0 - target)


def _up_threshold_for_target_rescue_rate(up_probabilities: list[float], target_rescue_rate: float) -> float | None:
    """Return an up-probability threshold that rescues the highest target share."""
    if not up_probabilities:
        return None
    target = min(1.0, max(0.0, float(target_rescue_rate)))
    if target <= 0:
        return max(up_probabilities) + 1.0
    if target >= 1:
        return min(up_probabilities) - 1.0
    return _quantile(up_probabilities, 1.0 - target)


def _is_buy_candidate(row: dict[str, Any], buy_threshold: float) -> bool:
    return str(row.get("predicted_label")) == "up" and _float(row.get("probability_up")) >= buy_threshold


def _is_proxy_no_buy_candidate(row: dict[str, Any], buy_threshold: float) -> bool:
    return not _is_buy_candidate(row, buy_threshold)


def _runtime_baseline_replay_status(row_value_keys: list[str]) -> dict[str, Any]:
    available = set(row_value_keys)
    missing = [name for name in RUNTIME_BASELINE_REQUIRED_FEATURES if name not in available]
    can_call_with_defaults = "return_1m_pct" in available
    if not missing:
        status = "replay_available"
        reason = (
            "Cybos rows include the features used by app.models.baseline.BaselineDirectionModel, "
            "so runtime baseline replay can be interpreted directly."
        )
    elif can_call_with_defaults:
        status = "not_replayed_orderbook_features_missing"
        reason = (
            "Cybos bar rows include return_1m_pct but do not include live orderbook features "
            "bid_ask_imbalance and spread_bps. BaselineDirectionModel could be called because it "
            "defaults missing values to 0.0, but that would not reproduce the runtime baseline."
        )
    else:
        status = "not_replayed_required_features_missing"
        reason = (
            "Cybos rows are missing required runtime baseline features, so runtime baseline replay "
            "is not available."
        )
    return {
        "available": not missing,
        "status": status,
        "model": "app.models.baseline.BaselineDirectionModel",
        "required_features": list(RUNTIME_BASELINE_REQUIRED_FEATURES),
        "row_value_keys": list(row_value_keys),
        "missing_features": missing,
        "can_call_with_missing_defaults": can_call_with_defaults and bool(missing),
        "reason": reason,
        "recommended_experiment_mode": "baseline_replay_buy_rescue" if not missing else "proxy_buy_rescue",
    }


def _trade_metrics(rows: list[dict[str, Any]], trade_cost_pct: float) -> TradeMetrics:
    gross = sum(_float(row.get("future_return_pct")) for row in rows)
    net = gross - (len(rows) * trade_cost_pct)
    hits = sum(1 for row in rows if str(row.get("actual_label")) == "up")
    wins = sum(1 for row in rows if _float(row.get("future_return_pct")) - trade_cost_pct > 0.0)
    return TradeMetrics(
        trades=len(rows),
        gross_return_pct=gross,
        net_return_pct=net,
        hit_rate=(hits / len(rows)) if rows else 0.0,
        win_rate=(wins / len(rows)) if rows else 0.0,
    )


def _buy_avoid_fold_result(
    *,
    scored_calibration: list[dict[str, Any]],
    scored_test: list[dict[str, Any]],
    target_skip_rates: tuple[float, ...],
    buy_threshold: float,
    trade_cost_pct: float,
) -> dict[str, Any]:
    calibration_buys = [row for row in scored_calibration if _is_buy_candidate(row, buy_threshold)]
    test_buys = [row for row in scored_test if _is_buy_candidate(row, buy_threshold)]
    baseline = _trade_metrics(test_buys, trade_cost_pct)
    target_results: list[dict[str, Any]] = []
    calibration_down_probs = [_float(row.get("probability_down")) for row in calibration_buys]
    for target_skip_rate in target_skip_rates:
        threshold = _down_threshold_for_target_skip_rate(calibration_down_probs, target_skip_rate)
        if threshold is None:
            kept = list(test_buys)
            skipped: list[dict[str, Any]] = []
            threshold_status = "no_calibration_buy_candidates"
        else:
            kept = [row for row in test_buys if _float(row.get("probability_down")) < threshold]
            skipped = [row for row in test_buys if _float(row.get("probability_down")) >= threshold]
            threshold_status = "ok"
        kept_metrics = _trade_metrics(kept, trade_cost_pct)
        skipped_metrics = _trade_metrics(skipped, trade_cost_pct)
        actual_skip_rate = (len(skipped) / len(test_buys)) if test_buys else 0.0
        # Same-coverage random-skip control per fold.
        # See docs/Buy-Avoid-Random-Control-Methodology.md: net_improvement_pct > 0
        # alone is not evidence of selectivity when the baseline mean is negative.
        test_net_returns = [_float(row.get("future_return_pct")) - trade_cost_pct for row in test_buys]
        random_control = random_control_report(
            test_net_returns,
            len(skipped),
            skipped_metrics.net_return_pct,
        )
        target_results.append(
            {
                "target_skip_rate": float(target_skip_rate),
                "down_probability_threshold": threshold,
                "threshold_status": threshold_status,
                "calibration_buy_candidates": len(calibration_buys),
                "baseline_trades": baseline.trades,
                "kept_trades": kept_metrics.trades,
                "skipped_trades": skipped_metrics.trades,
                "actual_skip_rate": actual_skip_rate,
                "baseline_gross_return_pct": baseline.gross_return_pct,
                "baseline_net_return_pct": baseline.net_return_pct,
                "kept_gross_return_pct": kept_metrics.gross_return_pct,
                "kept_net_return_pct": kept_metrics.net_return_pct,
                "skipped_gross_return_pct": skipped_metrics.gross_return_pct,
                "skipped_net_return_pct": skipped_metrics.net_return_pct,
                "net_improvement_pct": kept_metrics.net_return_pct - baseline.net_return_pct,
                "baseline_hit_rate": baseline.hit_rate,
                "kept_hit_rate": kept_metrics.hit_rate,
                "skipped_hit_rate": skipped_metrics.hit_rate,
                "baseline_win_rate": baseline.win_rate,
                "kept_win_rate": kept_metrics.win_rate,
                "skipped_win_rate": skipped_metrics.win_rate,
                "random_control": random_control,
            }
        )
    return {
        "baseline": {
            "trades": baseline.trades,
            "gross_return_pct": baseline.gross_return_pct,
            "net_return_pct": baseline.net_return_pct,
            "hit_rate": baseline.hit_rate,
            "win_rate": baseline.win_rate,
        },
        "target_results": target_results,
    }


def _buy_rescue_fold_result(
    *,
    scored_calibration: list[dict[str, Any]],
    scored_test: list[dict[str, Any]],
    target_rescue_rates: tuple[float, ...],
    buy_threshold: float,
    trade_cost_pct: float,
) -> dict[str, Any]:
    calibration_no_buys = [row for row in scored_calibration if _is_proxy_no_buy_candidate(row, buy_threshold)]
    test_no_buys = [row for row in scored_test if _is_proxy_no_buy_candidate(row, buy_threshold)]
    target_results: list[dict[str, Any]] = []
    calibration_up_probs = [_float(row.get("probability_up")) for row in calibration_no_buys]
    for target_rescue_rate in target_rescue_rates:
        threshold = _up_threshold_for_target_rescue_rate(calibration_up_probs, target_rescue_rate)
        if threshold is None:
            rescued: list[dict[str, Any]] = []
            untouched = list(test_no_buys)
            threshold_status = "no_calibration_no_buy_candidates"
        else:
            rescued = [row for row in test_no_buys if _float(row.get("probability_up")) >= threshold]
            untouched = [row for row in test_no_buys if _float(row.get("probability_up")) < threshold]
            threshold_status = "ok"
        rescued_metrics = _trade_metrics(rescued, trade_cost_pct)
        actual_rescue_rate = (len(rescued) / len(test_no_buys)) if test_no_buys else 0.0
        target_results.append(
            {
                "target_rescue_rate": float(target_rescue_rate),
                "up_probability_threshold": threshold,
                "threshold_status": threshold_status,
                "calibration_no_buy_candidates": len(calibration_no_buys),
                "no_buy_candidates": len(test_no_buys),
                "rescued_trades": rescued_metrics.trades,
                "untouched_candidates": len(untouched),
                "actual_rescue_rate": actual_rescue_rate,
                "trade_cost_pct": float(trade_cost_pct),
                "rescued_gross_return_pct": rescued_metrics.gross_return_pct,
                "rescued_net_return_pct": rescued_metrics.net_return_pct,
                "rescued_cost_drag_pct": rescued_metrics.trades * trade_cost_pct,
                "rescued_avg_gross_return_pct": (
                    rescued_metrics.gross_return_pct / rescued_metrics.trades
                    if rescued_metrics.trades
                    else 0.0
                ),
                "rescued_avg_net_return_pct": (
                    rescued_metrics.net_return_pct / rescued_metrics.trades
                    if rescued_metrics.trades
                    else 0.0
                ),
                "required_gross_per_trade_pct": float(trade_cost_pct),
                "gross_minus_cost_per_trade_pct": (
                    (rescued_metrics.gross_return_pct / rescued_metrics.trades) - trade_cost_pct
                    if rescued_metrics.trades
                    else 0.0
                ),
                "rescued_hit_rate": rescued_metrics.hit_rate,
                "rescued_win_rate": rescued_metrics.win_rate,
                "net_improvement_pct": rescued_metrics.net_return_pct,
            }
        )
    return {
        "no_buy_candidates": len(test_no_buys),
        "target_results": target_results,
    }


def _price_from_lifecycle_row(row: dict[str, Any]) -> float:
    price = _float(row.get("price", row.get("close")))
    if price <= 0:
        raise ValueError("hold-rescue lifecycle rows require a positive price or close value.")
    return price


def _simulate_hold_rescue_lifecycle(
    price_path: list[dict[str, Any]],
    *,
    entry_index: int,
    baseline_exit_index: int,
    up_probability_threshold: float,
    max_extension_steps: int,
    max_loss_pct: float | None = None,
    trade_cost_pct: float = 0.0,
) -> dict[str, Any]:
    """Simulate a single synthetic hold-rescue lifecycle without touching broker state."""
    if not price_path:
        raise ValueError("price_path must not be empty.")
    if entry_index < 0 or baseline_exit_index < 0:
        raise ValueError("entry_index and baseline_exit_index must be non-negative.")
    if entry_index > baseline_exit_index:
        raise ValueError("entry_index must be <= baseline_exit_index.")
    if baseline_exit_index >= len(price_path):
        raise ValueError("baseline_exit_index is outside price_path.")

    entry_price = _price_from_lifecycle_row(price_path[entry_index])
    baseline_exit_price = _price_from_lifecycle_row(price_path[baseline_exit_index])
    baseline_net_return_pct = ((baseline_exit_price / entry_price) - 1.0) * 100.0 - trade_cost_pct
    baseline_exit_probability = _float(price_path[baseline_exit_index].get("probability_up"))
    rescue_applied = False
    rescue_exit_index = baseline_exit_index
    rescue_exit_reason = "threshold_not_met"
    max_loss_limit = abs(max_loss_pct) if max_loss_pct is not None else None

    if baseline_exit_probability >= up_probability_threshold:
        if max_extension_steps <= 0:
            rescue_exit_reason = "max_extension_zero"
        elif baseline_exit_index >= len(price_path) - 1:
            rescue_exit_reason = "no_future_rows"
        else:
            rescue_applied = True
            max_exit_index = min(len(price_path) - 1, baseline_exit_index + max_extension_steps)
            rescue_exit_reason = "end_of_path"
            for idx in range(baseline_exit_index + 1, max_exit_index + 1):
                rescue_exit_index = idx
                current_price = _price_from_lifecycle_row(price_path[idx])
                current_return_pct = ((current_price / entry_price) - 1.0) * 100.0
                if max_loss_limit is not None and current_return_pct <= -max_loss_limit:
                    rescue_exit_reason = "max_loss"
                    break
                if _float(price_path[idx].get("probability_up")) < up_probability_threshold:
                    rescue_exit_reason = "probability_dropped"
                    break
                if idx == max_exit_index and idx < len(price_path) - 1:
                    rescue_exit_reason = "max_extension_steps"

    rescue_exit_price = _price_from_lifecycle_row(price_path[rescue_exit_index])
    rescue_net_return_pct = ((rescue_exit_price / entry_price) - 1.0) * 100.0 - trade_cost_pct
    drawdown_returns = [
        ((_price_from_lifecycle_row(row) / entry_price) - 1.0) * 100.0
        for row in price_path[entry_index : rescue_exit_index + 1]
    ]
    return {
        "entry_index": entry_index,
        "baseline_exit_index": baseline_exit_index,
        "rescue_exit_index": rescue_exit_index,
        "extension_steps": rescue_exit_index - baseline_exit_index,
        "rescue_applied": rescue_applied,
        "rescue_exit_reason": rescue_exit_reason,
        "entry_price": entry_price,
        "baseline_exit_price": baseline_exit_price,
        "rescue_exit_price": rescue_exit_price,
        "baseline_exit_probability_up": baseline_exit_probability,
        "up_probability_threshold": float(up_probability_threshold),
        "baseline_net_return_pct": baseline_net_return_pct,
        "rescue_net_return_pct": rescue_net_return_pct,
        "rescue_delta_pct": rescue_net_return_pct - baseline_net_return_pct,
        "max_drawdown_pct": min(drawdown_returns) if drawdown_returns else 0.0,
    }


def _candidate_conclusion(summary: dict[str, Any]) -> str:
    if _int(summary.get("eligible_folds")) <= 0:
        return "insufficient_baseline_trades"
    skip_rate = _float(summary.get("actual_skip_rate"))
    if skip_rate < COMPARABLE_SKIP_RATE_MIN or skip_rate > COMPARABLE_SKIP_RATE_MAX:
        return "coverage_out_of_bounds"
    if _float(summary.get("net_improvement_pct")) <= 0:
        return "hold_no_net_improvement"
    if _float(summary.get("positive_improvement_fold_share")) < FOLLOW_UP_FOLD_SHARE_MIN:
        return "average_positive_but_fold_inconsistent"
    return "follow_up_candidate_proxy_only"


def _buy_rescue_conclusion(summary: dict[str, Any]) -> str:
    if _int(summary.get("eligible_folds")) <= 0 or _int(summary.get("rescued_trades")) < BUY_RESCUE_MIN_TRADES:
        return "sample_insufficient"
    rescue_rate = _float(summary.get("actual_rescue_rate"))
    if rescue_rate < COMPARABLE_RESCUE_RATE_MIN or rescue_rate > COMPARABLE_RESCUE_RATE_MAX:
        return "coverage_out_of_bounds"
    if _float(summary.get("rescued_net_return_pct")) <= 0:
        return "diagnostic_only_negative_net"
    if _float(summary.get("nonnegative_net_fold_share")) < FOLLOW_UP_FOLD_SHARE_MIN:
        return "average_positive_but_fold_inconsistent"
    if _float(summary.get("max_positive_fold_net_share")) > FOLD_CONCENTRATION_MAX_SHARE:
        return "fold_concentration_risk"
    return "follow_up_candidate_proxy_only"


def _buy_rescue_precision_conclusion(summary: dict[str, Any]) -> str:
    if (
        _int(summary.get("eligible_folds")) <= 0
        or _int(summary.get("rescued_trades")) < BUY_RESCUE_PRECISION_MIN_TRADES
    ):
        return "sample_insufficient"
    rescue_rate = _float(summary.get("actual_rescue_rate"))
    if rescue_rate < PRECISION_RESCUE_RATE_MIN or rescue_rate > PRECISION_RESCUE_RATE_MAX:
        return "coverage_out_of_bounds"
    if _float(summary.get("rescued_avg_net_return_pct")) < BUY_RESCUE_PRECISION_MIN_NET_PER_TRADE_PCT:
        if (
            _float(summary.get("rescued_avg_gross_return_pct")) > 0.0
            and _float(summary.get("gross_minus_cost_per_trade_pct")) <= 0.0
        ):
            return "diagnostic_only_cost_drag"
        if _float(summary.get("rescued_net_return_pct")) <= 0.0:
            return "diagnostic_only_negative_net"
        return "diagnostic_only_low_net_per_trade"
    if _float(summary.get("nonnegative_net_fold_share")) < FOLLOW_UP_FOLD_SHARE_MIN:
        return "average_positive_but_fold_inconsistent"
    if _float(summary.get("max_positive_fold_net_share")) > FOLD_CONCENTRATION_MAX_SHARE:
        return "fold_concentration_risk"
    return "precision_follow_up_candidate_proxy_only"


def summarize_skip_targets(fold_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_target: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for fold in fold_summaries:
        for row in fold.get("buy_avoid_targets", []):
            if isinstance(row, dict):
                by_target[round(_float(row.get("target_skip_rate")), 6)].append(row)

    summaries: list[dict[str, Any]] = []
    for target, rows in sorted(by_target.items()):
        eligible = [row for row in rows if _int(row.get("baseline_trades")) > 0]
        baseline_trades = sum(_int(row.get("baseline_trades")) for row in rows)
        skipped_trades = sum(_int(row.get("skipped_trades")) for row in rows)
        baseline_net = sum(_float(row.get("baseline_net_return_pct")) for row in rows)
        kept_net = sum(_float(row.get("kept_net_return_pct")) for row in rows)
        improvement = kept_net - baseline_net
        positive_folds = sum(1 for row in eligible if _float(row.get("net_improvement_pct")) > 0.0)
        negative_folds = sum(1 for row in eligible if _float(row.get("net_improvement_pct")) < 0.0)
        no_change_folds = len(eligible) - positive_folds - negative_folds
        summary = {
            "target_skip_rate": target,
            "folds": len(rows),
            "eligible_folds": len(eligible),
            "baseline_trades": baseline_trades,
            "skipped_trades": skipped_trades,
            "kept_trades": sum(_int(row.get("kept_trades")) for row in rows),
            "actual_skip_rate": (skipped_trades / baseline_trades) if baseline_trades else 0.0,
            "baseline_net_return_pct": baseline_net,
            "kept_net_return_pct": kept_net,
            "net_improvement_pct": improvement,
            "positive_improvement_folds": positive_folds,
            "negative_improvement_folds": negative_folds,
            "no_change_folds": no_change_folds,
            "positive_improvement_fold_share": (positive_folds / len(eligible)) if eligible else 0.0,
            "coverage_band": f"{COMPARABLE_SKIP_RATE_MIN:.2f}..{COMPARABLE_SKIP_RATE_MAX:.2f}",
            "fold_consistency_min_share": FOLLOW_UP_FOLD_SHARE_MIN,
        }
        # Aggregate the per-fold random controls (folds are independent, so
        # expectations and variances add).  A target may only be called a real
        # loss-reduction candidate if this aggregate verdict is
        # 'filter_better_than_random_p95'.  docs/Buy-Avoid-Random-Control-Methodology.md
        summary["random_control_aggregate"] = aggregate_random_control_reports(
            [row.get("random_control") for row in rows]
        )
        summary["conclusion"] = _candidate_conclusion(summary)
        summaries.append(summary)
    return summaries


def summarize_rescue_targets(
    fold_summaries: list[dict[str, Any]],
    *,
    target_key: str = "buy_rescue_targets",
    precision: bool = False,
) -> list[dict[str, Any]]:
    by_target: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for fold in fold_summaries:
        for row in fold.get(target_key, []):
            if isinstance(row, dict):
                by_target[round(_float(row.get("target_rescue_rate")), 6)].append(row)

    summaries: list[dict[str, Any]] = []
    for target, rows in sorted(by_target.items()):
        eligible = [row for row in rows if _int(row.get("no_buy_candidates")) > 0]
        no_buy_candidates = sum(_int(row.get("no_buy_candidates")) for row in rows)
        rescued_trades = sum(_int(row.get("rescued_trades")) for row in rows)
        rescued_net = sum(_float(row.get("rescued_net_return_pct")) for row in rows)
        rescued_gross = sum(_float(row.get("rescued_gross_return_pct")) for row in rows)
        rescued_cost_drag = sum(_float(row.get("rescued_cost_drag_pct")) for row in rows)
        avg_gross_per_trade = rescued_gross / rescued_trades if rescued_trades else 0.0
        avg_net_per_trade = rescued_net / rescued_trades if rescued_trades else 0.0
        representative_trade_cost = _float(rows[0].get("trade_cost_pct")) if rows else 0.0
        positive_folds = sum(1 for row in eligible if _float(row.get("rescued_net_return_pct")) > 0.0)
        nonnegative_folds = sum(1 for row in eligible if _float(row.get("rescued_net_return_pct")) >= 0.0)
        negative_folds = sum(1 for row in eligible if _float(row.get("rescued_net_return_pct")) < 0.0)
        positive_fold_nets = [
            _float(row.get("rescued_net_return_pct"))
            for row in eligible
            if _float(row.get("rescued_net_return_pct")) > 0.0
        ]
        max_positive_fold_net_share = (
            max(positive_fold_nets) / sum(positive_fold_nets)
            if positive_fold_nets and sum(positive_fold_nets) > 0.0
            else 0.0
        )
        summary = {
            "target_rescue_rate": target,
            "folds": len(rows),
            "eligible_folds": len(eligible),
            "no_buy_candidates": no_buy_candidates,
            "rescued_trades": rescued_trades,
            "untouched_candidates": sum(_int(row.get("untouched_candidates")) for row in rows),
            "actual_rescue_rate": (rescued_trades / no_buy_candidates) if no_buy_candidates else 0.0,
            "rescued_gross_return_pct": rescued_gross,
            "rescued_net_return_pct": rescued_net,
            "rescued_cost_drag_pct": rescued_cost_drag,
            "rescued_avg_gross_return_pct": avg_gross_per_trade,
            "rescued_avg_net_return_pct": avg_net_per_trade,
            "required_gross_per_trade_pct": representative_trade_cost,
            "gross_minus_cost_per_trade_pct": avg_gross_per_trade - representative_trade_cost,
            "net_improvement_pct": rescued_net,
            "positive_net_folds": positive_folds,
            "nonnegative_net_folds": nonnegative_folds,
            "negative_net_folds": negative_folds,
            "positive_net_fold_share": (positive_folds / len(eligible)) if eligible else 0.0,
            "nonnegative_net_fold_share": (nonnegative_folds / len(eligible)) if eligible else 0.0,
            "max_positive_fold_net_share": max_positive_fold_net_share,
            "coverage_band": (
                f"{PRECISION_RESCUE_RATE_MIN:.4f}..{PRECISION_RESCUE_RATE_MAX:.4f}"
                if precision
                else f"{COMPARABLE_RESCUE_RATE_MIN:.2f}..{COMPARABLE_RESCUE_RATE_MAX:.2f}"
            ),
            "min_rescued_trades": BUY_RESCUE_PRECISION_MIN_TRADES if precision else BUY_RESCUE_MIN_TRADES,
            "min_avg_net_return_per_trade_pct": (
                BUY_RESCUE_PRECISION_MIN_NET_PER_TRADE_PCT if precision else None
            ),
            "fold_consistency_min_share": FOLLOW_UP_FOLD_SHARE_MIN,
            "fold_concentration_max_share": FOLD_CONCENTRATION_MAX_SHARE,
        }
        summary["conclusion"] = (
            _buy_rescue_precision_conclusion(summary) if precision else _buy_rescue_conclusion(summary)
        )
        summaries.append(summary)
    return summaries


def _fold_scored_metrics(scored_rows: list[dict[str, Any]], *, settings, trade_cost_pct: float, buy_threshold: float) -> dict[str, Any]:
    metrics = _metrics_from_scored_predictions(
        scored_rows=scored_rows,
        settings=settings,
        trade_cost_pct=trade_cost_pct,
        signal_confidence_threshold=buy_threshold,
    )
    future_returns = [_float(row.get("future_return_pct")) for row in scored_rows]
    actual_counts = Counter(str(row.get("actual_label")) for row in scored_rows)
    up_count = actual_counts.get("up", 0)
    down_count = actual_counts.get("down", 0)
    rows = len(scored_rows)
    avg_future = sum(future_returns) / rows if rows else 0.0
    if len(future_returns) >= 2:
        variance = sum((value - avg_future) ** 2 for value in future_returns) / (len(future_returns) - 1)
        future_stdev = math.sqrt(variance)
    else:
        future_stdev = 0.0
    return {
        "rows_evaluated": rows,
        "three_class_accuracy": _float(metrics.get("three_class_accuracy"), _float(metrics.get("overall_accuracy"))),
        "class_hit_rates": metrics.get("class_hit_rates") or {},
        "actual_label_counts": dict(actual_counts),
        "direction_bias": ((up_count - down_count) / rows) if rows else 0.0,
        "average_future_return_pct": avg_future,
        "future_return_stdev_pct": future_stdev,
        "trade_metrics": {
            "trades_taken": _int(metrics.get("trades_taken")),
            "buy_signal_hit_rate": _float(metrics.get("buy_signal_hit_rate"), _float(metrics.get("trade_hit_rate"))),
            "cumulative_net_return_pct": _float(metrics.get("cumulative_net_return_pct")),
            "virtual_direction_trades_taken": _int(metrics.get("virtual_direction_trades_taken")),
            "virtual_direction_hit_rate": _float(metrics.get("virtual_direction_hit_rate")),
            "virtual_direction_cumulative_net_return_pct": _float(
                metrics.get("virtual_direction_cumulative_net_return_pct")
            ),
        },
    }


def _regime_thresholds(folds: list[dict[str, Any]]) -> dict[str, Any]:
    direction_values = [_float(row.get("direction_bias")) for row in folds]
    volatility_values = [_float(row.get("future_return_stdev_pct")) for row in folds]
    return {
        "direction_bias_down_q30": _quantile(direction_values, 0.30),
        "direction_bias_up_q70": _quantile(direction_values, 0.70),
        "volatility_low_q30": _quantile(volatility_values, 0.30),
        "volatility_high_q70": _quantile(volatility_values, 0.70),
        "direction_definition": "down_bias <= q30, up_bias >= q70, otherwise range_bias",
        "volatility_definition": "high_vol >= q70, low_vol <= q30, otherwise mid_vol",
    }


def _assign_regime(fold: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, str]:
    direction_bias = _float(fold.get("direction_bias"))
    volatility = _float(fold.get("future_return_stdev_pct"))
    down_q = thresholds.get("direction_bias_down_q30")
    up_q = thresholds.get("direction_bias_up_q70")
    low_q = thresholds.get("volatility_low_q30")
    high_q = thresholds.get("volatility_high_q70")
    if down_q is not None and direction_bias <= float(down_q):
        direction = "down_bias"
    elif up_q is not None and direction_bias >= float(up_q):
        direction = "up_bias"
    else:
        direction = "range_bias"
    if high_q is not None and volatility >= float(high_q):
        volatility_label = "high_vol"
    elif low_q is not None and volatility <= float(low_q):
        volatility_label = "low_vol"
    else:
        volatility_label = "mid_vol"
    return {
        "direction_regime": direction,
        "volatility_regime": volatility_label,
        "combined_regime": f"{direction}/{volatility_label}",
    }


def _aggregate_regime_rows(folds: list[dict[str, Any]], key: str, reference_skip_rate: float) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fold in folds:
        groups[str(fold.get(key, "unknown"))].append(fold)
    rows: list[dict[str, Any]] = []
    for name, items in sorted(groups.items()):
        rows_evaluated = sum(_int(item.get("rows_evaluated")) for item in items)
        accuracy_numerator = sum(_float(item.get("three_class_accuracy")) * _int(item.get("rows_evaluated")) for item in items)
        trade_net = sum(_float((item.get("trade_metrics") or {}).get("cumulative_net_return_pct")) for item in items)
        virtual_net = sum(
            _float((item.get("trade_metrics") or {}).get("virtual_direction_cumulative_net_return_pct")) for item in items
        )
        reference_improvement = 0.0
        reference_actual_skip = 0
        reference_baseline = 0
        for item in items:
            for target in item.get("buy_avoid_targets", []):
                if round(_float(target.get("target_skip_rate")), 6) == round(float(reference_skip_rate), 6):
                    reference_improvement += _float(target.get("net_improvement_pct"))
                    reference_actual_skip += _int(target.get("skipped_trades"))
                    reference_baseline += _int(target.get("baseline_trades"))
        rows.append(
            {
                "regime": name,
                "folds": len(items),
                "rows_evaluated": rows_evaluated,
                "three_class_accuracy": (accuracy_numerator / rows_evaluated) if rows_evaluated else 0.0,
                "buy_signal_net_return_pct": trade_net,
                "virtual_direction_net_return_pct": virtual_net,
                "reference_target_skip_rate": float(reference_skip_rate),
                "reference_actual_skip_rate": (
                    reference_actual_skip / reference_baseline if reference_baseline else 0.0
                ),
                "reference_buy_avoid_net_improvement_pct": reference_improvement,
            }
        )
    return rows


def build_reports(
    *,
    project_root: Path,
    horizon_min: int,
    feature_set_name: str,
    train_max_rows: int,
    walk_forward_test_rows: int,
    walk_forward_step_rows: int,
    walk_forward_gap_rows: int,
    walk_forward_max_folds: int,
    calibration_rows: int,
    target_skip_rates: tuple[float, ...],
    target_rescue_rates: tuple[float, ...],
    precision_target_rescue_rates: tuple[float, ...],
    reference_skip_rate: float,
    trade_cost_pct: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for Cybos buy-avoid proxy diagnostics.")
    label_threshold = settings.strategy.label_threshold_15 if horizon_min == 15 else settings.strategy.label_threshold_60
    feature_names = _cybos_feature_set_names(feature_set_name)
    effective_trade_cost_pct = _effective_trade_cost_pct(settings, trade_cost_pct)
    buy_threshold = _effective_signal_confidence(settings)
    dataset_payload = _source_bar_train_validation_rows(
        sqlite_store=sqlite_store,
        source=CYBOS_HISTORICAL_SOURCE,
        horizon_min=horizon_min,
        threshold_pct=label_threshold,
        train_max_rows=train_max_rows,
        feature_set_name=feature_set_name,
    )
    rows = sorted(
        list(dataset_payload["train_rows"]) + list(dataset_payload["validation_rows"]),
        key=lambda item: (item["event_time"], str(item["symbol"])),
    )
    row_value_keys = sorted(
        {
            str(key)
            for row in rows[: min(len(rows), 1_000)]
            for key in (row.get("values") or {}).keys()
        }
    )
    runtime_baseline_replay = _runtime_baseline_replay_status(row_value_keys)
    fold_slices = _purged_walk_forward_slices(
        rows,
        min_train_rows=train_max_rows,
        test_rows=walk_forward_test_rows,
        step_rows=walk_forward_step_rows,
        gap_rows=walk_forward_gap_rows,
        horizon_min=horizon_min,
        max_train_rows=train_max_rows,
        max_folds=walk_forward_max_folds,
    )
    if not fold_slices:
        raise ValueError("Not enough Cybos rows for purged buy-avoid proxy diagnostics.")

    fold_summaries: list[dict[str, Any]] = []
    for fold_number, split in enumerate(fold_slices, start=1):
        train_start = int(split["train_start"])
        train_end = int(split["train_end"])
        test_start = int(split["test_start"])
        test_end = int(split["test_end"])
        fold_train = rows[train_start:train_end]
        fold_test = rows[test_start:test_end]
        if not fold_test:
            continue
        calibration_size = min(calibration_rows, max(1, len(fold_train) // 5))
        model_train = fold_train[:-calibration_size]
        calibration = fold_train[-calibration_size:]
        if len(model_train) < 5 or len(calibration) < 5 or not _has_complete_direction_labels(model_train):
            continue
        model = _fit_lightgbm_model(
            train_rows=model_train,
            feature_names=feature_names,
            feature_set_version=f"{settings.feature_set_version}-{feature_set_name}-buy-avoid-proxy",
            horizon_min=horizon_min,
            model_version=f"lightgbm-cybos-{feature_set_name.replace('_', '-')}-buy-avoid-h{horizon_min}-v1",
        )
        scored_calibration = _score_rows_with_model(
            rows=calibration,
            model=model,
            settings=settings,
            horizon_min=horizon_min,
            prediction_prefix=f"cybos-{feature_set_name}-buy-avoid-cal-{fold_number}",
            fold_number=fold_number,
        )
        scored_test = _score_rows_with_model(
            rows=fold_test,
            model=model,
            settings=settings,
            horizon_min=horizon_min,
            prediction_prefix=f"cybos-{feature_set_name}-buy-avoid-test-{fold_number}",
            fold_number=fold_number,
        )
        buy_avoid = _buy_avoid_fold_result(
            scored_calibration=scored_calibration,
            scored_test=scored_test,
            target_skip_rates=target_skip_rates,
            buy_threshold=buy_threshold,
            trade_cost_pct=effective_trade_cost_pct,
        )
        buy_rescue = _buy_rescue_fold_result(
            scored_calibration=scored_calibration,
            scored_test=scored_test,
            target_rescue_rates=target_rescue_rates,
            buy_threshold=buy_threshold,
            trade_cost_pct=effective_trade_cost_pct,
        )
        buy_rescue_precision = _buy_rescue_fold_result(
            scored_calibration=scored_calibration,
            scored_test=scored_test,
            target_rescue_rates=precision_target_rescue_rates,
            buy_threshold=buy_threshold,
            trade_cost_pct=effective_trade_cost_pct,
        )
        scored_metrics = _fold_scored_metrics(
            scored_test,
            settings=settings,
            trade_cost_pct=effective_trade_cost_pct,
            buy_threshold=buy_threshold,
        )
        fold_summaries.append(
            {
                "fold": fold_number,
                "train_start_row": train_start,
                "train_end_row": train_end - 1,
                "model_train_rows": len(model_train),
                "calibration_rows": len(calibration),
                "test_start_row": test_start,
                "test_end_row": test_start + len(scored_test) - 1,
                "train_start_event_time": fold_train[0]["event_time"].isoformat(),
                "train_end_event_time": fold_train[-1]["event_time"].isoformat(),
                "test_start_event_time": fold_test[0]["event_time"].isoformat(),
                "test_end_event_time": fold_test[-1]["event_time"].isoformat(),
                "actual_gap_minutes": float(split["actual_gap_minutes"]),
                "purge_horizon_min": int(split["purge_horizon_min"]),
                "baseline": buy_avoid["baseline"],
                "buy_avoid_targets": buy_avoid["target_results"],
                "buy_rescue": {
                    "no_buy_candidates": buy_rescue["no_buy_candidates"],
                },
                "buy_rescue_targets": buy_rescue["target_results"],
                "buy_rescue_precision_targets": buy_rescue_precision["target_results"],
                **scored_metrics,
            }
        )
        print(
            f"completed fold {fold_number}/{len(fold_slices)} "
            f"test_rows={len(scored_test)} baseline_trades={buy_avoid['baseline']['trades']}",
            flush=True,
        )

    if not fold_summaries:
        raise ValueError("Cybos buy-avoid proxy did not produce any evaluation folds.")

    target_summaries = summarize_skip_targets(fold_summaries)
    rescue_summaries = summarize_rescue_targets(fold_summaries)
    rescue_precision_summaries = summarize_rescue_targets(
        fold_summaries,
        target_key="buy_rescue_precision_targets",
        precision=True,
    )
    thresholds = _regime_thresholds(fold_summaries)
    regime_folds: list[dict[str, Any]] = []
    for fold in fold_summaries:
        regime = _assign_regime(fold, thresholds)
        fold.update(regime)
        regime_folds.append(fold)

    generated_at = now_local(settings.timezone)
    source_overlap_note = (
        "latest-walk-forward-extreme-fold-regimes-h15 is an extreme-fold diagnostic for the current gate "
        "walk-forward. This report reuses the idea but scopes it to Cybos 5y proxy folds, so it is not a "
        "replacement for the existing extreme-fold report."
    )
    buy_avoid_report = {
        "review": "cybos_buy_avoid_proxy",
        "generated_at": generated_at.isoformat(),
        "source": CYBOS_HISTORICAL_SOURCE,
        "scope": "research_only_no_model_promotion_no_gate_change_no_order_change",
        "overlap_check": source_overlap_note,
        "feature_set_name": feature_set_name,
        "feature_names": feature_names,
        "horizon_min": horizon_min,
        "label_threshold_pct": label_threshold,
        "trade_cost_pct": effective_trade_cost_pct,
        "baseline_candidate_policy_name": "lightgbm_self_filter_buy_avoid_proxy",
        "baseline_policy_scope": "Cybos LightGBM self-filter candidate set, not runtime baseline order decision.",
        "baseline_buy_policy": "predicted_label=up and probability_up >= signal_confidence_threshold",
        "runtime_baseline_replay": runtime_baseline_replay,
        "signal_confidence_threshold": buy_threshold,
        "kis_shadow_reference": {
            "down_threshold_0_40_skip_rate": 0.3665,
            "transfer_policy": "Do not port numeric 0.40 to Cybos; compare by skip-rate coverage instead.",
        },
        "settings": {
            "train_max_rows": train_max_rows,
            "walk_forward_test_rows": walk_forward_test_rows,
            "walk_forward_step_rows": walk_forward_step_rows,
            "walk_forward_gap_rows": walk_forward_gap_rows,
            "purge_mode": "event_time_strict_after_horizon",
            "purge_horizon_min": horizon_min,
            "walk_forward_max_folds": walk_forward_max_folds,
            "calibration_rows": calibration_rows,
            "target_skip_rates": list(target_skip_rates),
            "target_rescue_rates": list(target_rescue_rates),
            "precision_target_rescue_rates": list(precision_target_rescue_rates),
            "coverage_band": [COMPARABLE_SKIP_RATE_MIN, COMPARABLE_SKIP_RATE_MAX],
            "follow_up_fold_share_min": FOLLOW_UP_FOLD_SHARE_MIN,
        },
        "dataset": {
            "symbols": len(dataset_payload["symbols"]),
            "trade_dates": len(dataset_payload["trade_dates"]),
            "source_rows": dataset_payload["source_rows"],
            "labeled_rows": dataset_payload["labeled_rows"],
            "label_counts": dataset_payload["label_counts"],
            "first_event_time": dataset_payload["first_event_time"],
            "last_event_time": dataset_payload["last_event_time"],
            "validation_start_date": dataset_payload["validation_start_date"],
        },
        "target_summaries": target_summaries,
        "fold_summaries": fold_summaries,
        "decision": _overall_buy_avoid_decision(target_summaries),
    }
    rescue_report = {
        "review": "cybos_rescue_proxy",
        "generated_at": generated_at.isoformat(),
        "source": CYBOS_HISTORICAL_SOURCE,
        "scope": "research_only_no_model_promotion_no_gate_change_no_order_change",
        "feature_set_name": feature_set_name,
        "feature_names": feature_names,
        "horizon_min": horizon_min,
        "label_threshold_pct": label_threshold,
        "trade_cost_pct": effective_trade_cost_pct,
        "hypothesis_rank": {
            "buy_avoid": "primary",
            "buy_rescue": "secondary_exploratory",
            "hold_rescue": "separate_lifecycle_spec_only",
        },
        "multiple_testing_guardrails": {
            "thresholds_fixed_before_report_review": True,
            "report_all_thresholds": True,
            "do_not_promote_from_cybos_proxy_alone": True,
            "conclusion_labels": [
                "follow_up_candidate_proxy_only",
                "sample_insufficient",
                "coverage_out_of_bounds",
                "diagnostic_only_negative_net",
                "diagnostic_only_cost_drag",
                "diagnostic_only_low_net_per_trade",
                "average_positive_but_fold_inconsistent",
                "fold_concentration_risk",
                "precision_follow_up_candidate_proxy_only",
            ],
        },
        "baseline_candidate_policy_name": "lightgbm_self_filter_buy_avoid_proxy",
        "baseline_policy_scope": "Cybos LightGBM self-filter candidate set, not runtime baseline order decision.",
        "runtime_baseline_replay": runtime_baseline_replay,
        "buy_avoid_definition": {
            "candidate_pool": "predicted_label=up and probability_up >= signal_confidence_threshold",
            "action": "skip candidates with high probability_down",
            "target_skip_rates": list(target_skip_rates),
        },
        "buy_rescue_definition": {
            "experiment_mode": runtime_baseline_replay.get("recommended_experiment_mode"),
            "candidate_pool": "rows not selected by the Cybos LightGBM self-filter buy policy",
            "action": "virtually buy candidates with high probability_up",
            "target_rescue_rates": list(target_rescue_rates),
            "minimum_rescued_trades": BUY_RESCUE_MIN_TRADES,
            "coverage_band": [COMPARABLE_RESCUE_RATE_MIN, COMPARABLE_RESCUE_RATE_MAX],
        },
        "buy_rescue_precision_definition": {
            "experiment_mode": runtime_baseline_replay.get("recommended_experiment_mode"),
            "candidate_pool": "same proxy no-buy pool as buy_rescue_definition",
            "action": "virtually buy only rare high-conviction probability_up candidates",
            "target_rescue_rates": list(precision_target_rescue_rates),
            "minimum_rescued_trades": BUY_RESCUE_PRECISION_MIN_TRADES,
            "coverage_band": [PRECISION_RESCUE_RATE_MIN, PRECISION_RESCUE_RATE_MAX],
            "min_avg_net_return_per_trade_pct": BUY_RESCUE_PRECISION_MIN_NET_PER_TRADE_PCT,
            "interpretation": (
                "This answers whether buy-rescue failed only because the previous 5-30% grid was too broad. "
                "Passing this section still creates a KIS shadow design candidate only, not an order-policy change."
            ),
        },
        "hold_rescue_lifecycle_spec": {
            "status": "not_executed_in_this_report",
            "reason": "hold-rescue needs entry/hold/exit lifecycle simulation, not a single-row threshold test.",
            "required_next_steps": [
                "define entry policy",
                "define baseline exit policy",
                "define rescue hold extension rule",
                "cap max holding time",
                "compare drawdown and opportunity cost",
                "add synthetic lifecycle tests before full Cybos run",
            ],
        },
        "settings": {
            "train_max_rows": train_max_rows,
            "walk_forward_test_rows": walk_forward_test_rows,
            "walk_forward_step_rows": walk_forward_step_rows,
            "walk_forward_gap_rows": walk_forward_gap_rows,
            "walk_forward_max_folds": walk_forward_max_folds,
            "calibration_rows": calibration_rows,
            "target_skip_rates": list(target_skip_rates),
            "target_rescue_rates": list(target_rescue_rates),
            "precision_target_rescue_rates": list(precision_target_rescue_rates),
        },
        "dataset": buy_avoid_report["dataset"],
        "buy_avoid_target_summaries": target_summaries,
        "buy_rescue_target_summaries": rescue_summaries,
        "buy_rescue_precision_target_summaries": rescue_precision_summaries,
        "fold_summaries": fold_summaries,
        "decision": _overall_rescue_decision(target_summaries, rescue_summaries, rescue_precision_summaries),
    }
    regime_report = {
        "review": "cybos_regime_performance_diagnostic",
        "generated_at": generated_at.isoformat(),
        "source": CYBOS_HISTORICAL_SOURCE,
        "scope": "diagnostic_only_no_new_model_training_decision",
        "overlap_check": source_overlap_note,
        "feature_set_name": feature_set_name,
        "horizon_min": horizon_min,
        "regime_thresholds": thresholds,
        "reference_skip_rate": reference_skip_rate,
        "direction_regime_summary": _aggregate_regime_rows(regime_folds, "direction_regime", reference_skip_rate),
        "volatility_regime_summary": _aggregate_regime_rows(regime_folds, "volatility_regime", reference_skip_rate),
        "combined_regime_summary": _aggregate_regime_rows(regime_folds, "combined_regime", reference_skip_rate),
        "fold_summaries": [
            {
                "fold": fold["fold"],
                "test_start_event_time": fold["test_start_event_time"],
                "test_end_event_time": fold["test_end_event_time"],
                "direction_regime": fold["direction_regime"],
                "volatility_regime": fold["volatility_regime"],
                "combined_regime": fold["combined_regime"],
                "direction_bias": fold["direction_bias"],
                "average_future_return_pct": fold["average_future_return_pct"],
                "future_return_stdev_pct": fold["future_return_stdev_pct"],
                "three_class_accuracy": fold["three_class_accuracy"],
                "trade_metrics": fold["trade_metrics"],
            }
            for fold in regime_folds
        ],
    }
    return buy_avoid_report, regime_report, rescue_report


def _overall_buy_avoid_decision(target_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [row for row in target_summaries if row.get("conclusion") == "follow_up_candidate_proxy_only"]
    comparable = [
        row
        for row in target_summaries
        if COMPARABLE_SKIP_RATE_MIN <= _float(row.get("actual_skip_rate")) <= COMPARABLE_SKIP_RATE_MAX
    ]
    if candidates:
        best = max(
            candidates,
            key=lambda row: (
                _float(row.get("net_improvement_pct")),
                _float(row.get("positive_improvement_fold_share")),
            ),
        )
        return {
            "status": "follow_up_candidate_proxy_only",
            "recommended_action": "Keep KIS live buy-avoid shadow running; do not promote model or gate from Cybos proxy alone.",
            "best_target_skip_rate": best.get("target_skip_rate"),
            "reason": "Positive net improvement inside coverage band with >= 2/3 fold consistency.",
        }
    if comparable:
        best = max(comparable, key=lambda row: _float(row.get("net_improvement_pct")))
        return {
            "status": "diagnostic_only_hold",
            "recommended_action": "Do not change live/paper order policy. Use this as context for KIS shadow review.",
            "best_target_skip_rate": best.get("target_skip_rate"),
            "reason": best.get("conclusion"),
        }
    return {
        "status": "diagnostic_only_inconclusive",
        "recommended_action": "Do not change live/paper order policy. Coverage did not land in the practical skip-rate band.",
        "best_target_skip_rate": None,
        "reason": "No comparable skip-rate result.",
    }


def _overall_rescue_decision(
    target_summaries: list[dict[str, Any]],
    rescue_summaries: list[dict[str, Any]],
    rescue_precision_summaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    avoid_candidates = [row for row in target_summaries if row.get("conclusion") == "follow_up_candidate_proxy_only"]
    rescue_candidates = [
        row
        for row in rescue_summaries
        if row.get("conclusion") == "follow_up_candidate_proxy_only"
    ]
    precision_candidates = [
        row
        for row in (rescue_precision_summaries or [])
        if row.get("conclusion") == "precision_follow_up_candidate_proxy_only"
    ]
    if avoid_candidates and precision_candidates:
        best_precision = max(
            precision_candidates,
            key=lambda row: (
                _float(row.get("rescued_avg_net_return_pct")),
                _float(row.get("rescued_net_return_pct")),
                _float(row.get("nonnegative_net_fold_share")),
            ),
        )
        return {
            "status": "buy_avoid_and_precision_buy_rescue_proxy_candidates",
            "recommended_action": (
                "Keep KIS buy-avoid shadow sequential. Treat precision buy-rescue as a KIS no-trade logging "
                "and shadow-design candidate only; do not change paper/live order policy."
            ),
            "best_buy_rescue_target_rate": best_precision.get("target_rescue_rate"),
            "reason": "A rare high-conviction buy-rescue proxy passed the fixed precision criteria.",
        }
    if avoid_candidates and rescue_candidates:
        best_rescue = max(
            rescue_candidates,
            key=lambda row: (
                _float(row.get("rescued_net_return_pct")),
                _float(row.get("nonnegative_net_fold_share")),
            ),
        )
        return {
            "status": "buy_avoid_and_buy_rescue_proxy_candidates",
            "recommended_action": (
                "Keep KIS buy-avoid shadow sequential. Treat buy-rescue as Cybos proxy follow-up only "
                "until KIS no-trade decision logging is available."
            ),
            "best_buy_rescue_target_rate": best_rescue.get("target_rescue_rate"),
            "reason": "Both defensive avoid and offensive rescue proxy candidates passed fixed-grid criteria.",
        }
    if avoid_candidates:
        return {
            "status": "buy_avoid_candidate_only",
            "recommended_action": "Keep KIS buy-avoid shadow running; do not add KIS buy-rescue shadow yet.",
            "best_buy_rescue_target_rate": None,
            "reason": "Buy-avoid has proxy support, but buy-rescue did not pass fixed-grid criteria.",
        }
    if rescue_candidates:
        best_rescue = max(rescue_candidates, key=lambda row: _float(row.get("rescued_net_return_pct")))
        return {
            "status": "buy_rescue_proxy_candidate_only",
            "recommended_action": (
                "Do not add KIS live buy-rescue yet. Review fold concentration and data leakage risk first "
                "because this conflicts with the current stronger downside evidence."
            ),
            "best_buy_rescue_target_rate": best_rescue.get("target_rescue_rate"),
            "reason": "Only the secondary exploratory hypothesis passed.",
        }
    if precision_candidates:
        best_precision = max(
            precision_candidates,
            key=lambda row: _float(row.get("rescued_avg_net_return_pct")),
        )
        return {
            "status": "precision_buy_rescue_proxy_candidate_only",
            "recommended_action": (
                "Do not add KIS live buy-rescue yet. Review why buy-avoid did not pass and require KIS "
                "no-trade decision logging before any shadow expansion."
            ),
            "best_buy_rescue_target_rate": best_precision.get("target_rescue_rate"),
            "reason": "Only the rare high-conviction secondary exploratory hypothesis passed.",
        }
    return {
        "status": "diagnostic_only_no_rescue_candidate",
        "recommended_action": "Keep KIS buy-avoid shadow as the only live shadow expansion path for now.",
        "best_buy_rescue_target_rate": None,
        "reason": "No buy-rescue fixed-grid candidate passed.",
    }


def render_buy_avoid_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Cybos Buy-Avoid Proxy",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- source: `{report.get('source')}`",
        f"- scope: `{report.get('scope')}`",
        f"- feature_set: `{report.get('feature_set_name')}`",
        f"- horizon_min: `{report.get('horizon_min')}`",
        f"- trade_cost_pct: `{_float(report.get('trade_cost_pct')):.6f}`",
        f"- signal_confidence_threshold: `{_float(report.get('signal_confidence_threshold')):.6f}`",
        f"- decision: `{(report.get('decision') or {}).get('status')}`",
        f"- recommended_action: {(report.get('decision') or {}).get('recommended_action')}",
        "",
        "## Interpretation Guardrails",
        "",
        "- KIS `down_threshold=0.40` is not copied into Cybos.",
        "- Cybos compares by skip-rate coverage, especially the 30-40% band.",
        "- The `baseline` in this report is a Cybos LightGBM self-filter candidate set, not the runtime baseline order decision.",
        f"- Runtime baseline replay status: `{(report.get('runtime_baseline_replay') or {}).get('status')}`.",
        f"- Recommended rescue experiment mode: `{(report.get('runtime_baseline_replay') or {}).get('recommended_experiment_mode')}`.",
        "- This is not a model promotion, gate change, or order policy change.",
        "- Fold consistency requires improvement in at least 2/3 of eligible folds.",
        "",
        "## Target Summary",
        "",
        "| target_skip | actual_skip | folds | baseline_trades | skipped | baseline_net | kept_net | improvement | positive_fold_share | conclusion |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report.get("target_summaries", []):
        lines.append(
            "| "
            f"{_float(row.get('target_skip_rate')):.4f} | "
            f"{_float(row.get('actual_skip_rate')):.4f} | "
            f"{_int(row.get('eligible_folds'))} | "
            f"{_int(row.get('baseline_trades'))} | "
            f"{_int(row.get('skipped_trades'))} | "
            f"{_float(row.get('baseline_net_return_pct')):.6f} | "
            f"{_float(row.get('kept_net_return_pct')):.6f} | "
            f"{_float(row.get('net_improvement_pct')):.6f} | "
            f"{_float(row.get('positive_improvement_fold_share')):.4f} | "
            f"{row.get('conclusion')} |"
        )
    lines.extend(
        [
            "",
            "## Random Control (Same-Coverage Random Skip)",
            "",
            "improvement>0 만으로는 필터의 선별력이 증명되지 않는다 (baseline 평균이 음수이면 무작위 제거도 improvement를 양수로 만든다). "
            "아래 aggregate verdict가 `filter_better_than_random_p95`일 때만 손실 축소 후보로 부를 수 있다. "
            "기존 `decision.status`와 `conclusion` 문자열은 호환용이며, 해석은 `random_control_aggregate`가 우선한다. "
            "공식: `docs/Buy-Avoid-Random-Control-Methodology.md`",
            "",
            "| target_skip | folds_usable | actual_skipped_net | random_expected | excess | z_score | verdict |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report.get("target_summaries", []):
        aggregate = row.get("random_control_aggregate") or {}
        if aggregate.get("status") != "ok":
            lines.append(
                f"| {_float(row.get('target_skip_rate')):.4f} | - | - | - | - | - | {aggregate.get('status')} |"
            )
            continue
        z_value = aggregate.get("z_score")
        z_text = f"{_float(z_value):.4f}" if z_value is not None else "-"
        lines.append(
            "| "
            f"{_float(row.get('target_skip_rate')):.4f} | "
            f"{_int(aggregate.get('folds_usable'))} | "
            f"{_float(aggregate.get('actual_skipped_cumulative_net_pct')):.6f} | "
            f"{_float(aggregate.get('expected_random_skipped_sum_pct')):.6f} | "
            f"{_float(aggregate.get('excess_vs_random_pct')):.6f} | "
            f"{z_text} | "
            f"{aggregate.get('verdict')} |"
        )
    lines.extend(
        [
            "",
            "## Dataset",
            "",
            f"- symbols: `{(report.get('dataset') or {}).get('symbols')}`",
            f"- trade_dates: `{(report.get('dataset') or {}).get('trade_dates')}`",
            f"- labeled_rows: `{(report.get('dataset') or {}).get('labeled_rows')}`",
            f"- first_event_time: `{(report.get('dataset') or {}).get('first_event_time')}`",
            f"- last_event_time: `{(report.get('dataset') or {}).get('last_event_time')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def render_rescue_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Cybos Rescue Proxy",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- source: `{report.get('source')}`",
        f"- scope: `{report.get('scope')}`",
        f"- feature_set: `{report.get('feature_set_name')}`",
        f"- horizon_min: `{report.get('horizon_min')}`",
        f"- trade_cost_pct: `{_float(report.get('trade_cost_pct')):.6f}`",
        f"- decision: `{(report.get('decision') or {}).get('status')}`",
        f"- recommended_action: {(report.get('decision') or {}).get('recommended_action')}",
        "",
        "## Interpretation Guardrails",
        "",
        "- This is a fixed-grid exploratory report.",
        "- Buy-avoid is the primary hypothesis; buy-rescue is secondary and proxy-only.",
        "- Runtime baseline replay is not available when orderbook features are missing.",
        f"- Runtime baseline replay status: `{(report.get('runtime_baseline_replay') or {}).get('status')}`.",
        f"- Buy-rescue experiment mode: `{(report.get('buy_rescue_definition') or {}).get('experiment_mode')}`.",
        "- Hold-rescue is not executed here because it requires lifecycle simulation.",
        "- This report does not promote a model, change a gate, or change paper/live order policy.",
        "",
        "## Buy-Avoid Summary",
        "",
        "| target_skip | actual_skip | baseline_trades | skipped | baseline_net | kept_net | improvement | fold_share | conclusion |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report.get("buy_avoid_target_summaries", []):
        lines.append(
            "| "
            f"{_float(row.get('target_skip_rate')):.4f} | "
            f"{_float(row.get('actual_skip_rate')):.4f} | "
            f"{_int(row.get('baseline_trades'))} | "
            f"{_int(row.get('skipped_trades'))} | "
            f"{_float(row.get('baseline_net_return_pct')):.6f} | "
            f"{_float(row.get('kept_net_return_pct')):.6f} | "
            f"{_float(row.get('net_improvement_pct')):.6f} | "
            f"{_float(row.get('positive_improvement_fold_share')):.4f} | "
            f"{row.get('conclusion')} |"
        )
    lines.extend(
        [
            "",
            "## Buy-Rescue Summary",
            "",
            "| target_rescue | actual_rescue | no_buy_candidates | rescued | avg_gross | avg_net | gross_minus_cost | rescued_net | nonnegative_fold_share | max_positive_fold_share | conclusion |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report.get("buy_rescue_target_summaries", []):
        lines.append(
            "| "
            f"{_float(row.get('target_rescue_rate')):.4f} | "
            f"{_float(row.get('actual_rescue_rate')):.4f} | "
            f"{_int(row.get('no_buy_candidates'))} | "
            f"{_int(row.get('rescued_trades'))} | "
            f"{_float(row.get('rescued_avg_gross_return_pct')):.6f} | "
            f"{_float(row.get('rescued_avg_net_return_pct')):.6f} | "
            f"{_float(row.get('gross_minus_cost_per_trade_pct')):.6f} | "
            f"{_float(row.get('rescued_net_return_pct')):.6f} | "
            f"{_float(row.get('nonnegative_net_fold_share')):.4f} | "
            f"{_float(row.get('max_positive_fold_net_share')):.4f} | "
            f"{row.get('conclusion')} |"
        )
    lines.extend(
        [
            "",
            "## Precision Buy-Rescue Review",
            "",
            "- Purpose: check whether the earlier 5-30% rescue grid was simply too broad.",
            f"- Minimum average net return per rescued trade: `{BUY_RESCUE_PRECISION_MIN_NET_PER_TRADE_PCT:.4f}%`.",
            "- Passing this section still means `proxy-only shadow design candidate`, not a trading change.",
            "",
            "| target_rescue | actual_rescue | no_buy_candidates | rescued | avg_gross | avg_net | gross_minus_cost | rescued_net | nonnegative_fold_share | conclusion |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report.get("buy_rescue_precision_target_summaries", []):
        lines.append(
            "| "
            f"{_float(row.get('target_rescue_rate')):.4f} | "
            f"{_float(row.get('actual_rescue_rate')):.4f} | "
            f"{_int(row.get('no_buy_candidates'))} | "
            f"{_int(row.get('rescued_trades'))} | "
            f"{_float(row.get('rescued_avg_gross_return_pct')):.6f} | "
            f"{_float(row.get('rescued_avg_net_return_pct')):.6f} | "
            f"{_float(row.get('gross_minus_cost_per_trade_pct')):.6f} | "
            f"{_float(row.get('rescued_net_return_pct')):.6f} | "
            f"{_float(row.get('nonnegative_net_fold_share')):.4f} | "
            f"{row.get('conclusion')} |"
        )
    hold_spec = report.get("hold_rescue_lifecycle_spec") or {}
    lines.extend(
        [
            "",
            "## Hold-Rescue Lifecycle Spec",
            "",
            f"- status: `{hold_spec.get('status')}`",
            f"- reason: {hold_spec.get('reason')}",
            "- required_next_steps:",
        ]
    )
    for item in hold_spec.get("required_next_steps", []):
        lines.append(f"  - {item}")
    return "\n".join(lines) + "\n"


def render_regime_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Cybos Regime Performance Diagnostic",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- source: `{report.get('source')}`",
        f"- scope: `{report.get('scope')}`",
        f"- feature_set: `{report.get('feature_set_name')}`",
        f"- horizon_min: `{report.get('horizon_min')}`",
        f"- reference_skip_rate: `{_float(report.get('reference_skip_rate')):.4f}`",
        "",
        "## Regime Definitions",
        "",
        f"- direction: {(report.get('regime_thresholds') or {}).get('direction_definition')}",
        f"- direction_bias_down_q30: `{(report.get('regime_thresholds') or {}).get('direction_bias_down_q30')}`",
        f"- direction_bias_up_q70: `{(report.get('regime_thresholds') or {}).get('direction_bias_up_q70')}`",
        f"- volatility: {(report.get('regime_thresholds') or {}).get('volatility_definition')}",
        f"- volatility_low_q30: `{(report.get('regime_thresholds') or {}).get('volatility_low_q30')}`",
        f"- volatility_high_q70: `{(report.get('regime_thresholds') or {}).get('volatility_high_q70')}`",
        "",
        "## Direction Regime",
        "",
        "| regime | folds | rows | accuracy | buy_net | virtual_net | buy_avoid_delta | actual_skip |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("direction_regime_summary", []):
        lines.append(_regime_table_row(row))
    lines.extend(
        [
            "",
            "## Volatility Regime",
            "",
            "| regime | folds | rows | accuracy | buy_net | virtual_net | buy_avoid_delta | actual_skip |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("volatility_regime_summary", []):
        lines.append(_regime_table_row(row))
    lines.extend(
        [
            "",
            "## Combined Regime",
            "",
            "| regime | folds | rows | accuracy | buy_net | virtual_net | buy_avoid_delta | actual_skip |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("combined_regime_summary", []):
        lines.append(_regime_table_row(row))
    lines.extend(
        [
            "",
            "Note: This is diagnostic only. It defines where the current proxy struggles; it does not create a regime-specific model.",
        ]
    )
    return "\n".join(lines) + "\n"


def _regime_table_row(row: dict[str, Any]) -> str:
    return (
        "| "
        f"{row.get('regime')} | "
        f"{_int(row.get('folds'))} | "
        f"{_int(row.get('rows_evaluated'))} | "
        f"{_float(row.get('three_class_accuracy')):.6f} | "
        f"{_float(row.get('buy_signal_net_return_pct')):.6f} | "
        f"{_float(row.get('virtual_direction_net_return_pct')):.6f} | "
        f"{_float(row.get('reference_buy_avoid_net_improvement_pct')):.6f} | "
        f"{_float(row.get('reference_actual_skip_rate')):.4f} |"
    )


def _parse_float_tuple(raw: str) -> tuple[float, ...]:
    values = []
    for item in raw.split(","):
        item = item.strip()
        if item:
            values.append(float(item))
    return tuple(values)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Cybos buy-avoid proxy and regime diagnostics.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--feature-set-name", default="bar_context_momentum")
    parser.add_argument("--train-max-rows", type=int, default=100_000)
    parser.add_argument("--walk-forward-test-rows", type=int, default=50_000)
    parser.add_argument("--walk-forward-step-rows", type=int, default=100_000)
    parser.add_argument("--walk-forward-gap-rows", type=int, default=15)
    parser.add_argument("--walk-forward-max-folds", type=int, default=12)
    parser.add_argument("--calibration-rows", type=int, default=20_000)
    parser.add_argument("--target-skip-rates", default="0.20,0.30,0.3665,0.40,0.50")
    parser.add_argument("--target-rescue-rates", default="0.05,0.10,0.20,0.30")
    parser.add_argument(
        "--precision-target-rescue-rates",
        default=",".join(str(value) for value in DEFAULT_PRECISION_TARGET_RESCUE_RATES),
    )
    parser.add_argument("--reference-skip-rate", type=float, default=0.3665)
    parser.add_argument("--trade-cost-pct", type=float, default=CYBOS_PROFITABILITY_COST_PCT)
    parser.add_argument("--output-dir", default="runtime-data/reports/backtests")
    args = parser.parse_args()

    buy_avoid_report, regime_report, rescue_report = build_reports(
        project_root=Path(args.project_root),
        horizon_min=args.horizon_min,
        feature_set_name=args.feature_set_name,
        train_max_rows=args.train_max_rows,
        walk_forward_test_rows=args.walk_forward_test_rows,
        walk_forward_step_rows=args.walk_forward_step_rows,
        walk_forward_gap_rows=args.walk_forward_gap_rows,
        walk_forward_max_folds=args.walk_forward_max_folds,
        calibration_rows=args.calibration_rows,
        target_skip_rates=_parse_float_tuple(args.target_skip_rates),
        target_rescue_rates=_parse_float_tuple(args.target_rescue_rates),
        precision_target_rescue_rates=_parse_float_tuple(args.precision_target_rescue_rates),
        reference_skip_rate=args.reference_skip_rate,
        trade_cost_pct=args.trade_cost_pct,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    buy_json = output_dir / f"latest-cybos-buy-avoid-proxy-h{args.horizon_min}.json"
    buy_md = output_dir / f"latest-cybos-buy-avoid-proxy-h{args.horizon_min}.md"
    rescue_json = output_dir / f"latest-cybos-rescue-proxy-h{args.horizon_min}.json"
    rescue_md = output_dir / f"latest-cybos-rescue-proxy-h{args.horizon_min}.md"
    regime_json = output_dir / f"latest-cybos-regime-performance-h{args.horizon_min}.json"
    regime_md = output_dir / f"latest-cybos-regime-performance-h{args.horizon_min}.md"
    buy_json.write_text(json.dumps(buy_avoid_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    buy_md.write_text(render_buy_avoid_markdown(buy_avoid_report), encoding="utf-8")
    rescue_json.write_text(json.dumps(rescue_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rescue_md.write_text(render_rescue_markdown(rescue_report), encoding="utf-8")
    regime_json.write_text(json.dumps(regime_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    regime_md.write_text(render_regime_markdown(regime_report), encoding="utf-8")
    print(
        json.dumps(
            {
                "buy_avoid_report": str(buy_json),
                "rescue_report": str(rescue_json),
                "regime_report": str(regime_json),
                "buy_avoid_decision": buy_avoid_report.get("decision"),
                "rescue_decision": rescue_report.get("decision"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
