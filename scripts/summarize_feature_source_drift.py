#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ACTUAL_RAW_SOURCES = ("kis-ws", "kis-rest")
CYBOS_SOURCE = "cybos-historical"
DEFAULT_OUTPUT_NAME = "latest-feature-source-drift"
FEATURE_NAMES = (
    "avg_trade_size",
    "hl_range_pct",
    "mid_price",
    "return_1m_pct",
    "spread_bps",
    "bid_ask_imbalance",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _database_path_from_env(default_path: Path) -> Path:
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///")).expanduser()
    return default_path


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _fetch_scalar(connection: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> Any:
    row = connection.execute(query, params).fetchone()
    if row is None:
        return None
    return row[0]


def _load_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return value


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return round(sorted_values[0], 6)
    rank = (len(sorted_values) - 1) * pct
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return round(sorted_values[low], 6)
    weight = rank - low
    return round(sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight, 6)


def _stats(values: list[float], total_rows: int) -> dict[str, Any]:
    clean = sorted(value for value in values if math.isfinite(value))
    count = len(clean)
    if count == 0:
        return {
            "count": 0,
            "missing": max(total_rows, 0),
            "missing_ratio": 1.0 if total_rows > 0 else None,
            "mean": None,
            "stddev": None,
            "min": None,
            "p10": None,
            "p50": None,
            "p90": None,
            "max": None,
            "zero_ratio": None,
        }
    mean = sum(clean) / count
    variance = sum((value - mean) ** 2 for value in clean) / count
    zero_count = sum(1 for value in clean if abs(value) < 1e-12)
    missing = max(total_rows - count, 0)
    return {
        "count": count,
        "missing": missing,
        "missing_ratio": round(missing / total_rows, 6) if total_rows > 0 else None,
        "mean": round(mean, 6),
        "stddev": round(math.sqrt(variance), 6),
        "min": round(clean[0], 6),
        "p10": _percentile(clean, 0.10),
        "p50": _percentile(clean, 0.50),
        "p90": _percentile(clean, 0.90),
        "max": round(clean[-1], 6),
        "zero_ratio": round(zero_count / count, 6),
    }


def _feature_stats(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[float]] = {name: [] for name in FEATURE_NAMES}
    for row in rows:
        values = _load_json_object(str(row.get("values_json") or ""))
        for name in FEATURE_NAMES:
            value = _to_float(values.get(name))
            if value is not None:
                buckets[name].append(value)
    return {name: _stats(values, len(rows)) for name, values in buckets.items()}


def _date_bounds(trade_date: str) -> tuple[str, str]:
    start = date.fromisoformat(trade_date)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _source_summary(connection: sqlite3.Connection, source: str) -> dict[str, Any]:
    if not _table_exists(connection, "raw_market_ticks"):
        return {}
    row = connection.execute(
        """
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT symbol) AS symbols,
            COUNT(DISTINCT substr(event_time, 1, 10)) AS trade_dates,
            MIN(event_time) AS first_event_time,
            MAX(event_time) AS last_event_time
        FROM raw_market_ticks
        WHERE source = ?
        """,
        (source,),
    ).fetchone()
    return dict(row) if row is not None else {}


def _source_clause() -> str:
    return f"source IN ({', '.join('?' for _ in ACTUAL_RAW_SOURCES)})"


def _actual_minute_index(connection: sqlite3.Connection) -> dict[str, dict[str, set[str]]]:
    actual_minutes: dict[str, dict[str, set[str]]] = {}
    for table_name in ("raw_market_ticks", "raw_orderbook_ticks"):
        if not _table_exists(connection, table_name):
            continue
        query = f"""
            SELECT symbol, substr(event_time, 1, 16) AS minute_key
            FROM {table_name}
            WHERE {_source_clause()}
            GROUP BY symbol, minute_key
            ORDER BY minute_key, symbol
        """
        for row in connection.execute(query, ACTUAL_RAW_SOURCES):
            symbol = str(row["symbol"])
            minute_key = str(row["minute_key"])
            trade_date = minute_key[:10]
            actual_minutes.setdefault(trade_date, {}).setdefault(symbol, set()).add(minute_key)
    return actual_minutes


def _select_kis_dates(
    actual_minutes: dict[str, dict[str, set[str]]],
    *,
    cybos_last_event_time: str | None,
    recent_days: int,
) -> tuple[list[str], str]:
    available = sorted(actual_minutes)
    if not available:
        return [], "none"
    if cybos_last_event_time:
        cybos_last_date = cybos_last_event_time[:10]
        post_overlap = [trade_date for trade_date in available if trade_date > cybos_last_date]
        if post_overlap:
            return post_overlap[-recent_days:], "post_cybos_overlap"
    return available[-recent_days:], "recent_actual_fallback"


def _collect_kis_feature_rows(
    connection: sqlite3.Connection,
    actual_minutes: dict[str, dict[str, set[str]]],
    trade_dates: list[str],
    *,
    horizon_min: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not trade_dates or not _table_exists(connection, "feature_model_inputs"):
        return [], {}
    rows: list[dict[str, Any]] = []
    label_counts: Counter[str] = Counter()
    feature_query = """
        SELECT symbol, event_time, values_json
        FROM feature_model_inputs
        WHERE symbol = ?
          AND event_time >= ?
          AND event_time < ?
        ORDER BY event_time
    """
    label_query = """
        SELECT event_time, label
        FROM feature_labels
        WHERE symbol = ?
          AND event_time >= ?
          AND event_time < ?
          AND horizon_min = ?
    """
    labels_exist = _table_exists(connection, "feature_labels")
    for trade_date in trade_dates:
        start_at, end_at = _date_bounds(trade_date)
        for symbol, minute_keys in actual_minutes.get(trade_date, {}).items():
            for row in connection.execute(feature_query, (symbol, start_at, end_at)):
                if str(row["event_time"])[:16] not in minute_keys:
                    continue
                rows.append(dict(row))
            if labels_exist:
                for row in connection.execute(label_query, (symbol, start_at, end_at, horizon_min)):
                    if str(row["event_time"])[:16] not in minute_keys:
                        continue
                    label_counts[str(row["label"])] += 1
    return rows, dict(sorted(label_counts.items()))


def _collect_cybos_feature_rows(
    connection: sqlite3.Connection,
    *,
    horizon_min: int,
    sample_size: int,
    lookback_days: int,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    if not _table_exists(connection, "raw_market_ticks") or not _table_exists(connection, "feature_model_inputs"):
        return [], {}, {}
    summary = _source_summary(connection, CYBOS_SOURCE)
    last_event_time = str(summary.get("last_event_time") or "")
    if not last_event_time:
        return [], {}, summary
    last_date = date.fromisoformat(last_event_time[:10])
    start_date = last_date - timedelta(days=lookback_days)
    label_select = "labels.label AS label" if _table_exists(connection, "feature_labels") else "NULL AS label"
    label_join = (
        """
        LEFT JOIN feature_labels AS labels
          ON labels.symbol = inputs.symbol
         AND labels.event_time = inputs.event_time
         AND labels.horizon_min = ?
        """
        if _table_exists(connection, "feature_labels")
        else ""
    )
    params: tuple[Any, ...]
    if label_join:
        params = (horizon_min, CYBOS_SOURCE, start_date.isoformat(), sample_size)
    else:
        params = (CYBOS_SOURCE, start_date.isoformat(), sample_size)
    query = f"""
        SELECT
            inputs.symbol,
            inputs.event_time,
            inputs.values_json,
            {label_select}
        FROM raw_market_ticks AS ticks
        JOIN feature_model_inputs AS inputs
          ON inputs.symbol = ticks.symbol
         AND inputs.event_time = ticks.event_time
        {label_join}
        WHERE ticks.source = ?
          AND ticks.event_time >= ?
        ORDER BY ticks.event_time DESC, ticks.symbol
        LIMIT ?
    """
    rows = [dict(row) for row in connection.execute(query, params)]
    label_counts = Counter(str(row["label"]) for row in rows if row.get("label") is not None)
    return rows, dict(sorted(label_counts.items())), summary


def _sample_summary(rows: list[dict[str, Any]], label_distribution: dict[str, int]) -> dict[str, Any]:
    dates = sorted({str(row.get("event_time", ""))[:10] for row in rows if row.get("event_time")})
    symbols = sorted({str(row.get("symbol")) for row in rows if row.get("symbol")})
    return {
        "rows": len(rows),
        "symbols": len(symbols),
        "trade_dates": len(dates),
        "first_event_time": min((str(row.get("event_time")) for row in rows if row.get("event_time")), default=None),
        "last_event_time": max((str(row.get("event_time")) for row in rows if row.get("event_time")), default=None),
        "label_distribution_h15": label_distribution,
        "feature_stats": _feature_stats(rows),
    }


def _drift_findings(
    kis_stats: dict[str, dict[str, Any]],
    cybos_stats: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for feature_name in FEATURE_NAMES:
        kis = kis_stats.get(feature_name, {})
        cybos = cybos_stats.get(feature_name, {})
        kis_mean = kis.get("mean")
        cybos_mean = cybos.get("mean")
        kis_median = kis.get("p50")
        cybos_median = cybos.get("p50")
        cybos_std = cybos.get("stddev")
        kis_zero_ratio = kis.get("zero_ratio")
        cybos_zero_ratio = cybos.get("zero_ratio")
        mean_delta = None
        median_delta = None
        zscore_like = None
        zero_ratio_delta = None
        flags: list[str] = []
        if kis_mean is not None and cybos_mean is not None:
            mean_delta = round(float(kis_mean) - float(cybos_mean), 6)
            if cybos_std and abs(float(cybos_std)) > 1e-12:
                zscore_like = round(mean_delta / float(cybos_std), 6)
                if abs(zscore_like) >= 1.0:
                    flags.append("mean_delta_over_1_cybos_std")
            elif abs(mean_delta) > 1e-12:
                flags.append("cybos_zero_variance_with_mean_delta")
        if kis_median is not None and cybos_median is not None:
            median_delta = round(float(kis_median) - float(cybos_median), 6)
        if kis_zero_ratio is not None and cybos_zero_ratio is not None:
            zero_ratio_delta = round(float(kis_zero_ratio) - float(cybos_zero_ratio), 6)
            if abs(zero_ratio_delta) >= 0.5:
                flags.append("large_zero_ratio_delta")
        if feature_name in {"spread_bps", "bid_ask_imbalance"} and flags:
            flags.append("orderbook_feature_source_mismatch")
        if flags:
            findings.append(
                {
                    "feature": feature_name,
                    "flags": sorted(set(flags)),
                    "kis_mean": kis_mean,
                    "cybos_mean": cybos_mean,
                    "mean_delta": mean_delta,
                    "mean_delta_in_cybos_std": zscore_like,
                    "kis_p50": kis_median,
                    "cybos_p50": cybos_median,
                    "median_delta": median_delta,
                    "kis_zero_ratio": kis_zero_ratio,
                    "cybos_zero_ratio": cybos_zero_ratio,
                    "zero_ratio_delta": zero_ratio_delta,
                }
            )
    findings.sort(key=lambda item: (0 if "orderbook_feature_source_mismatch" in item["flags"] else 1, item["feature"]))
    return findings


def _assessment(findings: list[dict[str, Any]], kis_rows: int) -> dict[str, Any]:
    orderbook_findings = [
        item
        for item in findings
        if "orderbook_feature_source_mismatch" in item.get("flags", [])
    ]
    if kis_rows <= 0:
        posture = "insufficient_kis_live_sample"
        conclusion = "KIS live feature sample is empty; source transfer drift cannot be evaluated."
    elif orderbook_findings:
        posture = "source_drift_detected"
        conclusion = (
            "Cybos historical rows do not carry live orderbook feature distributions; "
            "Cybos-only candidates should not be treated as direct KIS live performance proxies."
        )
    elif findings:
        posture = "source_drift_watch"
        conclusion = "Non-orderbook feature drift exists; continue KIS accumulation before live promotion decisions."
    else:
        posture = "no_material_drift_detected"
        conclusion = "No material feature drift was detected in this sample."
    return {
        "posture": posture,
        "conclusion": conclusion,
        "orderbook_mismatch_features": [item["feature"] for item in orderbook_findings],
    }


def _write_reports(report: dict[str, Any], output_dir: Path, output_name: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{output_name}.json"
    md_path = output_dir / f"{output_name}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_format_markdown(report), encoding="utf-8")
    return json_path, md_path


def _format_markdown(report: dict[str, Any]) -> str:
    kis = report.get("samples", {}).get("kis_live", {})
    cybos = report.get("samples", {}).get("cybos_historical", {})
    assessment = report.get("assessment", {})
    lines = [
        "# Feature Source Drift Summary",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- posture: `{assessment.get('posture')}`",
        f"- conclusion: {assessment.get('conclusion')}",
        "",
        "## Samples",
        "",
        "| source | rows | symbols | trade_dates | first | last | labels_h15 |",
        "| --- | ---: | ---: | ---: | --- | --- | --- |",
        (
            f"| kis_live | {kis.get('rows', 0)} | {kis.get('symbols', 0)} | {kis.get('trade_dates', 0)} | "
            f"{kis.get('first_event_time')} | {kis.get('last_event_time')} | `{kis.get('label_distribution_h15', {})}` |"
        ),
        (
            f"| cybos_historical | {cybos.get('rows', 0)} | {cybos.get('symbols', 0)} | {cybos.get('trade_dates', 0)} | "
            f"{cybos.get('first_event_time')} | {cybos.get('last_event_time')} | `{cybos.get('label_distribution_h15', {})}` |"
        ),
        "",
        "## Drift Findings",
        "",
        "| feature | flags | kis_mean | cybos_mean | mean_delta/std | kis_zero | cybos_zero |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for finding in report.get("drift_findings", []):
        lines.append(
            "| {feature} | {flags} | {kis_mean} | {cybos_mean} | {z} | {kis_zero} | {cybos_zero} |".format(
                feature=finding.get("feature"),
                flags=", ".join(finding.get("flags", [])),
                kis_mean=finding.get("kis_mean"),
                cybos_mean=finding.get("cybos_mean"),
                z=finding.get("mean_delta_in_cybos_std"),
                kis_zero=finding.get("kis_zero_ratio"),
                cybos_zero=finding.get("cybos_zero_ratio"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `spread_bps` and `bid_ask_imbalance` are live orderbook features. If Cybos values are structurally zero while KIS values are distributed, Cybos-only training results are not a direct live-KIS proxy.",
            "- This report is diagnostic only. It does not promote models or change risk gates.",
            "",
        ]
    )
    return "\n".join(lines)


def summarize(
    database_path: Path,
    *,
    output_dir: Path | None = None,
    output_name: str = DEFAULT_OUTPUT_NAME,
    horizon_min: int = 15,
    kis_recent_days: int = 10,
    cybos_sample_size: int = 100_000,
    cybos_lookback_days: int = 45,
    write_reports: bool = True,
) -> dict[str, Any]:
    with _connect(database_path) as connection:
        actual_minutes = _actual_minute_index(connection)
        cybos_rows, cybos_labels, cybos_source_summary = _collect_cybos_feature_rows(
            connection,
            horizon_min=horizon_min,
            sample_size=cybos_sample_size,
            lookback_days=cybos_lookback_days,
        )
        kis_trade_dates, kis_date_selection = _select_kis_dates(
            actual_minutes,
            cybos_last_event_time=cybos_source_summary.get("last_event_time"),
            recent_days=kis_recent_days,
        )
        kis_rows, kis_labels = _collect_kis_feature_rows(
            connection,
            actual_minutes,
            kis_trade_dates,
            horizon_min=horizon_min,
        )

    kis_sample = _sample_summary(kis_rows, kis_labels)
    cybos_sample = _sample_summary(cybos_rows, cybos_labels)
    drift_findings = _drift_findings(kis_sample["feature_stats"], cybos_sample["feature_stats"])
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database_path": str(database_path),
        "horizon_min": horizon_min,
        "kis_date_selection": kis_date_selection,
        "kis_trade_dates": kis_trade_dates,
        "cybos_source_summary": cybos_source_summary,
        "cybos_sample_size_requested": cybos_sample_size,
        "cybos_lookback_days": cybos_lookback_days,
        "samples": {
            "kis_live": kis_sample,
            "cybos_historical": cybos_sample,
        },
        "drift_findings": drift_findings,
        "assessment": _assessment(drift_findings, int(kis_sample.get("rows") or 0)),
    }
    if write_reports:
        target_dir = output_dir or _repo_root() / "runtime-data" / "reports" / "data-quality"
        json_path, md_path = _write_reports(report, target_dir, output_name)
        report["output_paths"] = {"json": str(json_path), "markdown": str(md_path)}
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize feature distribution drift between KIS live and Cybos historical rows.")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite database path. Defaults to DATABASE_URL or runtime-data/dev.db.",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--output-name", default=DEFAULT_OUTPUT_NAME)
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--kis-recent-days", type=int, default=10)
    parser.add_argument("--cybos-sample-size", type=int, default=100_000)
    parser.add_argument("--cybos-lookback-days", type=int, default=45)
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
        kis_recent_days=args.kis_recent_days,
        cybos_sample_size=args.cybos_sample_size,
        cybos_lookback_days=args.cybos_lookback_days,
        write_reports=not args.no_write,
    )
    print(json.dumps(report["assessment"], ensure_ascii=False, sort_keys=True))
    if report.get("output_paths"):
        print(f"json={report['output_paths']['json']}")
        print(f"markdown={report['output_paths']['markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
