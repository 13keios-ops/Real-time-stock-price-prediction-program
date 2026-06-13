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
    _score_rows_with_model,
    _source_bar_train_validation_rows,
)
from app.utils.time import now_local


DEFAULT_TARGET_SKIP_RATES = (0.20, 0.30, 0.3665, 0.40, 0.50)
COMPARABLE_SKIP_RATE_MIN = 0.20
COMPARABLE_SKIP_RATE_MAX = 0.50
FOLLOW_UP_FOLD_SHARE_MIN = 2 / 3
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


def _is_buy_candidate(row: dict[str, Any], buy_threshold: float) -> bool:
    return str(row.get("predicted_label")) == "up" and _float(row.get("probability_up")) >= buy_threshold


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
        summary["conclusion"] = _candidate_conclusion(summary)
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
    reference_skip_rate: float,
    trade_cost_pct: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
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
    if len(rows) < train_max_rows + walk_forward_gap_rows + walk_forward_test_rows:
        raise ValueError("Not enough Cybos rows for buy-avoid proxy diagnostics.")
    train_end_values = list(
        range(train_max_rows, len(rows) - walk_forward_gap_rows - walk_forward_test_rows + 1, walk_forward_step_rows)
    )
    if walk_forward_max_folds > 0 and len(train_end_values) > walk_forward_max_folds:
        selected_indices = np.linspace(0, len(train_end_values) - 1, walk_forward_max_folds, dtype=int)
        train_end_values = [train_end_values[int(index)] for index in selected_indices]

    fold_summaries: list[dict[str, Any]] = []
    for fold_number, train_end in enumerate(train_end_values, start=1):
        train_start = max(0, train_end - train_max_rows)
        fold_train = rows[train_start:train_end]
        test_start = train_end + walk_forward_gap_rows
        fold_test = rows[test_start : test_start + walk_forward_test_rows]
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
                "baseline": buy_avoid["baseline"],
                "buy_avoid_targets": buy_avoid["target_results"],
                **scored_metrics,
            }
        )
        print(
            f"completed fold {fold_number}/{len(train_end_values)} "
            f"test_rows={len(scored_test)} baseline_trades={buy_avoid['baseline']['trades']}",
            flush=True,
        )

    if not fold_summaries:
        raise ValueError("Cybos buy-avoid proxy did not produce any evaluation folds.")

    target_summaries = summarize_skip_targets(fold_summaries)
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
            "walk_forward_max_folds": walk_forward_max_folds,
            "calibration_rows": calibration_rows,
            "target_skip_rates": list(target_skip_rates),
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
    return buy_avoid_report, regime_report


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
    parser.add_argument("--reference-skip-rate", type=float, default=0.3665)
    parser.add_argument("--trade-cost-pct", type=float, default=CYBOS_PROFITABILITY_COST_PCT)
    parser.add_argument("--output-dir", default="runtime-data/reports/backtests")
    args = parser.parse_args()

    buy_avoid_report, regime_report = build_reports(
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
        reference_skip_rate=args.reference_skip_rate,
        trade_cost_pct=args.trade_cost_pct,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    buy_json = output_dir / f"latest-cybos-buy-avoid-proxy-h{args.horizon_min}.json"
    buy_md = output_dir / f"latest-cybos-buy-avoid-proxy-h{args.horizon_min}.md"
    regime_json = output_dir / f"latest-cybos-regime-performance-h{args.horizon_min}.json"
    regime_md = output_dir / f"latest-cybos-regime-performance-h{args.horizon_min}.md"
    buy_json.write_text(json.dumps(buy_avoid_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    buy_md.write_text(render_buy_avoid_markdown(buy_avoid_report), encoding="utf-8")
    regime_json.write_text(json.dumps(regime_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    regime_md.write_text(render_regime_markdown(regime_report), encoding="utf-8")
    print(
        json.dumps(
            {
                "buy_avoid_report": str(buy_json),
                "regime_report": str(regime_json),
                "decision": buy_avoid_report.get("decision"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
