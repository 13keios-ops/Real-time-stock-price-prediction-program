#!/usr/bin/env python3
"""Summarize rank information coefficients for saved shadow model probabilities.

This is a read-only research diagnostic. It does not change active models,
thresholds, gates, paper orders, or live orders.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable

try:
    from scripts.summarize_lightgbm_defensive_shadow import (
        DEFAULT_DATABASE,
        DEFAULT_DIAGNOSTICS,
        _choose_label_threshold,
        _connect_readonly,
        _load_rows,
        _trade_cost_pct,
    )
except ImportError:  # pragma: no cover - direct script run
    from summarize_lightgbm_defensive_shadow import (  # type: ignore[no-redef]
        DEFAULT_DATABASE,
        DEFAULT_DIAGNOSTICS,
        _choose_label_threshold,
        _connect_readonly,
        _load_rows,
        _trade_cost_pct,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "research"
DEFAULT_MODEL_VERSION_TEMPLATE = "lightgbm-h{horizon_min}-v1"

PREREGISTERED_CRITERIA = {
    "source_document": "docs/cowork-reports/2026-07-05-alternative-approaches-validation-plan.md",
    "experiment": "E1_signal_information_coefficient",
    "primary_signal": "probability_down_vs_future_return_pct_on_baseline_buy_shadow_rows",
    "daily_metric": "Spearman rank correlation per trade_date",
    "proceed_to_filter_experiments": "mean_daily_ic <= -0.02 and t_stat <= -2.0",
    "signal_quality_insufficient": "abs(mean_daily_ic) < 0.02 or abs(t_stat) < 2.0",
    "reverse_signal_observation": "mean_daily_ic >= 0.02 and t_stat >= 2.0",
    "pooled_correlation_use": "reference_only_not_decision",
}


@dataclass(frozen=True)
class IcRow:
    trade_date: str
    symbol: str
    event_time: str
    probability_up: float | None
    probability_down: float | None
    future_return_pct: float


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _rank_average(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    idx = 0
    while idx < len(indexed):
        end = idx + 1
        while end < len(indexed) and indexed[end][1] == indexed[idx][1]:
            end += 1
        avg_rank = (idx + 1 + end) / 2.0
        for original_index, _value in indexed[idx:end]:
            ranks[original_index] = avg_rank
        idx = end
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = mean(xs)
    mean_y = mean(ys)
    dx = [value - mean_x for value in xs]
    dy = [value - mean_y for value in ys]
    denom_x = math.sqrt(sum(value * value for value in dx))
    denom_y = math.sqrt(sum(value * value for value in dy))
    if denom_x == 0.0 or denom_y == 0.0:
        return None
    return sum(x * y for x, y in zip(dx, dy)) / (denom_x * denom_y)


def spearman(xs: Iterable[float], ys: Iterable[float]) -> float | None:
    x_list = list(xs)
    y_list = list(ys)
    if len(x_list) != len(y_list) or len(x_list) < 2:
        return None
    return _pearson(_rank_average(x_list), _rank_average(y_list))


def _date_from_event_time(value: str) -> str:
    return value[:10]


def _rows_from_shadow(connection: sqlite3.Connection, horizon_min: int, label_threshold_pct: float) -> list[IcRow]:
    shadow_rows = _load_rows(connection, horizon_min, label_threshold_pct)
    result: list[IcRow] = []
    for row in shadow_rows:
        result.append(
            IcRow(
                trade_date=_date_from_event_time(row.event_time),
                symbol=row.symbol,
                event_time=row.event_time,
                probability_up=row.probability_up,
                probability_down=row.probability_down,
                future_return_pct=row.future_return_pct,
            )
        )
    return result


def _daily_ic(rows: list[IcRow], probability_field: str, *, min_daily_rows: int) -> list[dict[str, Any]]:
    by_date: dict[str, list[IcRow]] = {}
    for row in rows:
        by_date.setdefault(row.trade_date, []).append(row)
    daily: list[dict[str, Any]] = []
    for trade_date, date_rows in sorted(by_date.items()):
        pairs: list[tuple[float, float]] = []
        for row in date_rows:
            probability = getattr(row, probability_field)
            if probability is None:
                continue
            pairs.append((float(probability), row.future_return_pct))
        ic_value = spearman([p for p, _r in pairs], [r for _p, r in pairs]) if len(pairs) >= min_daily_rows else None
        daily.append(
            {
                "trade_date": trade_date,
                "rows": len(pairs),
                "ic": ic_value,
                "status": "ok" if ic_value is not None else "insufficient_rows_or_constant_values",
            }
        )
    return daily


def _summarize_daily(daily: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["ic"]) for row in daily if row.get("ic") is not None]
    if not values:
        return {
            "days_total": len(daily),
            "days_usable": 0,
            "mean_daily_ic": None,
            "std_daily_ic": None,
            "t_stat": None,
            "positive_days": 0,
            "negative_days": 0,
        }
    avg = mean(values)
    std = pstdev(values) if len(values) > 1 else 0.0
    if std > 0:
        t_stat = avg / std * math.sqrt(len(values))
    elif avg > 0:
        t_stat = math.inf
    elif avg < 0:
        t_stat = -math.inf
    else:
        t_stat = None
    return {
        "days_total": len(daily),
        "days_usable": len(values),
        "mean_daily_ic": avg,
        "std_daily_ic": std,
        "t_stat": t_stat,
        "positive_days": sum(1 for value in values if value > 0),
        "negative_days": sum(1 for value in values if value < 0),
    }


def _classify_down_signal(summary: dict[str, Any]) -> dict[str, Any]:
    mean_ic = summary.get("mean_daily_ic")
    t_stat = summary.get("t_stat")
    if mean_ic is None or t_stat is None:
        return {"decision": "insufficient_data", "proceed_to_e2_e3": False}
    if mean_ic <= -0.02 and t_stat <= -2.0:
        return {"decision": "down_signal_has_correct_direction_information", "proceed_to_e2_e3": True}
    if mean_ic >= 0.02 and t_stat >= 2.0:
        return {"decision": "reverse_signal_observed", "proceed_to_e2_e3": False}
    if abs(mean_ic) < 0.02 or abs(t_stat) < 2.0:
        return {"decision": "signal_quality_insufficient", "proceed_to_e2_e3": False}
    return {"decision": "criteria_not_met", "proceed_to_e2_e3": False}


def build_summary(
    *,
    database_path: Path,
    diagnostics_path: Path,
    horizon_min: int,
    min_daily_rows: int = 2,
) -> dict[str, Any]:
    with _connect_readonly(database_path) as connection:
        threshold = _choose_label_threshold(connection, horizon_min)
        if threshold is None:
            return {
                "status": "no_joinable_shadow_rows",
                "generated_at": _now_iso(),
                "horizon_min": horizon_min,
                "preregistered_criteria": PREREGISTERED_CRITERIA,
            }
        rows = _rows_from_shadow(connection, horizon_min, threshold)
    down_daily = _daily_ic(rows, "probability_down", min_daily_rows=min_daily_rows)
    up_daily = _daily_ic(rows, "probability_up", min_daily_rows=min_daily_rows)
    down_summary = _summarize_daily(down_daily)
    up_summary = _summarize_daily(up_daily)
    pooled_down_pairs = [(row.probability_down, row.future_return_pct) for row in rows if row.probability_down is not None]
    pooled_up_pairs = [(row.probability_up, row.future_return_pct) for row in rows if row.probability_up is not None]
    down_decision = _classify_down_signal(down_summary)
    return {
        "status": "ok" if rows else "no_joinable_shadow_rows",
        "generated_at": _now_iso(),
        "horizon_min": horizon_min,
        "model_version": DEFAULT_MODEL_VERSION_TEMPLATE.format(horizon_min=horizon_min),
        "database_path": str(database_path),
        "trade_cost_pct_reference": _trade_cost_pct(diagnostics_path),
        "label_threshold_pct": threshold,
        "joined_rows": len(rows),
        "trade_days": sorted({row.trade_date for row in rows}),
        "min_daily_rows": min_daily_rows,
        "preregistered_criteria": PREREGISTERED_CRITERIA,
        "probability_down": {
            "daily": down_daily,
            "summary": down_summary,
            "pooled_spearman_reference_only": spearman(
                [float(p) for p, _r in pooled_down_pairs], [r for _p, r in pooled_down_pairs]
            ),
            "decision": down_decision,
        },
        "probability_up": {
            "daily": up_daily,
            "summary": up_summary,
            "pooled_spearman_reference_only": spearman(
                [float(p) for p, _r in pooled_up_pairs], [r for _p, r in pooled_up_pairs]
            ),
        },
    }


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_markdown(summary: dict[str, Any]) -> str:
    down = summary.get("probability_down", {})
    down_summary = down.get("summary", {})
    up = summary.get("probability_up", {})
    up_summary = up.get("summary", {})
    decision = down.get("decision", {})
    lines = [
        "# Signal Information Coefficient h15",
        "",
        f"- generated_at: `{summary.get('generated_at')}`",
        f"- status: `{summary.get('status')}`",
        f"- horizon_min: `{summary.get('horizon_min')}`",
        f"- model_version: `{summary.get('model_version')}`",
        f"- joined_rows: `{summary.get('joined_rows')}`",
        f"- trade_days: `{len(summary.get('trade_days') or [])}`",
        f"- label_threshold_pct: `{summary.get('label_threshold_pct')}`",
        "",
        "## Preregistered Criteria",
        "",
        "- down 확률이 높을수록 미래 수익률이 낮아야 한다.",
        "- 통과: `mean_daily_ic <= -0.02` 그리고 `t_stat <= -2.0`.",
        "- `pooled_spearman_reference_only`는 참고용이며 판정에 쓰지 않는다.",
        "",
        "## Summary",
        "",
        "| signal | usable_days | mean_daily_ic | std_daily_ic | t_stat | pooled_reference |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| probability_down | {_fmt(down_summary.get('days_usable'), 0)} | {_fmt(down_summary.get('mean_daily_ic'))} | {_fmt(down_summary.get('std_daily_ic'))} | {_fmt(down_summary.get('t_stat'))} | {_fmt(down.get('pooled_spearman_reference_only'))} |",
        f"| probability_up | {_fmt(up_summary.get('days_usable'), 0)} | {_fmt(up_summary.get('mean_daily_ic'))} | {_fmt(up_summary.get('std_daily_ic'))} | {_fmt(up_summary.get('t_stat'))} | {_fmt(up.get('pooled_spearman_reference_only'))} |",
        "",
        "## Decision",
        "",
        f"- decision: `{decision.get('decision')}`",
        f"- proceed_to_e2_e3: `{decision.get('proceed_to_e2_e3')}`",
        "",
    ]
    daily = down.get("daily") or []
    if daily:
        lines.extend(["## Daily Down IC", "", "| date | rows | ic | status |", "| --- | ---: | ---: | --- |"])
        for row in daily:
            lines.append(
                f"| {row.get('trade_date')} | {row.get('rows')} | {_fmt(row.get('ic'))} | {row.get('status')} |"
            )
        lines.append("")
    return "\n".join(lines)


def write_outputs(summary: dict[str, Any], output_dir: Path, horizon_min: int) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"latest-signal-ic-h{horizon_min}.json"
    md_path = output_dir / f"latest-signal-ic-h{horizon_min}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--diagnostics-path", type=Path, default=DEFAULT_DIAGNOSTICS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--min-daily-rows", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_summary(
        database_path=args.database_path,
        diagnostics_path=args.diagnostics_path,
        horizon_min=args.horizon_min,
        min_daily_rows=args.min_daily_rows,
    )
    json_path, md_path = write_outputs(summary, args.output_dir, args.horizon_min)
    print(json.dumps({"status": summary.get("status"), "json_path": str(json_path), "md_path": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
