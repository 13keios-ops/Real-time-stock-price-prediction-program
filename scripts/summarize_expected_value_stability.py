#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


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


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _basic_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "p25": 0.0, "median": 0.0, "mean": 0.0, "p75": 0.0, "max": 0.0, "stdev": 0.0}
    return {
        "min": min(values),
        "p25": _percentile(values, 0.25),
        "median": statistics.median(values),
        "mean": statistics.mean(values),
        "p75": _percentile(values, 0.75),
        "max": max(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def _bootstrap_ci(values: list[float], *, samples: int, seed: int, aggregate: str) -> dict[str, float]:
    if not values:
        return {"samples": 0, "low": 0.0, "median": 0.0, "high": 0.0}
    rng = random.Random(seed)
    count = len(values)
    simulated: list[float] = []
    for _ in range(samples):
        draw = [values[rng.randrange(count)] for _ in range(count)]
        simulated.append(statistics.mean(draw) if aggregate == "mean" else sum(draw))
    return {
        "samples": samples,
        "low": _percentile(simulated, 0.025),
        "median": _percentile(simulated, 0.5),
        "high": _percentile(simulated, 0.975),
    }


def summarize(payload: dict[str, Any], *, bootstrap_samples: int, seed: int) -> dict[str, Any]:
    walk_forward = payload.get("walk_forward") if isinstance(payload.get("walk_forward"), dict) else payload
    folds = walk_forward.get("fold_summaries", []) if isinstance(walk_forward, dict) else []
    if not isinstance(folds, list):
        folds = []

    net_values = [_float(fold.get("cumulative_net_return_pct")) for fold in folds if isinstance(fold, dict)]
    gross_values = [_float(fold.get("cumulative_gross_return_pct")) for fold in folds if isinstance(fold, dict)]
    avg_net_values = [_float(fold.get("average_net_return_pct")) for fold in folds if isinstance(fold, dict)]
    hit_rates = [_float(fold.get("trade_hit_rate")) for fold in folds if isinstance(fold, dict) and _int(fold.get("trades_taken")) > 0]
    trades = [_int(fold.get("trades_taken")) for fold in folds if isinstance(fold, dict)]
    portfolio_values = [
        _float(fold.get("portfolio_return_pct"))
        for fold in folds
        if isinstance(fold, dict) and fold.get("portfolio_return_pct") is not None
    ]

    positive = sum(1 for fold in folds if isinstance(fold, dict) and _int(fold.get("trades_taken")) > 0 and _float(fold.get("cumulative_net_return_pct")) > 0)
    negative = sum(1 for fold in folds if isinstance(fold, dict) and _int(fold.get("trades_taken")) > 0 and _float(fold.get("cumulative_net_return_pct")) < 0)
    no_trade = sum(1 for fold in folds if isinstance(fold, dict) and _int(fold.get("trades_taken")) == 0)
    flat = len(folds) - positive - negative - no_trade
    threshold_counts = Counter(
        str(fold.get("selected_threshold"))
        for fold in folds
        if isinstance(fold, dict) and fold.get("selected_threshold") is not None
    )

    ci_sum = _bootstrap_ci(net_values, samples=bootstrap_samples, seed=seed, aggregate="sum")
    ci_mean = _bootstrap_ci(avg_net_values, samples=bootstrap_samples, seed=seed + 1, aggregate="mean")
    reliability_flags: list[str] = []
    if len(folds) < 20:
        reliability_flags.append("low_fold_count")
    if no_trade:
        reliability_flags.append("contains_no_trade_folds")
    if ci_sum["low"] <= 0 <= ci_sum["high"]:
        reliability_flags.append("bootstrap_ci_crosses_zero")
    if _float(walk_forward.get("trade_hit_rate")) < 0.33:
        reliability_flags.append("hit_rate_near_random_or_lower")

    if _float(walk_forward.get("trade_sum_net_return_pct")) <= 0:
        conclusion = "hold: cost-adjusted trade-sum return is negative."
    elif ci_sum["low"] <= 0:
        conclusion = "hold: positive headline is not stable at fold bootstrap level."
    else:
        conclusion = "candidate: fold bootstrap stayed positive; still requires out-of-sample review."

    return {
        "review": "expected_value_stability",
        "completed_at": datetime.now().astimezone().isoformat(),
        "source_report": payload.get("report_json_path"),
        "source": payload.get("source"),
        "feature_set_name": payload.get("feature_set_name"),
        "horizon_min": payload.get("horizon_min"),
        "trade_cost_pct": walk_forward.get("trade_cost_pct"),
        "headline": {
            "folds": walk_forward.get("folds"),
            "rows_evaluated": walk_forward.get("rows_evaluated"),
            "trades_taken": walk_forward.get("trades_taken"),
            "overall_accuracy": walk_forward.get("overall_accuracy"),
            "trade_hit_rate": walk_forward.get("trade_hit_rate"),
            "trade_sum_net_return_pct": walk_forward.get("trade_sum_net_return_pct"),
            "portfolio_return_pct": walk_forward.get("portfolio_return_pct"),
            "portfolio_return_model": walk_forward.get("portfolio_return_model"),
            "portfolio_return_caveat": walk_forward.get("portfolio_return_caveat"),
        },
        "fold_distribution": {
            "folds": len(folds),
            "positive_net_folds": positive,
            "negative_net_folds": negative,
            "flat_net_folds": flat,
            "no_trade_folds": no_trade,
            "trades": _basic_stats([float(item) for item in trades]),
            "net_return_pct": _basic_stats(net_values),
            "gross_return_pct": _basic_stats(gross_values),
            "average_net_return_pct": _basic_stats(avg_net_values),
            "trade_hit_rate": _basic_stats(hit_rates),
            "portfolio_return_pct": _basic_stats(portfolio_values),
            "selected_threshold_counts": dict(sorted(threshold_counts.items())),
        },
        "bootstrap": {
            "fold_sum_net_return_pct_ci95": ci_sum,
            "fold_average_net_return_pct_ci95": ci_mean,
        },
        "reliability_flags": reliability_flags,
        "conclusion": conclusion,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    headline = summary["headline"]
    dist = summary["fold_distribution"]
    bootstrap = summary["bootstrap"]
    lines = [
        "# Expected-Value Stability Review",
        "",
        f"- source: `{summary.get('source')}`",
        f"- feature_set_name: `{summary.get('feature_set_name')}`",
        f"- horizon_min: `{summary.get('horizon_min')}`",
        f"- trade_cost_pct: `{_float(summary.get('trade_cost_pct')):.6f}`",
        f"- folds: `{headline.get('folds')}`",
        f"- trades_taken: `{headline.get('trades_taken')}`",
        f"- trade_hit_rate: `{_float(headline.get('trade_hit_rate')):.6f}`",
        f"- trade_sum_net_return_pct: `{_float(headline.get('trade_sum_net_return_pct')):.6f}`",
        f"- portfolio_return_pct: `{_float(headline.get('portfolio_return_pct')):.6f}`",
        f"- portfolio_return_model: `{headline.get('portfolio_return_model')}`",
        "",
        "## Fold Distribution",
        "",
        f"- positive_net_folds: `{dist['positive_net_folds']}`",
        f"- negative_net_folds: `{dist['negative_net_folds']}`",
        f"- flat_net_folds: `{dist['flat_net_folds']}`",
        f"- no_trade_folds: `{dist['no_trade_folds']}`",
        f"- trades_per_fold_median: `{dist['trades']['median']:.6f}`",
        f"- trades_per_fold_min_max: `{dist['trades']['min']:.6f}..{dist['trades']['max']:.6f}`",
        f"- net_return_pct_median: `{dist['net_return_pct']['median']:.6f}`",
        f"- net_return_pct_min_max: `{dist['net_return_pct']['min']:.6f}..{dist['net_return_pct']['max']:.6f}`",
        f"- trade_hit_rate_median: `{dist['trade_hit_rate']['median']:.6f}`",
        f"- selected_threshold_counts: `{json.dumps(dist['selected_threshold_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Bootstrap",
        "",
        f"- fold_sum_net_return_pct_ci95: `{bootstrap['fold_sum_net_return_pct_ci95']['low']:.6f}..{bootstrap['fold_sum_net_return_pct_ci95']['high']:.6f}`",
        f"- fold_average_net_return_pct_ci95: `{bootstrap['fold_average_net_return_pct_ci95']['low']:.6f}..{bootstrap['fold_average_net_return_pct_ci95']['high']:.6f}`",
        "",
        "## Reliability",
        "",
        f"- flags: `{', '.join(summary['reliability_flags']) or 'none'}`",
        f"- conclusion: `{summary['conclusion']}`",
        "",
        "Note: portfolio_return_pct is a diagnostic proxy, not actual paper-account performance.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize expected-value fold stability without retraining.")
    parser.add_argument("--src", required=True, help="Expected-value JSON report path.")
    parser.add_argument("--out-json", required=True, help="Output JSON summary path.")
    parser.add_argument("--out-md", required=True, help="Output Markdown summary path.")
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260508)
    args = parser.parse_args()

    src = Path(args.src)
    payload = json.loads(src.read_text(encoding="utf-8"))
    payload["report_json_path"] = str(src)
    summary = summarize(payload, bootstrap_samples=args.bootstrap_samples, seed=args.seed)
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
