#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.summarize_feature_source_drift import (
    CYBOS_SOURCE,
    FEATURE_NAMES,
    _actual_minute_index,
    _connect,
    _database_path_from_env,
    _date_bounds,
    _load_json_object,
    _repo_root,
    _select_kis_dates,
    _source_summary,
    _table_exists,
    _to_float,
)


DEFAULT_OUTPUT_NAME = "latest-kis-live-feature-diagnostics"


def _collect_labeled_feature_rows(
    connection: sqlite3.Connection,
    actual_minutes: dict[str, dict[str, set[str]]],
    trade_dates: list[str],
    *,
    horizon_min: int,
) -> list[dict[str, Any]]:
    if not trade_dates or not _table_exists(connection, "feature_model_inputs") or not _table_exists(connection, "feature_labels"):
        return []
    rows: list[dict[str, Any]] = []
    feature_query = """
        SELECT symbol, event_time, values_json
        FROM feature_model_inputs
        WHERE symbol = ?
          AND event_time >= ?
          AND event_time < ?
        ORDER BY event_time
    """
    label_query = """
        SELECT event_time, label, future_return_pct
        FROM feature_labels
        WHERE symbol = ?
          AND event_time >= ?
          AND event_time < ?
          AND horizon_min = ?
    """
    for trade_date in trade_dates:
        start_at, end_at = _date_bounds(trade_date)
        for symbol, minute_keys in actual_minutes.get(trade_date, {}).items():
            labels_by_event_time: dict[str, dict[str, Any]] = {}
            for row in connection.execute(label_query, (symbol, start_at, end_at, horizon_min)):
                if str(row["event_time"])[:16] not in minute_keys:
                    continue
                labels_by_event_time[str(row["event_time"])] = {
                    "label": str(row["label"]),
                    "future_return_pct": _to_float(row["future_return_pct"]),
                }
            if not labels_by_event_time:
                continue
            for row in connection.execute(feature_query, (symbol, start_at, end_at)):
                event_time = str(row["event_time"])
                if event_time[:16] not in minute_keys or event_time not in labels_by_event_time:
                    continue
                label_row = labels_by_event_time[event_time]
                future_return_pct = label_row.get("future_return_pct")
                if future_return_pct is None:
                    continue
                values = _load_json_object(str(row["values_json"] or ""))
                feature_values = {
                    name: value
                    for name in FEATURE_NAMES
                    if (value := _to_float(values.get(name))) is not None
                }
                rows.append(
                    {
                        "symbol": symbol,
                        "event_time": event_time,
                        "trade_date": event_time[:10],
                        "label": label_row["label"],
                        "future_return_pct": future_return_pct,
                        "features": feature_values,
                    }
                )
    return rows


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    xs = [item[0] for item in pairs]
    ys = [item[1] for item in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    var_x = sum((value - mean_x) ** 2 for value in xs)
    var_y = sum((value - mean_y) ** 2 for value in ys)
    if var_x <= 1e-18 or var_y <= 1e-18:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    return round(cov / math.sqrt(var_x * var_y), 6)


def _label_distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get("label")) for row in rows).items()))


def _label_ratios(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"up": 0.0, "flat": 0.0, "down": 0.0}
    counts = Counter(str(row.get("label")) for row in rows)
    total = len(rows)
    return {
        "up": round(counts.get("up", 0) / total, 6),
        "flat": round(counts.get("flat", 0) / total, 6),
        "down": round(counts.get("down", 0) / total, 6),
    }


