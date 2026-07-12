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
    from scripts.summarize_lightgbm_defensive_shadow import DEFAULT_DATABASE, DEFAULT_DIAGNOSTICS, _connect_readonly, _trade_cost_context
except ImportError:  # pragma: no cover - direct script run
    from summarize_lightgbm_defensive_shadow import DEFAULT_DATABASE, DEFAULT_DIAGNOSTICS, _connect_readonly, _trade_cost_context  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "research"
DEFAULT_HORIZONS = (15, 30, 60)
KIS_LIVE_START_DATE = "2026-06-11"

PREREGISTERED_CRITERIA = {
    "source_document": "docs/cowork-reports/2026-07-05-alternative-approaches-validation-plan.md",
    "experiment": "E6_cost_horizon_structure",
    "primary_question": "whether KIS live median absolute future return can overcome 2x trade_cost",
    "h15_cost_warning": "median_abs_future_return_pct < 2 * trade_cost_pct",
    "policy_population": "KIS live approximation: symbols seen in serving runtime tables and event_time >= 2026-06-11",
    "reference_population": "Cybos historical and all-source rows are reference only, not the final h15 policy conclusion",
    "if_warning": "filter tuning alone may be insufficient for h15; prioritize signal quality, horizon extension, lower trade frequency, or execution cost improvement",
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


def _live_symbols(connection: sqlite3.Connection) -> list[str]:
    symbols: set[str] = set()
    for table in ("serving_trade_signals", "serving_predictions"):
        try:
            rows = connection.execute(f"SELECT DISTINCT symbol FROM {table} WHERE symbol IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            continue
        symbols.update(str(row[0]) for row in rows if row and row[0])
    return sorted(symbols)


def _horizon_values(
    connection: sqlite3.Connection,
    horizon_min: int,
    *,
    source_key: str = "all",
    live_symbols: list[str] | None = None,
) -> list[float]:
    parameters: list[Any] = [horizon_min]
    source_filter = ""
    if source_key == "kis_live":
        source_filter = "AND event_time >= ?"
        parameters.append(KIS_LIVE_START_DATE)
        if live_symbols:
            placeholders = ",".join("?" for _ in live_symbols)
            source_filter += f" AND symbol IN ({placeholders})"
            parameters.extend(live_symbols)
    elif source_key == "cybos_historical":
        source_filter = "AND event_time < ?"
        parameters.append(KIS_LIVE_START_DATE)

    rows = connection.execute(
        f"""
        SELECT DISTINCT symbol, event_time, future_return_pct
        FROM feature_labels
        WHERE horizon_min = ?
          AND future_return_pct IS NOT NULL
          {source_filter}
        """,
        parameters,
    ).fetchall()
    values: list[float] = []
    for _symbol, _event_time, value in rows:
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _baseline_buy_values(connection: sqlite3.Connection, horizon_min: int) -> list[float]:
    try:
        rows = connection.execute(
            """
            SELECT DISTINCT fl.symbol, fl.event_time, fl.future_return_pct
            FROM serving_trade_signals AS s
            JOIN feature_labels AS fl
              ON fl.symbol = s.symbol
             AND fl.event_time = s.event_time
             AND fl.horizon_min = ?
            WHERE s.side = 'buy'
              AND s.allowed = 1
              AND s.event_time >= ?
              AND fl.future_return_pct IS NOT NULL
            """,
            (horizon_min, KIS_LIVE_START_DATE),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
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


def _with_row_share(summary: dict[str, Any], all_rows_by_horizon: dict[int, int]) -> dict[str, Any]:
    rows = int(summary.get("rows") or 0)
    all_rows = int(all_rows_by_horizon.get(int(summary.get("horizon_min") or 0), 0))
    summary["share_of_all_rows"] = (rows / all_rows) if all_rows else None
    return summary


def _summarize_source(
    *,
    connection: sqlite3.Connection,
    source_key: str,
    role: str,
    method: str,
    horizons: tuple[int, ...],
    trade_cost_pct: float,
    all_rows_by_horizon: dict[int, int],
    live_symbols: list[str],
) -> dict[str, Any]:
    horizon_summaries: list[dict[str, Any]] = []
    for horizon in horizons:
        if source_key == "kis_live_baseline_buy_join":
            values = _baseline_buy_values(connection, horizon)
        else:
            values = _horizon_values(connection, horizon, source_key=source_key, live_symbols=live_symbols)
        horizon_summaries.append(
            _with_row_share(_summarize_horizon(values, horizon, trade_cost_pct), all_rows_by_horizon)
        )
    return {
        "source_key": source_key,
        "role": role,
        "method": method,
        "horizons": horizon_summaries,
    }


def _decision_for_h15(source_key: str, h15: dict[str, Any] | None) -> dict[str, Any]:
    if not h15 or h15.get("status") != "ok":
        return {
            "status": f"{source_key}_h15_labels_missing",
            "policy_source": source_key,
            "filter_tuning_only_warning": False,
        }
    if h15.get("median_abs_less_than_2x_cost"):
        status = f"{source_key}_h15_median_move_below_2x_cost"
        warning = True
    else:
        status = f"{source_key}_h15_median_move_covers_2x_cost"
        warning = False
    return {
        "status": status,
        "policy_source": source_key,
        "filter_tuning_only_warning": warning,
        "median_abs_future_return_pct": h15.get("median_abs_future_return_pct"),
        "two_x_trade_cost_pct": h15.get("two_x_trade_cost_pct"),
        "rows": h15.get("rows"),
        "share_of_all_rows": h15.get("share_of_all_rows"),
    }


def _horizon_by_min(source_summary: dict[str, Any], horizon_min: int) -> dict[str, Any] | None:
    return next((row for row in source_summary.get("horizons", []) if row.get("horizon_min") == horizon_min), None)


def build_summary(
    *,
    database_path: Path,
    diagnostics_path: Path,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    cost_model = _trade_cost_context(diagnostics_path)
    trade_cost_pct = float(cost_model["round_trip_cost_pct"])
    with _connect_readonly(database_path) as connection:
        live_symbols = _live_symbols(connection)
        horizon_summaries = [
            _summarize_horizon(_horizon_values(connection, horizon), horizon, trade_cost_pct)
            for horizon in horizons
        ]
        all_rows_by_horizon = {
            int(row.get("horizon_min")): int(row.get("rows") or 0)
            for row in horizon_summaries
        }
        all_summary = {
            "source_key": "all",
            "role": "reference_all_sources",
            "method": "all distinct feature_labels rows with future_return_pct",
            "horizons": [_with_row_share(row, all_rows_by_horizon) for row in horizon_summaries],
        }
        source_summaries = [
            all_summary,
            _summarize_source(
                connection=connection,
                source_key="kis_live",
                role="policy_relevant",
                method=(
                    "approximation because feature_labels and curated_minute_bars have no source column: "
                    f"symbol in serving runtime symbols and event_time >= {KIS_LIVE_START_DATE}"
                ),
                horizons=horizons,
                trade_cost_pct=trade_cost_pct,
                all_rows_by_horizon=all_rows_by_horizon,
                live_symbols=live_symbols,
            ),
            _summarize_source(
                connection=connection,
                source_key="cybos_historical",
                role="reference_historical",
                method=(
                    "approximation because feature_labels and curated_minute_bars have no source column: "
                    f"event_time < {KIS_LIVE_START_DATE}"
                ),
                horizons=horizons,
                trade_cost_pct=trade_cost_pct,
                all_rows_by_horizon=all_rows_by_horizon,
                live_symbols=live_symbols,
            ),
            _summarize_source(
                connection=connection,
                source_key="kis_live_baseline_buy_join",
                role="diagnostic_runtime_buy_signals",
                method=f"serving_trade_signals side=buy and allowed=1 and event_time >= {KIS_LIVE_START_DATE} joined to feature_labels",
                horizons=horizons,
                trade_cost_pct=trade_cost_pct,
                all_rows_by_horizon=all_rows_by_horizon,
                live_symbols=live_symbols,
            ),
        ]
    kis_summary = next(row for row in source_summaries if row["source_key"] == "kis_live")
    kis_h15 = _horizon_by_min(kis_summary, 15)
    if not kis_h15 or kis_h15.get("status") != "ok":
        fallback_h15 = _horizon_by_min(all_summary, 15)
        decision = _decision_for_h15("all_fallback_no_kis_live_subset", fallback_h15)
    else:
        decision = _decision_for_h15("kis_live", kis_h15)
    return {
        "status": "ok" if any(row.get("status") == "ok" for row in horizon_summaries) else "no_labels",
        "generated_at": _now_iso(),
        "database_path": str(database_path),
        "trade_cost_pct": trade_cost_pct,
        "two_x_trade_cost_pct": 2 * trade_cost_pct,
        "cost_model_version": cost_model["version"],
        "cost_model": cost_model,
        "preregistered_criteria": PREREGISTERED_CRITERIA,
        "source_classification": {
            "has_source_column": False,
            "kis_live_start_date": KIS_LIVE_START_DATE,
            "live_symbols": live_symbols,
            "method_note": (
                "feature_labels and curated_minute_bars do not carry a source column in the current schema; "
                "source split is an approximation requested by review_ver_25."
            ),
        },
        "decision": decision,
        "horizons": all_summary["horizons"],
        "source_summaries": source_summaries,
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
        f"- cost_model_version: `{summary.get('cost_model_version')}`",
        f"- decision.status: `{summary.get('decision', {}).get('status')}`",
        f"- policy_source: `{summary.get('decision', {}).get('policy_source')}`",
        f"- filter_tuning_only_warning: `{summary.get('decision', {}).get('filter_tuning_only_warning')}`",
        "",
        "## Source Classification",
        "",
        f"- has_source_column: `{summary.get('source_classification', {}).get('has_source_column')}`",
        f"- kis_live_start_date: `{summary.get('source_classification', {}).get('kis_live_start_date')}`",
        f"- live_symbols: `{', '.join(summary.get('source_classification', {}).get('live_symbols') or [])}`",
        f"- method_note: {summary.get('source_classification', {}).get('method_note')}",
        "",
        "## Preregistered Criteria",
        "",
        "- h15 판단은 KIS live 근사 표본의 `median_abs_future_return_pct < 2 * trade_cost_pct` 여부로 본다.",
        "- Cybos historical과 all-source 표본은 참고용이며, h15 정책 결론을 단독 확정하지 않는다.",
        "- 없는 horizon 라벨은 이번 진단에서 새로 만들지 않는다.",
        "",
        "## Source / Horizon Summary",
        "",
        "| source | role | horizon | status | rows | share_all | median_abs | mean_abs | p75_abs | p90_abs | breakeven_win_rate | below_2x_cost |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for source in summary.get("source_summaries", []):
        for row in source.get("horizons", []):
            lines.append(
                "| {source} | {role} | {horizon} | {status} | {rows} | {share} | {median} | {mean_abs} | {p75} | {p90} | {breakeven} | {below} |".format(
                    source=source.get("source_key"),
                    role=source.get("role"),
                    horizon=row.get("horizon_min"),
                    status=row.get("status"),
                    rows=row.get("rows"),
                    share=_fmt(row.get("share_of_all_rows")),
                    median=_fmt(row.get("median_abs_future_return_pct")),
                    mean_abs=_fmt(row.get("mean_abs_future_return_pct")),
                    p75=_fmt(row.get("p75_abs_future_return_pct")),
                    p90=_fmt(row.get("p90_abs_future_return_pct")),
                    breakeven=_fmt(row.get("breakeven_win_rate_long_reference")),
                    below=row.get("median_abs_less_than_2x_cost"),
                )
            )
    lines.append("")
    lines.extend([
        "## Horizon Summary (All Sources, Backward Compatible)",
        "",
        "| horizon | status | rows | median_abs | mean_abs | p75_abs | p90_abs | breakeven_win_rate | below_2x_cost |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
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
