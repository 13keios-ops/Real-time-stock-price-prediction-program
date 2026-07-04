#!/usr/bin/env python3
"""Diagnose whether horizon returns are large enough to overcome costs.

This is a read-only research diagnostic. It writes JSON/Markdown reports only.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

try:
    from scripts.summarize_lightgbm_defensive_shadow import DEFAULT_DATABASE, DEFAULT_DIAGNOSTICS, _connect_readonly, _trade_cost_pct
except ImportError:  # pragma: no cover - direct script run
    from summarize_lightgbm_defensive_shadow import DEFAULT_DATABASE, DEFAULT_DIAGNOSTICS, _connect_readonly, _trade_cost_pct  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "research"
DEFAULT_HORIZONS = (15, 30, 60)

PREREGISTERED_CRITERIA = {
    "source_document": "docs/cowork-reports/2026-07-05-alternative-approaches-validation-plan.md",
    "experiment": "E6_cost_horizon_structure",
    "primary_question": "whether median absolute future return can overcome 2x trade_cost",
    "h15_structural_cost_warning": "median_abs_future_return_pct < 2 * trade_cost_pct",
    "if_warning": "filter tuning alone is unlikely to make h15 profitable; prioritize horizon extension, lower trade frequency, or execution cost improvement",
    "label_generation_scope": "do not create missing horizons in this diagnostic",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * pct
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return sorted_values[low]
    weight = pos - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def _breakeven_win_rate(values: list[float], cost_pct: float) -> float | None:
    gains = [value for value in values if value > 0]
    losses = [-value for value in values if value < 0]
    if not gains or not losses:
        return None
    avg_gain = mean(gains)
    avg_loss = mean(losses)
    denom = avg_gain + avg_loss
    if denom <= 0:
        return None
    return (avg_loss + cost_pct) / denom


def _horizon_values(connection: sqlite3.Connection, horizon_min: int) -> list[float]:
    rows = connection.execute(
        """
        SELECT DISTINCT symbol, event_time, future_return_pct
        FROM feature_labels
        WHERE horizon_min = ?
          AND future_return_pct IS NOT NULL
        """,
        (horizon_min,),
    ).fetchall()
    values: list[float] = []
    for _symbol, _event_time, value in rows:
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _summarize_horizon(values: list[float], horizon_min: int, trade_cost_pct: float) -> dict[str, Any]:
    if not values:
        return {
            "horizon_min": horizon_min,
            "status": "no_labels",
            "rows": 0,
        }
    abs_values = sorted(abs(value) for value in values)
    positive = [value for value in values if value > 0]
    negative = [value for value in values if value < 0]
    two_x_cost = 2 * trade_cost_pct
    median_abs = _percentile(abs_values, 0.5)
    structural_warning = bool(median_abs is not None and median_abs < two_x_cost)
    return {
        "horizon_min": horizon_min,
        "status": "ok",
        "rows": len(values),
        "mean_future_return_pct": mean(values),
        "mean_abs_future_return_pct": mean(abs_values),
        "median_abs_future_return_pct": median_abs,
        "p75_abs_future_return_pct": _percentile(abs_values, 0.75),
        "p90_abs_future_return_pct": _percentile(abs_values, 0.90),
        "positive_rows": len(positive),
        "negative_rows": len(negative),
        "flat_rows": len(values) - len(positive) - len(negative),
        "avg_positive_return_pct": mean(positive) if positive else None,
        "avg_negative_return_pct": mean(negative) if negative else None,
        "trade_cost_pct": trade_cost_pct,
        "two_x_trade_cost_pct": two_x_cost,
        "median_abs_less_than_2x_cost": structural_warning,
        "breakeven_win_rate_long_reference": _breakeven_win_rate(values, trade_cost_pct),
    }


def build_summary(
    *,
    database_path: Path,
    diagnostics_path: Path,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    trade_cost_pct = _trade_cost_pct(diagnostics_path)
    with _connect_readonly(database_path) as connection:
        horizon_summaries = [
            _summarize_horizon(_horizon_values(connection, horizon), horizon, trade_cost_pct)
            for horizon in horizons
        ]
    h15 = next((row for row in horizon_summaries if row.get("horizon_min") == 15), None)
    if not h15 or h15.get("status") != "ok":
        decision = "h15_labels_missing"
    elif h15.get("median_abs_less_than_2x_cost"):
        decision = "h15_median_move_below_2x_cost"
    else:
        decision = "h15_median_move_covers_2x_cost"
    return {
        "status": "ok" if any(row.get("status") == "ok" for row in horizon_summaries) else "no_labels",
        "generated_at": _now_iso(),
        "database_path": str(database_path),
        "trade_cost_pct": trade_cost_pct,
        "two_x_trade_cost_pct": 2 * trade_cost_pct,
        "preregistered_criteria": PREREGISTERED_CRITERIA,
        "decision": {
            "status": decision,
            "filter_tuning_only_warning": decision == "h15_median_move_below_2x_cost",
        },
        "horizons": horizon_summaries,
    }


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Cost / Horizon Diagnostics",
        "",
        f"- generated_at: `{summary.get('generated_at')}`",
        f"- status: `{summary.get('status')}`",
        f"- trade_cost_pct: `{summary.get('trade_cost_pct')}`",
        f"- two_x_trade_cost_pct: `{summary.get('two_x_trade_cost_pct')}`",
        f"- decision.status: `{summary.get('decision', {}).get('status')}`",
        f"- filter_tuning_only_warning: `{summary.get('decision', {}).get('filter_tuning_only_warning')}`",
        "",
        "## Preregistered Criteria",
        "",
        "- h15 `median_abs_future_return_pct < 2 * trade_cost_pct`이면 필터 튜닝만으로 흑자 전환이 어렵다고 본다.",
        "- 없는 horizon 라벨은 이번 진단에서 새로 만들지 않는다.",
        "",
        "## Horizon Summary",
        "",
        "| horizon | status | rows | median_abs | mean_abs | p75_abs | p90_abs | breakeven_win_rate | below_2x_cost |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary.get("horizons", []):
        lines.append(
            "| {horizon} | {status} | {rows} | {median} | {mean_abs} | {p75} | {p90} | {breakeven} | {below} |".format(
                horizon=row.get("horizon_min"),
                status=row.get("status"),
                rows=row.get("rows"),
                median=_fmt(row.get("median_abs_future_return_pct")),
                mean_abs=_fmt(row.get("mean_abs_future_return_pct")),
                p75=_fmt(row.get("p75_abs_future_return_pct")),
                p90=_fmt(row.get("p90_abs_future_return_pct")),
                breakeven=_fmt(row.get("breakeven_win_rate_long_reference")),
                below=row.get("median_abs_less_than_2x_cost"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(summary: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest-cost-horizon-diagnostics.json"
    md_path = output_dir / "latest-cost-horizon-diagnostics.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--diagnostics-path", type=Path, default=DEFAULT_DIAGNOSTICS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--horizons", type=int, nargs="+", default=list(DEFAULT_HORIZONS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_summary(
        database_path=args.database_path,
        diagnostics_path=args.diagnostics_path,
        horizons=tuple(args.horizons),
    )
    json_path, md_path = write_outputs(summary, args.output_dir)
    print(json.dumps({"status": summary.get("status"), "json_path": str(json_path), "md_path": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
