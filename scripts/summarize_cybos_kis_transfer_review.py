#!/usr/bin/env python3
"""Compare Cybos historical and KIS live feature/return relationships.

This is a research-only diagnostic. It looks for bar/orderbook conditions
whose relationship to the 15-minute label is similar or different between
the Cybos historical source and the recent KIS live collection window.

It does not train a new model, promote a model, change gates, or submit
orders.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable


CYBOS_SOURCE = "cybos-historical"
DEFAULT_KIS_START_DATE = "2026-06-11"
DEFAULT_OUTPUT_NAME = "latest-cybos-kis-transfer-review"
FEATURE_NAMES = (
    "return_1m_pct",
    "hl_range_pct",
    "spread_bps",
    "bid_ask_imbalance",
    "avg_trade_size",
    "mid_price",
)
ORDERBOOK_FEATURES = {"spread_bps", "bid_ask_imbalance"}
MIN_RELATIONSHIP_ROWS = 500
MIN_TRANSFER_EFFECT_PCT = 0.02
MIN_KIS_ONLY_EFFECT_PCT = 0.02


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _database_path_from_env(default_path: Path) -> Path:
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///")).expanduser()
    return default_path


def _connect_ro(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True, timeout=30.0)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


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


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _stddev(values: list[float]) -> float | None:
    if not values:
        return None
    avg = sum(values) / len(values)
    return round(math.sqrt(sum((value - avg) ** 2 for value in values) / len(values)), 6)


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return round(sorted_values[0], 6)
    rank = (len(sorted_values) - 1) * min(1.0, max(0.0, pct))
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return round(sorted_values[low], 6)
    weight = rank - low
    return round(sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight, 6)


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    var_x = sum((value - mean_x) ** 2 for value in xs)
    var_y = sum((value - mean_y) ** 2 for value in ys)
    if var_x <= 1e-18 or var_y <= 1e-18:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    return round(cov / math.sqrt(var_x * var_y), 6)


def _sign(value: float | None, *, epsilon: float = 1e-9) -> int:
    if value is None or abs(value) <= epsilon:
        return 0
    return 1 if value > 0 else -1


def _format_number(value: Any, digits: int = 6) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


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


def _records_from_rows(rows: list[sqlite3.Row], *, source: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        future_return_pct = _to_float(row["future_return_pct"])
        if future_return_pct is None:
            continue
        values = _load_json_object(str(row["values_json"] or ""))
        features = {
            name: value
            for name in FEATURE_NAMES
            if (value := _to_float(values.get(name))) is not None
        }
        records.append(
            {
                "source": source,
                "symbol": str(row["symbol"]),
                "event_time": str(row["event_time"]),
                "trade_date": str(row["event_time"])[:10],
                "label": str(row["label"]),
                "future_return_pct": future_return_pct,
                "features": features,
            }
        )
    return records


def _collect_cybos_rows(
    connection: sqlite3.Connection,
    *,
    horizon_min: int,
    sample_size: int,
) -> list[dict[str, Any]]:
    if not (
        _table_exists(connection, "raw_market_ticks")
        and _table_exists(connection, "feature_model_inputs")
        and _table_exists(connection, "feature_labels")
    ):
        return []
    rows = connection.execute(
        """
        SELECT
            inputs.symbol,
            inputs.event_time,
            inputs.values_json,
            labels.label,
            labels.future_return_pct
        FROM raw_market_ticks AS ticks
        JOIN feature_model_inputs AS inputs
          ON inputs.symbol = ticks.symbol
         AND inputs.event_time = ticks.event_time
        JOIN feature_labels AS labels
          ON labels.symbol = inputs.symbol
         AND labels.event_time = inputs.event_time
         AND labels.horizon_min = ?
        WHERE ticks.source = ?
        ORDER BY ticks.event_time DESC, ticks.symbol
        LIMIT ?
        """,
        (horizon_min, CYBOS_SOURCE, sample_size),
    ).fetchall()
    return _records_from_rows(rows, source=CYBOS_SOURCE)


def _collect_kis_rows(
    connection: sqlite3.Connection,
    *,
    horizon_min: int,
    start_date: str,
    sample_size: int,
) -> list[dict[str, Any]]:
    if not (_table_exists(connection, "feature_model_inputs") and _table_exists(connection, "feature_labels")):
        return []
    rows = connection.execute(
        """
        SELECT
            inputs.symbol,
            inputs.event_time,
            inputs.values_json,
            labels.label,
            labels.future_return_pct
        FROM feature_model_inputs AS inputs
        JOIN feature_labels AS labels
          ON labels.symbol = inputs.symbol
         AND labels.event_time = inputs.event_time
         AND labels.horizon_min = ?
        WHERE inputs.event_time >= ?
        ORDER BY inputs.event_time DESC, inputs.symbol
        LIMIT ?
        """,
        (horizon_min, start_date, sample_size),
    ).fetchall()
    return _records_from_rows(rows, source="kis-live")


def _sample_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    future_returns = [float(row["future_return_pct"]) for row in rows]
    dates = sorted({str(row["trade_date"]) for row in rows})
    symbols = sorted({str(row["symbol"]) for row in rows})
    return {
        "rows": len(rows),
        "symbols": len(symbols),
        "trade_dates": len(dates),
        "first_event_time": min((str(row["event_time"]) for row in rows), default=None),
        "last_event_time": max((str(row["event_time"]) for row in rows), default=None),
        "label_distribution": _label_distribution(rows),
        "label_ratios": _label_ratios(rows),
        "avg_future_return_pct": _mean(future_returns),
        "stddev_future_return_pct": _stddev(future_returns),
    }


def _feature_distribution(rows: list[dict[str, Any]], feature_name: str) -> dict[str, Any]:
    values = sorted(
        float(row["features"][feature_name])
        for row in rows
        if feature_name in row.get("features", {})
    )
    count = len(values)
    total = len(rows)
    zero_count = sum(1 for value in values if abs(value) <= 1e-12)
    return {
        "rows": count,
        "coverage_ratio": round(count / total, 6) if total else None,
        "zero_ratio": round(zero_count / count, 6) if count else None,
        "mean": _mean(values),
        "stddev": _stddev(values),
        "p10": _percentile(values, 0.10),
        "p50": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
    }


def _bucketize_feature(rows: list[dict[str, Any]], feature_name: str, *, bucket_count: int) -> list[dict[str, Any]]:
    feature_rows = [
        row
        for row in rows
        if feature_name in row.get("features", {})
        and math.isfinite(float(row["features"][feature_name]))
        and math.isfinite(float(row["future_return_pct"]))
    ]
    feature_rows.sort(
        key=lambda row: (
            float(row["features"][feature_name]),
            str(row["event_time"]),
            str(row["symbol"]),
        )
    )
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
        values = [float(row["features"][feature_name]) for row in bucket_rows]
        future_returns = [float(row["future_return_pct"]) for row in bucket_rows]
        buckets.append(
            {
                "bucket": bucket_index + 1,
                "rows": len(bucket_rows),
                "min_feature": round(min(values), 6),
                "max_feature": round(max(values), 6),
                "avg_feature": _mean(values),
                "avg_future_return_pct": _mean(future_returns),
                "label_ratios": _label_ratios(bucket_rows),
            }
        )
    return buckets


def _feature_relationship(rows: list[dict[str, Any]], feature_name: str, *, bucket_count: int) -> dict[str, Any]:
    pairs = [
        (float(row["features"][feature_name]), float(row["future_return_pct"]))
        for row in rows
        if feature_name in row.get("features", {})
        and math.isfinite(float(row["features"][feature_name]))
        and math.isfinite(float(row["future_return_pct"]))
    ]
    distribution = _feature_distribution(rows, feature_name)
    zero_variance = bool(distribution.get("stddev") is not None and abs(float(distribution["stddev"])) <= 1e-12)
    buckets = [] if zero_variance else _bucketize_feature(rows, feature_name, bucket_count=bucket_count)
    top_bottom_delta = None
    bottom = buckets[0] if buckets else {}
    top = buckets[-1] if buckets else {}
    if bottom and top:
        bottom_return = bottom.get("avg_future_return_pct")
        top_return = top.get("avg_future_return_pct")
        if bottom_return is not None and top_return is not None:
            top_bottom_delta = round(float(top_return) - float(bottom_return), 6)
    worst_bucket = None
    if buckets:
        worst_bucket = min(
            buckets,
            key=lambda bucket: float(bucket.get("avg_future_return_pct") or 0.0),
        )
    return {
        "feature": feature_name,
        "distribution": distribution,
        "rows": len(pairs),
        "pearson_future_return": None if zero_variance else _pearson(pairs),
        "top_bottom_future_return_delta_pct": top_bottom_delta,
        "worst_bucket": worst_bucket,
        "buckets": buckets,
    }


def _relationship_map(rows: list[dict[str, Any]], *, bucket_count: int) -> dict[str, dict[str, Any]]:
    return {
        feature_name: _feature_relationship(rows, feature_name, bucket_count=bucket_count)
        for feature_name in FEATURE_NAMES
    }


def _transfer_grade(feature_name: str, cybos: dict[str, Any], kis: dict[str, Any]) -> tuple[str, str]:
    cybos_rows = int(cybos.get("rows") or 0)
    kis_rows = int(kis.get("rows") or 0)
    if cybos_rows < MIN_RELATIONSHIP_ROWS or kis_rows < MIN_RELATIONSHIP_ROWS:
        return "insufficient_rows", "표본 수가 부족해서 비교 후보가 아닙니다."

    cybos_zero = (cybos.get("distribution") or {}).get("zero_ratio")
    kis_zero = (kis.get("distribution") or {}).get("zero_ratio")
    if feature_name in ORDERBOOK_FEATURES and cybos_zero is not None and float(cybos_zero) >= 0.90:
        return (
            "kis_only_orderbook_watch",
            "Cybos 쪽 값이 구조적으로 비어 있어 KIS 전용 shadow 근거로만 봅니다.",
        )

    cybos_delta = cybos.get("top_bottom_future_return_delta_pct")
    kis_delta = kis.get("top_bottom_future_return_delta_pct")
    cybos_corr = cybos.get("pearson_future_return")
    kis_corr = kis.get("pearson_future_return")
    delta_same = _sign(cybos_delta) != 0 and _sign(cybos_delta) == _sign(kis_delta)
    corr_same = _sign(cybos_corr) != 0 and _sign(cybos_corr) == _sign(kis_corr)
    kis_effect = abs(float(kis_delta or 0.0))
    cybos_effect = abs(float(cybos_delta or 0.0))

    if delta_same and kis_effect >= MIN_TRANSFER_EFFECT_PCT and cybos_effect >= MIN_TRANSFER_EFFECT_PCT:
        return "source_stable_candidate", "Cybos와 KIS에서 feature bucket 방향이 같습니다. shadow 후보입니다."
    if not delta_same and (kis_effect >= MIN_TRANSFER_EFFECT_PCT or cybos_effect >= MIN_TRANSFER_EFFECT_PCT):
        return "not_transferable_now", "Cybos와 KIS의 방향이 다르거나 한쪽에서만 보입니다."
    if corr_same or delta_same:
        return "weak_same_direction_watch", "방향은 비슷하지만 효과가 약합니다."
    return "weak_or_no_relationship", "단독 피처 관계가 약하거나 일관되지 않습니다."


def _compare_relationships(
    cybos_relationships: dict[str, dict[str, Any]],
    kis_relationships: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for feature_name in FEATURE_NAMES:
        cybos = cybos_relationships.get(feature_name, {})
        kis = kis_relationships.get(feature_name, {})
        grade, interpretation = _transfer_grade(feature_name, cybos, kis)
        comparisons.append(
            {
                "feature": feature_name,
                "transfer_grade": grade,
                "interpretation": interpretation,
                "cybos_rows": cybos.get("rows"),
                "kis_rows": kis.get("rows"),
                "cybos_pearson": cybos.get("pearson_future_return"),
                "kis_pearson": kis.get("pearson_future_return"),
                "cybos_top_bottom_delta_pct": cybos.get("top_bottom_future_return_delta_pct"),
                "kis_top_bottom_delta_pct": kis.get("top_bottom_future_return_delta_pct"),
                "cybos_zero_ratio": (cybos.get("distribution") or {}).get("zero_ratio"),
                "kis_zero_ratio": (kis.get("distribution") or {}).get("zero_ratio"),
                "cybos_worst_bucket": cybos.get("worst_bucket"),
                "kis_worst_bucket": kis.get("worst_bucket"),
            }
        )
    comparisons.sort(
        key=lambda item: (
            0 if item["transfer_grade"] == "source_stable_candidate" else 1,
            0 if item["transfer_grade"] == "kis_only_orderbook_watch" else 1,
            -abs(float(item.get("kis_top_bottom_delta_pct") or 0.0)),
        )
    )
    return comparisons


def _time_bucket(event_time: str) -> str:
    time_part = event_time[11:16] if len(event_time) >= 16 else ""
    if time_part < "09:00":
        return "pre_open"
    if time_part < "09:30":
        return "open_early"
    if time_part < "11:00":
        return "morning"
    if time_part < "13:00":
        return "midday"
    if time_part < "14:30":
        return "afternoon"
    return "close"


def _momentum_bucket(row: dict[str, Any]) -> str:
    value = row.get("features", {}).get("return_1m_pct")
    if value is None:
        return "missing"
    number = float(value)
    if number >= 0.05:
        return "short_up"
    if number <= -0.05:
        return "short_down"
    return "short_flat"


def _quantile_cutoffs(rows: list[dict[str, Any]], feature_name: str) -> tuple[float | None, float | None]:
    values = sorted(
        float(row["features"][feature_name])
        for row in rows
        if feature_name in row.get("features", {})
    )
    return _percentile(values, 0.30), _percentile(values, 0.70)


def _volatility_bucket_factory(rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], str]:
    low, high = _quantile_cutoffs(rows, "hl_range_pct")

    def classify(row: dict[str, Any]) -> str:
        value = row.get("features", {}).get("hl_range_pct")
        if value is None or low is None or high is None:
            return "missing"
        number = float(value)
        if number <= low:
            return "low_vol"
        if number >= high:
            return "high_vol"
        return "mid_vol"

    return classify


def _group_stats(rows: list[dict[str, Any]], key_func: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[key_func(row)].append(row)
    stats: list[dict[str, Any]] = []
    for group, group_rows in grouped.items():
        future_returns = [float(row["future_return_pct"]) for row in group_rows]
        stats.append(
            {
                "group": group,
                "rows": len(group_rows),
                "avg_future_return_pct": _mean(future_returns),
                "label_ratios": _label_ratios(group_rows),
            }
        )
    stats.sort(key=lambda item: str(item["group"]))
    return stats


def _regime_diagnostics(cybos_rows: list[dict[str, Any]], kis_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "time_bucket": {
            "cybos": _group_stats(cybos_rows, lambda row: _time_bucket(str(row["event_time"]))),
            "kis": _group_stats(kis_rows, lambda row: _time_bucket(str(row["event_time"]))),
        },
        "momentum_bucket": {
            "cybos": _group_stats(cybos_rows, _momentum_bucket),
            "kis": _group_stats(kis_rows, _momentum_bucket),
        },
        "volatility_bucket": {
            "cybos": _group_stats(cybos_rows, _volatility_bucket_factory(cybos_rows)),
            "kis": _group_stats(kis_rows, _volatility_bucket_factory(kis_rows)),
        },
    }


def _group_lookup(groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("group")): item for item in groups}


def _candidate_actions(
    comparisons: list[dict[str, Any]],
    regimes: dict[str, Any],
    *,
    kis_rows: int,
    cybos_rows: int,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in comparisons:
        grade = item.get("transfer_grade")
        feature = str(item.get("feature"))
        kis_delta = item.get("kis_top_bottom_delta_pct")
        cybos_delta = item.get("cybos_top_bottom_delta_pct")
        if grade == "source_stable_candidate":
            direction = "high_feature_is_better" if float(kis_delta or 0.0) > 0 else "high_feature_is_worse"
            actions.append(
                {
                    "candidate": f"source_stable_{feature}",
                    "type": "shadow_filter_candidate",
                    "role": "avoid_or_weighting_filter",
                    "evidence": {
                        "cybos_top_bottom_delta_pct": cybos_delta,
                        "kis_top_bottom_delta_pct": kis_delta,
                        "direction": direction,
                    },
                    "recommended_next_step": "paper/shadow에서 주문 변경 없이 조건별 성과를 계속 누적합니다.",
                }
            )
        elif grade == "kis_only_orderbook_watch":
            kis_effect = abs(float(kis_delta or 0.0))
            if kis_effect >= MIN_KIS_ONLY_EFFECT_PCT:
                actions.append(
                    {
                        "candidate": f"kis_only_{feature}",
                        "type": "kis_live_shadow_only",
                        "role": "orderbook_filter_watch",
                        "evidence": {
                            "kis_top_bottom_delta_pct": kis_delta,
                            "kis_pearson": item.get("kis_pearson"),
                            "cybos_zero_ratio": item.get("cybos_zero_ratio"),
                        },
                        "recommended_next_step": "Cybos로 검증하지 말고 KIS live 20/30/60거래일 checkpoint에서 재평가합니다.",
                    }
                )

    for regime_name, sections in regimes.items():
        cybos = _group_lookup(sections.get("cybos", []))
        kis = _group_lookup(sections.get("kis", []))
        common_groups = sorted(set(cybos) & set(kis))
        for group in common_groups:
            cybos_return = cybos[group].get("avg_future_return_pct")
            kis_return = kis[group].get("avg_future_return_pct")
            if cybos_return is None or kis_return is None:
                continue
            if float(cybos_return) < 0 and float(kis_return) < 0:
                actions.append(
                    {
                        "candidate": f"{regime_name}_{group}_caution",
                        "type": "regime_avoid_watch",
                        "role": "no_trade_or_size_down_candidate",
                        "evidence": {
                            "cybos_avg_future_return_pct": cybos_return,
                            "kis_avg_future_return_pct": kis_return,
                            "cybos_rows": cybos[group].get("rows"),
                            "kis_rows": kis[group].get("rows"),
                        },
                        "recommended_next_step": "거래 회피/축소 후보로만 보고, 모델 승격이나 gate 변경은 하지 않습니다.",
                    }
                )
    if not actions:
        actions.append(
            {
                "candidate": "no_source_stable_profit_signal_yet",
                "type": "do_not_promote",
                "role": "continue_data_collection",
                "evidence": {"cybos_rows": cybos_rows, "kis_rows": kis_rows},
                "recommended_next_step": "KIS live 표본을 더 쌓고, 기존 buy-avoid/overlay 관측을 유지합니다.",
            }
        )
    return actions


def _assessment(report: dict[str, Any]) -> dict[str, Any]:
    samples = report.get("samples", {})
    kis_rows = int((samples.get("kis_live") or {}).get("rows") or 0)
    cybos_rows = int((samples.get("cybos_historical") or {}).get("rows") or 0)
    comparisons = report.get("feature_transfer", [])
    source_stable = [item for item in comparisons if item.get("transfer_grade") == "source_stable_candidate"]
    kis_only = [item for item in comparisons if item.get("transfer_grade") == "kis_only_orderbook_watch"]
    if kis_rows < 10_000:
        posture = "kis_sample_still_small"
        conclusion = "KIS live 표본이 아직 작아 수익 후보를 확정할 수 없습니다."
    elif source_stable:
        posture = "source_stable_shadow_candidates_found"
        conclusion = "Cybos와 KIS에서 같은 방향으로 보이는 조건이 있어 shadow 후보로 분리합니다."
    elif kis_only:
        posture = "kis_specific_shadow_candidates_only"
        conclusion = "Cybos로 전이 검증할 수 없는 KIS 전용 orderbook 후보만 보입니다."
    elif cybos_rows and kis_rows:
        posture = "no_transferable_profit_signal_yet"
        conclusion = "현재 공통 피처만으로는 전이 가능한 수익 신호가 뚜렷하지 않습니다."
    else:
        posture = "insufficient_data"
        conclusion = "Cybos 또는 KIS 표본을 충분히 읽지 못했습니다."
    return {
        "posture": posture,
        "conclusion": conclusion,
        "source_stable_feature_count": len(source_stable),
        "kis_only_orderbook_feature_count": len(kis_only),
    }


def _format_group_table(title: str, section: dict[str, Any]) -> list[str]:
    lines = [
        f"### {title}",
        "",
        "| source | group | rows | avg_future_return_pct | up | flat | down |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for source_name in ("cybos", "kis"):
        for item in section.get(source_name, []):
            ratios = item.get("label_ratios") or {}
            lines.append(
                "| {source} | {group} | {rows} | {ret} | {up} | {flat} | {down} |".format(
                    source=source_name,
                    group=item.get("group"),
                    rows=item.get("rows"),
                    ret=_format_number(item.get("avg_future_return_pct")),
                    up=_format_number(ratios.get("up")),
                    flat=_format_number(ratios.get("flat")),
                    down=_format_number(ratios.get("down")),
                )
            )
    lines.append("")
    return lines


def _format_markdown(report: dict[str, Any]) -> str:
    assessment = report.get("assessment", {})
    samples = report.get("samples", {})
    cybos = samples.get("cybos_historical", {})
    kis = samples.get("kis_live", {})
    lines = [
        "# Cybos-KIS Transfer Review",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- horizon_min: `{report.get('horizon_min')}`",
        f"- posture: `{assessment.get('posture')}`",
        f"- conclusion: {assessment.get('conclusion')}",
        "",
        "## Guardrails",
        "",
        "- 이 리포트는 연구/진단 전용입니다. 모델 승격, gate 변경, 주문 정책 변경을 하지 않습니다.",
        "- Cybos 장기 데이터와 KIS live 데이터가 같은 방향으로 말하는지 확인하는 보조 리포트입니다.",
        "- `spread_bps`, `bid_ask_imbalance`는 KIS live 성격이 강한 호가 피처이므로 Cybos 검증으로 직접 확정하지 않습니다.",
        "",
        "## Samples",
        "",
        "| source | rows | symbols | trade_dates | first | last | avg_future_return_pct | labels |",
        "| --- | ---: | ---: | ---: | --- | --- | ---: | --- |",
        (
            f"| cybos_historical | {cybos.get('rows')} | {cybos.get('symbols')} | {cybos.get('trade_dates')} | "
            f"{cybos.get('first_event_time')} | {cybos.get('last_event_time')} | "
            f"{_format_number(cybos.get('avg_future_return_pct'))} | `{cybos.get('label_distribution')}` |"
        ),
        (
            f"| kis_live | {kis.get('rows')} | {kis.get('symbols')} | {kis.get('trade_dates')} | "
            f"{kis.get('first_event_time')} | {kis.get('last_event_time')} | "
            f"{_format_number(kis.get('avg_future_return_pct'))} | `{kis.get('label_distribution')}` |"
        ),
        "",
        "## Feature Transfer",
        "",
        "| feature | grade | cybos_delta | kis_delta | cybos_corr | kis_corr | cybos_zero | kis_zero | interpretation |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report.get("feature_transfer", []):
        lines.append(
            "| {feature} | {grade} | {cybos_delta} | {kis_delta} | {cybos_corr} | {kis_corr} | {cybos_zero} | {kis_zero} | {interpretation} |".format(
                feature=item.get("feature"),
                grade=item.get("transfer_grade"),
                cybos_delta=_format_number(item.get("cybos_top_bottom_delta_pct")),
                kis_delta=_format_number(item.get("kis_top_bottom_delta_pct")),
                cybos_corr=_format_number(item.get("cybos_pearson")),
                kis_corr=_format_number(item.get("kis_pearson")),
                cybos_zero=_format_number(item.get("cybos_zero_ratio")),
                kis_zero=_format_number(item.get("kis_zero_ratio")),
                interpretation=item.get("interpretation"),
            )
        )
    lines.extend(
        [
            "",
            "## Regime Diagnostics",
            "",
        ]
    )
    regimes = report.get("regime_diagnostics", {})
    lines.extend(_format_group_table("Time Bucket", regimes.get("time_bucket", {})))
    lines.extend(_format_group_table("Momentum Bucket", regimes.get("momentum_bucket", {})))
    lines.extend(_format_group_table("Volatility Bucket", regimes.get("volatility_bucket", {})))
    lines.extend(
        [
            "## Candidate Actions",
            "",
            "| candidate | type | role | evidence | next_step |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for action in report.get("candidate_actions", []):
        lines.append(
            "| {candidate} | {type} | {role} | `{evidence}` | {next_step} |".format(
                candidate=action.get("candidate"),
                type=action.get("type"),
                role=action.get("role"),
                evidence=json.dumps(action.get("evidence", {}), ensure_ascii=False, sort_keys=True),
                next_step=action.get("recommended_next_step"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- 수익을 내는 진입 모델을 확정하기보다, 먼저 손실이 반복되는 구간과 전이 가능한 조건을 분리하는 것이 안전합니다.",
            "- `source_stable_candidate`는 바로 실거래 조건이 아니라, paper/shadow에서 계속 추적할 후보입니다.",
            "- `kis_only_orderbook_watch`는 Cybos로 검증하지 말고 KIS live 표본이 20/30/60거래일로 늘어날 때 재판정해야 합니다.",
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
    cybos_sample_size: int = 200_000,
    kis_start_date: str = DEFAULT_KIS_START_DATE,
    kis_sample_size: int = 200_000,
    bucket_count: int = 5,
    write_reports: bool = True,
) -> dict[str, Any]:
    with _connect_ro(database_path) as connection:
        cybos_rows = _collect_cybos_rows(
            connection,
            horizon_min=horizon_min,
            sample_size=cybos_sample_size,
        )
        kis_rows = _collect_kis_rows(
            connection,
            horizon_min=horizon_min,
            start_date=kis_start_date,
            sample_size=kis_sample_size,
        )

    cybos_relationships = _relationship_map(cybos_rows, bucket_count=bucket_count)
    kis_relationships = _relationship_map(kis_rows, bucket_count=bucket_count)
    feature_transfer = _compare_relationships(cybos_relationships, kis_relationships)
    regimes = _regime_diagnostics(cybos_rows, kis_rows)
    samples = {
        "cybos_historical": _sample_summary(cybos_rows),
        "kis_live": _sample_summary(kis_rows),
    }
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database_path": str(database_path),
        "horizon_min": horizon_min,
        "scope": "research_only_no_model_promotion_no_gate_change_no_order_change",
        "source_separation": {
            "cybos": "raw_market_ticks.source = cybos-historical",
            "kis_live": f"feature_model_inputs.event_time >= {kis_start_date}",
            "guardrail": "KIS live selection uses the post-Cybos live window; source drift report must remain the authority for raw-source mismatch checks.",
        },
        "samples": samples,
        "feature_relationships": {
            "cybos_historical": cybos_relationships,
            "kis_live": kis_relationships,
        },
        "feature_transfer": feature_transfer,
        "regime_diagnostics": regimes,
    }
    report["candidate_actions"] = _candidate_actions(
        feature_transfer,
        regimes,
        kis_rows=int(samples["kis_live"].get("rows") or 0),
        cybos_rows=int(samples["cybos_historical"].get("rows") or 0),
    )
    report["assessment"] = _assessment(report)

    if write_reports:
        target_dir = output_dir or _repo_root() / "runtime-data" / "reports" / "research"
        json_path, md_path = _write_reports(report, target_dir, output_name)
        report["output_paths"] = {"json": str(json_path), "markdown": str(md_path)}
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize Cybos/KIS feature transfer diagnostics.")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--output-name", default=DEFAULT_OUTPUT_NAME)
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--cybos-sample-size", type=int, default=200_000)
    parser.add_argument("--kis-start-date", default=DEFAULT_KIS_START_DATE)
    parser.add_argument("--kis-sample-size", type=int, default=200_000)
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
        cybos_sample_size=args.cybos_sample_size,
        kis_start_date=args.kis_start_date,
        kis_sample_size=args.kis_sample_size,
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