def _bucketize(rows: list[dict[str, Any]], feature_name: str, *, bucket_count: int) -> list[dict[str, Any]]:
    feature_rows = [
        row
        for row in rows
        if feature_name in row.get("features", {}) and math.isfinite(float(row["features"][feature_name]))
    ]
    feature_rows.sort(key=lambda row: (float(row["features"][feature_name]), str(row["event_time"]), str(row["symbol"])))
    if not feature_rows:
        return []
    actual_bucket_count = min(bucket_count, len(feature_rows))
    buckets: list[dict[str, Any]] = []
    for bucket_index in range(actual_bucket_count):
        start = math.floor(bucket_index * len(feature_rows) / actual_bucket_count)
        end = math.floor((bucket_index + 1) * len(feature_rows) / actual_bucket_count)
        bucket_rows = feature_rows[start:end]
        if not bucket_rows:
            continue
        feature_values = [float(row["features"][feature_name]) for row in bucket_rows]
        future_returns = [float(row["future_return_pct"]) for row in bucket_rows]
        buckets.append(
            {
                "bucket": bucket_index + 1,
                "rows": len(bucket_rows),
                "min_feature": round(min(feature_values), 6),
                "max_feature": round(max(feature_values), 6),
                "avg_feature": _mean(feature_values),
                "avg_future_return_pct": _mean(future_returns),
                "label_distribution": _label_distribution(bucket_rows),
                "label_ratios": _label_ratios(bucket_rows),
            }
        )
    return buckets


def _feature_diagnostics(rows: list[dict[str, Any]], *, bucket_count: int) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for feature_name in FEATURE_NAMES:
        pairs = [
            (float(row["features"][feature_name]), float(row["future_return_pct"]))
            for row in rows
            if feature_name in row.get("features", {})
        ]
        buckets = _bucketize(rows, feature_name, bucket_count=bucket_count)
        bottom = buckets[0] if buckets else {}
        top = buckets[-1] if buckets else {}
        top_bottom_return_delta = None
        top_bottom_up_ratio_delta = None
        if bottom and top:
            top_return = top.get("avg_future_return_pct")
            bottom_return = bottom.get("avg_future_return_pct")
            if top_return is not None and bottom_return is not None:
                top_bottom_return_delta = round(float(top_return) - float(bottom_return), 6)
            top_up_ratio = (top.get("label_ratios") or {}).get("up")
            bottom_up_ratio = (bottom.get("label_ratios") or {}).get("up")
            if top_up_ratio is not None and bottom_up_ratio is not None:
                top_bottom_up_ratio_delta = round(float(top_up_ratio) - float(bottom_up_ratio), 6)
        diagnostics.append(
            {
                "feature": feature_name,
                "rows": len(pairs),
                "pearson_future_return": _pearson(pairs),
                "top_bottom_future_return_delta_pct": top_bottom_return_delta,
                "top_bottom_up_ratio_delta": top_bottom_up_ratio_delta,
                "buckets": buckets,
            }
        )
    diagnostics.sort(
        key=lambda item: (
            abs(float(item.get("pearson_future_return") or 0.0)),
            abs(float(item.get("top_bottom_future_return_delta_pct") or 0.0)),
        ),
        reverse=True,
    )
    return diagnostics


def _sample_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = sorted({str(row.get("trade_date")) for row in rows if row.get("trade_date")})
    symbols = sorted({str(row.get("symbol")) for row in rows if row.get("symbol")})
    future_returns = [float(row["future_return_pct"]) for row in rows]
    return {
        "rows": len(rows),
        "symbols": len(symbols),
        "trade_dates": len(dates),
        "first_event_time": min((str(row.get("event_time")) for row in rows if row.get("event_time")), default=None),
        "last_event_time": max((str(row.get("event_time")) for row in rows if row.get("event_time")), default=None),
        "label_distribution": _label_distribution(rows),
        "avg_future_return_pct": _mean(future_returns),
    }


def _assessment(sample: dict[str, Any], diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    rows = int(sample.get("rows") or 0)
    trade_dates = int(sample.get("trade_dates") or 0)
    strongest = diagnostics[0] if diagnostics else {}
    strongest_corr = strongest.get("pearson_future_return")
    if rows < 3_000 or trade_dates < 3:
        posture = "sample_too_small"
        conclusion = "KIS live sample is still small; use diagnostics only as directional feature triage."
    elif strongest_corr is not None and abs(float(strongest_corr)) >= 0.05:
        posture = "weak_signal_watch"
        conclusion = "Some KIS live features show weak directional relationship; validate only after more live days accumulate."
    else:
        posture = "no_clear_single_feature_signal"
        conclusion = "No single KIS live feature shows a strong standalone relationship yet; keep accumulating live data."
    return {
        "posture": posture,
        "conclusion": conclusion,
        "strongest_feature": strongest.get("feature"),
        "strongest_feature_pearson": strongest_corr,
        "strongest_feature_top_bottom_delta_pct": strongest.get("top_bottom_future_return_delta_pct"),
    }


def _format_markdown(report: dict[str, Any]) -> str:
    sample = report.get("sample", {})
    assessment = report.get("assessment", {})
    lines = [
        "# KIS Live Feature Diagnostics",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- posture: `{assessment.get('posture')}`",
        f"- conclusion: {assessment.get('conclusion')}",
        "",
        "## Sample",
        "",
        f"- rows: `{sample.get('rows')}`",
        f"- symbols: `{sample.get('symbols')}`",
        f"- trade_dates: `{sample.get('trade_dates')}`",
        f"- range: `{sample.get('first_event_time')}..{sample.get('last_event_time')}`",
        f"- label_distribution: `{sample.get('label_distribution')}`",
        f"- avg_future_return_pct: `{sample.get('avg_future_return_pct')}`",
        "",
        "## Feature Ranking",
        "",
        "| feature | rows | pearson | top-bottom return delta | top-bottom up-ratio delta |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for item in report.get("feature_diagnostics", []):
        lines.append(
            f"| {item.get('feature')} | {item.get('rows')} | {item.get('pearson_future_return')} | "
            f"{item.get('top_bottom_future_return_delta_pct')} | {item.get('top_bottom_up_ratio_delta')} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This report is feature triage, not model promotion.",
            "- KIS live rows are still sparse compared with Cybos historical rows, so weak single-feature signals must be rechecked after more live days accumulate.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_reports(report: dict[str, Any], output_dir: Path, output_name: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{output_name}.json"
    md_path = output_dir / f"{output_name}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_format_markdown(report), encoding="utf-8")
    return json_path, md_path


def summarize(
    database_path: Path,
    *,
    output_dir: Path | None = None,
    output_name: str = DEFAULT_OUTPUT_NAME,
    horizon_min: int = 15,
    recent_days: int = 10,
    bucket_count: int = 5,
    write_reports: bool = True,
) -> dict[str, Any]:
    with _connect(database_path) as connection:
        actual_minutes = _actual_minute_index(connection)
        cybos_summary = _source_summary(connection, CYBOS_SOURCE)
        trade_dates, date_selection = _select_kis_dates(
            actual_minutes,
            cybos_last_event_time=cybos_summary.get("last_event_time"),
            recent_days=recent_days,
        )
        rows = _collect_labeled_feature_rows(connection, actual_minutes, trade_dates, horizon_min=horizon_min)

    sample = _sample_summary(rows)
    diagnostics = _feature_diagnostics(rows, bucket_count=bucket_count)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database_path": str(database_path),
        "horizon_min": horizon_min,
        "recent_days": recent_days,
        "bucket_count": bucket_count,
        "date_selection": date_selection,
        "trade_dates": trade_dates,
        "sample": sample,
        "feature_diagnostics": diagnostics,
        "assessment": _assessment(sample, diagnostics),
    }
    if write_reports:
        target_dir = output_dir or _repo_root() / "runtime-data" / "reports" / "data-quality"
        json_path, md_path = _write_reports(report, target_dir, output_name)
        report["output_paths"] = {"json": str(json_path), "markdown": str(md_path)}
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize KIS live feature relationship with future-return labels.")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite database path. Defaults to DATABASE_URL or runtime-data/dev.db.",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--output-name", default=DEFAULT_OUTPUT_NAME)
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--recent-days", type=int, default=10)
    parser.add_argument("--bucket-count", type=int, default=5)
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = _repo_root()
    database_path = args.db or _database_path_from_env(repo_root / "runtime-data" / "dev.db")
    report = summarize(
        database_path.expanduser(),
        output_dir=args.output_dir,
        output_name=args.output_name,
        horizon_min=args.horizon_min,
        recent_days=args.recent_days,
        bucket_count=args.bucket_count,
        write_reports=not args.no_write,
    )
    print(json.dumps(report["assessment"], ensure_ascii=False, sort_keys=True))
    if report.get("output_paths"):
        print(f"json={report['output_paths']['json']}")
        print(f"markdown={report['output_paths']['markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
