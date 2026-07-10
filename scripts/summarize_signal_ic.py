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
        _filter_shadow_rows_by_date,
        _load_rows,
        _trade_cost_pct,
    )
except ImportError:  # pragma: no cover - direct script run
    from summarize_lightgbm_defensive_shadow import (  # type: ignore[no-redef]
        DEFAULT_DATABASE,
        DEFAULT_DIAGNOSTICS,
        _choose_label_threshold,
        _connect_readonly,
        _filter_shadow_rows_by_date,
        _load_rows,
        _trade_cost_pct,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "research"
DEFAULT_MODEL_VERSION_TEMPLATE = "lightgbm-h{horizon_min}-v1"
DECOMPOSITION_MEAN_IC_THRESHOLD = 0.03
DECOMPOSITION_T_STAT_THRESHOLD = 2.5
DECOMPOSITION_MIN_USABLE_DAYS = 5
DECOMPOSITION_VOL_LOOKBACK_BARS = 5
TIME_BUCKET_ORDER = ("open_early", "midday", "close", "outside_regular")
VOLATILITY_BUCKET_ORDER = ("low", "medium", "high", "unknown")
REPRODUCTION_T_STAT_THRESHOLD = 2.0
PREREGISTERED_REPRODUCTION_CANDIDATES = (
    {"symbol": "005380", "signal": "probability_up", "prior_direction": "positive"},
    {"symbol": "035420", "signal": "probability_down", "prior_direction": "negative"},
    {"symbol": "105560", "signal": "probability_down", "prior_direction": "positive"},
)

PREREGISTERED_CRITERIA = {
    "source_document": "docs/cowork-reports/2026-07-05-alternative-approaches-validation-plan.md",
    "criteria_revision": "review_ver_26 requested E1 decomposition before 2026-07-18; no threshold/gate/order policy change",
    "experiment": "E1_signal_information_coefficient",
    "primary_signal": "probability_down_vs_future_return_pct_on_baseline_buy_shadow_rows",
    "daily_metric": "Spearman rank correlation per trade_date",
    "proceed_to_filter_experiments": "mean_daily_ic <= -0.02 and t_stat <= -2.0",
    "signal_quality_insufficient": "abs(mean_daily_ic) < 0.02 or abs(t_stat) < 2.0",
    "reverse_signal_observation": "mean_daily_ic >= 0.02 and t_stat >= 2.0",
    "pooled_correlation_use": "reference_only_not_decision",
    "decomposition_families": ["time_bucket", "symbol", "volatility_bucket"],
    "decomposition_time_buckets": {
        "open_early": "09:00 <= event_time < 10:00 KST",
        "midday": "10:00 <= event_time < 14:30 KST",
        "close": "14:30 <= event_time during regular session",
        "outside_regular": "event_time outside the above regular-session buckets",
    },
    "decomposition_volatility_bucket": (
        "recent realized volatility proxy: rolling mean of absolute one-minute close-to-close returns, "
        f"lookback={DECOMPOSITION_VOL_LOOKBACK_BARS}; low/medium/high split by terciles on joined rows"
    ),
    "decomposition_candidate_after_multiple_comparison": (
        f"abs(mean_daily_ic) >= {DECOMPOSITION_MEAN_IC_THRESHOLD} and "
        f"abs(t_stat) >= {DECOMPOSITION_T_STAT_THRESHOLD} and "
        f"days_usable >= {DECOMPOSITION_MIN_USABLE_DAYS}"
    ),
    "decomposition_scope_until_2026_07_18": "diagnostic only; do not run E2/E3 filter tuning or policy changes from decomposition alone",
}


@dataclass(frozen=True)
class IcRow:
    trade_date: str
    symbol: str
    event_time: str
    probability_up: float | None
    probability_flat: float | None
    probability_down: float | None
    future_return_pct: float
    time_bucket: str
    volatility_bucket: str
    recent_volatility_pct: float | None


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


def _minutes_from_event_time(value: str) -> int | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.hour * 60 + parsed.minute


def _time_bucket(value: str) -> str:
    minutes = _minutes_from_event_time(value)
    if minutes is None:
        return "outside_regular"
    if 9 * 60 <= minutes < 10 * 60:
        return "open_early"
    if 10 * 60 <= minutes < 14 * 60 + 30:
        return "midday"
    if 14 * 60 + 30 <= minutes <= 15 * 60 + 30:
        return "close"
    return "outside_regular"


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


def _recent_volatility_map(connection: sqlite3.Connection, shadow_rows: list[Any]) -> dict[tuple[str, str], float]:
    if not shadow_rows:
        return {}
    symbols = sorted({str(row.symbol) for row in shadow_rows})
    if not symbols:
        return {}
    min_time = min(str(row.event_time) for row in shadow_rows)
    max_time = max(str(row.event_time) for row in shadow_rows)
    placeholders = ",".join("?" for _ in symbols)
    try:
        bar_rows = connection.execute(
            f"""
            SELECT symbol, bar_time, close
            FROM curated_minute_bars
            WHERE symbol IN ({placeholders})
              AND bar_time >= ?
              AND bar_time <= ?
              AND close IS NOT NULL
            ORDER BY symbol ASC, bar_time ASC
            """,
            [*symbols, min_time[:10] + "T00:00:00+09:00", max_time],
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    by_symbol: dict[str, list[tuple[str, float]]] = {}
    for symbol, bar_time, close_raw in bar_rows:
        try:
            close = float(close_raw)
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        by_symbol.setdefault(str(symbol), []).append((str(bar_time), close))

    volatility: dict[tuple[str, str], float] = {}
    for symbol, rows in by_symbol.items():
        recent_abs_returns: list[float] = []
        previous_close: float | None = None
        for bar_time, close in rows:
            if previous_close is not None and previous_close > 0:
                abs_return_pct = abs((close / previous_close - 1.0) * 100.0)
                recent_abs_returns.append(abs_return_pct)
                if len(recent_abs_returns) > DECOMPOSITION_VOL_LOOKBACK_BARS:
                    recent_abs_returns.pop(0)
                volatility[(symbol, bar_time)] = mean(recent_abs_returns)
            previous_close = close
    return volatility


def _volatility_cutoffs(volatility_map: dict[tuple[str, str], float], shadow_rows: list[Any]) -> tuple[float | None, float | None]:
    values = sorted(
        volatility_map[(str(row.symbol), str(row.event_time))]
        for row in shadow_rows
        if (str(row.symbol), str(row.event_time)) in volatility_map
    )
    if not values:
        return None, None
    return _percentile(values, 1.0 / 3.0), _percentile(values, 2.0 / 3.0)


def _volatility_bucket(value: float | None, low_cutoff: float | None, high_cutoff: float | None) -> str:
    if value is None or low_cutoff is None or high_cutoff is None:
        return "unknown"
    if value <= low_cutoff:
        return "low"
    if value <= high_cutoff:
        return "medium"
    return "high"


def _rows_from_shadow(
    connection: sqlite3.Connection,
    horizon_min: int,
    label_threshold_pct: float,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[IcRow]:
    shadow_rows = _filter_shadow_rows_by_date(
        _load_rows(connection, horizon_min, label_threshold_pct),
        start_date=start_date,
        end_date=end_date,
    )
    volatility_map = _recent_volatility_map(connection, shadow_rows)
    low_cutoff, high_cutoff = _volatility_cutoffs(volatility_map, shadow_rows)
    result: list[IcRow] = []
    for row in shadow_rows:
        key = (str(row.symbol), str(row.event_time))
        recent_volatility = volatility_map.get(key)
        result.append(
            IcRow(
                trade_date=_date_from_event_time(row.event_time),
                symbol=row.symbol,
                event_time=row.event_time,
                probability_up=row.probability_up,
                probability_flat=row.probability_flat,
                probability_down=row.probability_down,
                future_return_pct=row.future_return_pct,
                time_bucket=_time_bucket(row.event_time),
                volatility_bucket=_volatility_bucket(recent_volatility, low_cutoff, high_cutoff),
                recent_volatility_pct=recent_volatility,
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


def _classify_decomposition_candidate(summary: dict[str, Any], probability_field: str) -> dict[str, Any]:
    mean_ic = summary.get("mean_daily_ic")
    t_stat = summary.get("t_stat")
    days_usable = int(summary.get("days_usable") or 0)
    if mean_ic is None or t_stat is None:
        return {
            "magnitude_candidate": False,
            "expected_direction_candidate": False,
            "reverse_direction_candidate": False,
            "reason": "insufficient_data",
        }
    magnitude_candidate = (
        abs(float(mean_ic)) >= DECOMPOSITION_MEAN_IC_THRESHOLD
        and abs(float(t_stat)) >= DECOMPOSITION_T_STAT_THRESHOLD
        and days_usable >= DECOMPOSITION_MIN_USABLE_DAYS
    )
    expected_direction = "negative" if probability_field == "probability_down" else "positive"
    expected_direction_met = mean_ic < 0 if probability_field == "probability_down" else mean_ic > 0
    return {
        "magnitude_candidate": magnitude_candidate,
        "expected_direction": expected_direction,
        "expected_direction_candidate": bool(magnitude_candidate and expected_direction_met),
        "reverse_direction_candidate": bool(magnitude_candidate and not expected_direction_met),
        "reason": "passes_preregistered_magnitude" if magnitude_candidate else "below_preregistered_magnitude",
    }


def _signal_block(rows: list[IcRow], probability_field: str, min_daily_rows: int) -> dict[str, Any]:
    daily = _daily_ic(rows, probability_field, min_daily_rows=min_daily_rows)
    summary = _summarize_daily(daily)
    return {
        "daily": daily,
        "summary": summary,
        "candidate": _classify_decomposition_candidate(summary, probability_field),
    }


def _ordered_group_keys(family: str, keys: Iterable[str]) -> list[str]:
    key_set = set(keys)
    if family == "time_bucket":
        return [key for key in TIME_BUCKET_ORDER if key in key_set] + sorted(key_set - set(TIME_BUCKET_ORDER))
    if family == "volatility_bucket":
        return [key for key in VOLATILITY_BUCKET_ORDER if key in key_set] + sorted(key_set - set(VOLATILITY_BUCKET_ORDER))
    return sorted(key_set)


def _decompose_rows(rows: list[IcRow], min_daily_rows: int) -> dict[str, Any]:
    families = {
        "time_bucket": lambda row: row.time_bucket,
        "symbol": lambda row: row.symbol,
        "volatility_bucket": lambda row: row.volatility_bucket,
    }
    family_results: dict[str, list[dict[str, Any]]] = {}
    for family, key_func in families.items():
        grouped: dict[str, list[IcRow]] = {}
        for row in rows:
            grouped.setdefault(str(key_func(row)), []).append(row)
        entries: list[dict[str, Any]] = []
        for group_key in _ordered_group_keys(family, grouped.keys()):
            group_rows = grouped[group_key]
            entries.append(
                {
                    "group_family": family,
                    "group_key": group_key,
                    "rows": len(group_rows),
                    "trade_days": sorted({row.trade_date for row in group_rows}),
                    "probability_down": _signal_block(group_rows, "probability_down", min_daily_rows),
                    "probability_up": _signal_block(group_rows, "probability_up", min_daily_rows),
                }
            )
        family_results[family] = entries
    candidates: list[dict[str, Any]] = []
    for family, entries in family_results.items():
        for entry in entries:
            for signal in ("probability_down", "probability_up"):
                candidate = entry[signal]["candidate"]
                if candidate.get("magnitude_candidate"):
                    candidates.append(
                        {
                            "group_family": family,
                            "group_key": entry["group_key"],
                            "signal": signal,
                            "rows": entry["rows"],
                            "days_usable": entry[signal]["summary"].get("days_usable"),
                            "mean_daily_ic": entry[signal]["summary"].get("mean_daily_ic"),
                            "t_stat": entry[signal]["summary"].get("t_stat"),
                            "expected_direction_candidate": candidate.get("expected_direction_candidate"),
                            "reverse_direction_candidate": candidate.get("reverse_direction_candidate"),
                        }
                    )
    candidates.sort(key=lambda row: abs(float(row.get("t_stat") or 0.0)), reverse=True)
    return {
        "preregistered_criteria": {
            "families": list(families.keys()),
            "candidate_after_multiple_comparison": PREREGISTERED_CRITERIA["decomposition_candidate_after_multiple_comparison"],
            "interpretation": "magnitude candidates are follow-up hypotheses only until 2026-07-18 remeasurement",
        },
        "families": family_results,
        "candidates": candidates,
    }


def _candidate_reproducibility(decomposition: dict[str, Any]) -> dict[str, Any]:
    symbol_entries = {
        str(entry.get("group_key")): entry
        for entry in decomposition.get("families", {}).get("symbol", [])
    }
    results: list[dict[str, Any]] = []
    for candidate in PREREGISTERED_REPRODUCTION_CANDIDATES:
        symbol = candidate["symbol"]
        signal = candidate["signal"]
        prior_direction = candidate["prior_direction"]
        entry = symbol_entries.get(symbol, {})
        signal_block = entry.get(signal, {})
        summary = signal_block.get("summary", {})
        mean_ic = summary.get("mean_daily_ic")
        t_stat = summary.get("t_stat")
        same_direction = False
        if mean_ic is not None:
            same_direction = float(mean_ic) > 0 if prior_direction == "positive" else float(mean_ic) < 0
        passes = bool(
            same_direction
            and t_stat is not None
            and abs(float(t_stat)) >= REPRODUCTION_T_STAT_THRESHOLD
        )
        if mean_ic is None or t_stat is None:
            status = "insufficient_data"
        elif passes:
            status = "reproduced"
        else:
            status = "not_reproduced"
        results.append(
            {
                "symbol": symbol,
                "signal": signal,
                "prior_direction": prior_direction,
                "rows": int(entry.get("rows") or 0),
                "days_usable": int(summary.get("days_usable") or 0),
                "mean_daily_ic": mean_ic,
                "t_stat": t_stat,
                "same_direction": same_direction,
                "passes_review_ver_27_gate": passes,
                "status": status,
            }
        )
    return {
        "source_review": "docs/cowork-reports/2026-07-05-buy-avoid-validation-verification-review_ver_27.md",
        "criteria": "same symbol, same IC direction, abs(t_stat) >= 2.0",
        "candidates": results,
        "reproduced_count": sum(1 for result in results if result["passes_review_ver_27_gate"]),
        "all_reproduced": bool(results) and all(
            result["passes_review_ver_27_gate"] for result in results
        ),
    }


def _daily_ic_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        str(row["trade_date"]): float(row["ic"])
        for row in rows
        if row.get("ic") is not None
    }


def _build_105560_probability_relationship(
    rows: list[IcRow],
    *,
    min_daily_rows: int,
) -> dict[str, Any]:
    symbol_rows = [row for row in rows if row.symbol == "105560"]
    daily_by_signal = {
        signal: _daily_ic(symbol_rows, signal, min_daily_rows=min_daily_rows)
        for signal in ("probability_down", "probability_up", "probability_flat")
    }
    summary_by_signal = {
        signal: _summarize_daily(daily)
        for signal, daily in daily_by_signal.items()
    }
    down_map = _daily_ic_map(daily_by_signal["probability_down"])
    up_map = _daily_ic_map(daily_by_signal["probability_up"])
    flat_map = _daily_ic_map(daily_by_signal["probability_flat"])
    paired_dates = sorted(set(down_map) & set(up_map))
    relationship_rows = [
        {
            "trade_date": trade_date,
            "probability_down_ic": down_map[trade_date],
            "probability_up_ic": up_map[trade_date],
            "probability_flat_ic": flat_map.get(trade_date),
        }
        for trade_date in paired_dates
    ]
    return {
        "symbol": "105560",
        "rows": len(symbol_rows),
        "trade_days": sorted({row.trade_date for row in symbol_rows}),
        "probability_down": {
            "daily": daily_by_signal["probability_down"],
            "summary": summary_by_signal["probability_down"],
        },
        "probability_up": {
            "daily": daily_by_signal["probability_up"],
            "summary": summary_by_signal["probability_up"],
        },
        "probability_flat": {
            "daily": daily_by_signal["probability_flat"],
            "summary": summary_by_signal["probability_flat"],
        },
        "down_up_daily_ic_relationship": {
            "method": "Pearson correlation across paired daily Spearman IC values",
            "paired_days": len(paired_dates),
            "pearson": _pearson(
                [down_map[trade_date] for trade_date in paired_dates],
                [up_map[trade_date] for trade_date in paired_dates],
            ),
            "same_sign_days": sum(
                1
                for trade_date in paired_dates
                if down_map[trade_date] * up_map[trade_date] > 0
            ),
            "daily": relationship_rows,
        },
    }


def _build_preregistered_remeasurement(
    rows: list[IcRow],
    decomposition: dict[str, Any],
    *,
    min_daily_rows: int,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, Any]:
    return {
        "source_review": "docs/cowork-reports/2026-07-05-buy-avoid-validation-verification-review_ver_27.md",
        "requested_window": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "window_locked_to_review_ver_27": start_date == "2026-07-04" and end_date == "2026-07-18",
        "candidate_reproducibility": _candidate_reproducibility(decomposition),
        "special_105560_probability_relationship": _build_105560_probability_relationship(
            rows,
            min_daily_rows=min_daily_rows,
        ),
        "interpretation": "diagnostic_only",
        "automatic_policy_change": False,
    }


def build_summary(
    *,
    database_path: Path,
    diagnostics_path: Path,
    horizon_min: int,
    min_daily_rows: int = 2,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    with _connect_readonly(database_path) as connection:
        threshold = _choose_label_threshold(connection, horizon_min)
        if threshold is None:
            return {
                "status": "no_joinable_shadow_rows",
                "generated_at": _now_iso(),
                "horizon_min": horizon_min,
                "requested_date_range": {
                    "start_date": start_date,
                    "end_date": end_date,
                },
                "preregistered_criteria": PREREGISTERED_CRITERIA,
            }
        rows = _rows_from_shadow(
            connection,
            horizon_min,
            threshold,
            start_date=start_date,
            end_date=end_date,
        )
    down_daily = _daily_ic(rows, "probability_down", min_daily_rows=min_daily_rows)
    up_daily = _daily_ic(rows, "probability_up", min_daily_rows=min_daily_rows)
    flat_daily = _daily_ic(rows, "probability_flat", min_daily_rows=min_daily_rows)
    down_summary = _summarize_daily(down_daily)
    up_summary = _summarize_daily(up_daily)
    flat_summary = _summarize_daily(flat_daily)
    pooled_down_pairs = [(row.probability_down, row.future_return_pct) for row in rows if row.probability_down is not None]
    pooled_up_pairs = [(row.probability_up, row.future_return_pct) for row in rows if row.probability_up is not None]
    pooled_flat_pairs = [(row.probability_flat, row.future_return_pct) for row in rows if row.probability_flat is not None]
    down_decision = _classify_down_signal(down_summary)
    decomposition = _decompose_rows(rows, min_daily_rows)
    remeasurement = _build_preregistered_remeasurement(
        rows,
        decomposition,
        min_daily_rows=min_daily_rows,
        start_date=start_date,
        end_date=end_date,
    )
    return {
        "status": "ok" if rows else "no_joinable_shadow_rows",
        "generated_at": _now_iso(),
        "horizon_min": horizon_min,
        "model_version": DEFAULT_MODEL_VERSION_TEMPLATE.format(horizon_min=horizon_min),
        "database_path": str(database_path),
        "trade_cost_pct_reference": _trade_cost_pct(diagnostics_path),
        "label_threshold_pct": threshold,
        "joined_rows": len(rows),
        "requested_date_range": {
            "start_date": start_date,
            "end_date": end_date,
        },
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
        "probability_flat": {
            "daily": flat_daily,
            "summary": flat_summary,
            "pooled_spearman_reference_only": spearman(
                [float(p) for p, _r in pooled_flat_pairs], [r for _p, r in pooled_flat_pairs]
            ),
        },
        "decomposition": decomposition,
        "preregistered_remeasurement": remeasurement,
    }


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _candidate_mark(candidate: dict[str, Any]) -> str:
    if candidate.get("expected_direction_candidate"):
        return "expected"
    if candidate.get("reverse_direction_candidate"):
        return "reverse"
    return "-"


def render_markdown(summary: dict[str, Any]) -> str:
    down = summary.get("probability_down", {})
    down_summary = down.get("summary", {})
    up = summary.get("probability_up", {})
    up_summary = up.get("summary", {})
    flat = summary.get("probability_flat", {})
    flat_summary = flat.get("summary", {})
    remeasurement = summary.get("preregistered_remeasurement", {})
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
        f"- requested_date_range: `{summary.get('requested_date_range', {}).get('start_date')}` ~ `{summary.get('requested_date_range', {}).get('end_date')}`",
        "",
        "## Preregistered Criteria",
        "",
        "- down 확률이 높을수록 미래 수익률이 낮아야 한다.",
        "- E1 전체 통과: `mean_daily_ic <= -0.02` 그리고 `t_stat <= -2.0`.",
        "- 부분집합 후속 후보: `abs(mean_daily_ic) >= 0.03`, `abs(t_stat) >= 2.5`, `days_usable >= 5`.",
        "- `pooled_spearman_reference_only`는 참고용이며 판정에 쓰지 않는다.",
        "- 부분집합 후보는 2026-07-18 재측정 전까지 진단용이다.",
        "",
        "## Summary",
        "",
        "| signal | usable_days | mean_daily_ic | std_daily_ic | t_stat | pooled_reference |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| probability_down | {_fmt(down_summary.get('days_usable'), 0)} | {_fmt(down_summary.get('mean_daily_ic'))} | {_fmt(down_summary.get('std_daily_ic'))} | {_fmt(down_summary.get('t_stat'))} | {_fmt(down.get('pooled_spearman_reference_only'))} |",
        f"| probability_up | {_fmt(up_summary.get('days_usable'), 0)} | {_fmt(up_summary.get('mean_daily_ic'))} | {_fmt(up_summary.get('std_daily_ic'))} | {_fmt(up_summary.get('t_stat'))} | {_fmt(up.get('pooled_spearman_reference_only'))} |",
        f"| probability_flat | {_fmt(flat_summary.get('days_usable'), 0)} | {_fmt(flat_summary.get('mean_daily_ic'))} | {_fmt(flat_summary.get('std_daily_ic'))} | {_fmt(flat_summary.get('t_stat'))} | {_fmt(flat.get('pooled_spearman_reference_only'))} |",
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
    decomposition = summary.get("decomposition", {})
    families = decomposition.get("families") or {}
    if families:
        lines.extend([
            "## Decomposition",
            "",
            "| family | group | rows | down_mean_ic | down_t | down_candidate | up_mean_ic | up_t | up_candidate |",
            "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |",
        ])
        for family in ("time_bucket", "volatility_bucket", "symbol"):
            for entry in families.get(family, []):
                down_block = entry.get("probability_down", {})
                up_block = entry.get("probability_up", {})
                lines.append(
                    "| {family} | {group} | {rows} | {down_mean} | {down_t} | {down_candidate} | {up_mean} | {up_t} | {up_candidate} |".format(
                        family=family,
                        group=entry.get("group_key"),
                        rows=entry.get("rows"),
                        down_mean=_fmt(down_block.get("summary", {}).get("mean_daily_ic")),
                        down_t=_fmt(down_block.get("summary", {}).get("t_stat")),
                        down_candidate=_candidate_mark(down_block.get("candidate", {})),
                        up_mean=_fmt(up_block.get("summary", {}).get("mean_daily_ic")),
                        up_t=_fmt(up_block.get("summary", {}).get("t_stat")),
                        up_candidate=_candidate_mark(up_block.get("candidate", {})),
                    )
                )
        lines.append("")
    candidates = decomposition.get("candidates") or []
    lines.extend(["## Decomposition Candidates", ""])
    if candidates:
        lines.extend(["| family | group | signal | rows | days | mean_ic | t_stat | type |", "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |"])
        for row in candidates:
            candidate_type = "expected" if row.get("expected_direction_candidate") else "reverse"
            lines.append(
                "| {family} | {group} | {signal} | {rows} | {days} | {mean_ic} | {t_stat} | {candidate_type} |".format(
                    family=row.get("group_family"),
                    group=row.get("group_key"),
                    signal=row.get("signal"),
                    rows=row.get("rows"),
                    days=row.get("days_usable"),
                    mean_ic=_fmt(row.get("mean_daily_ic")),
                    t_stat=_fmt(row.get("t_stat")),
                    candidate_type=candidate_type,
                )
            )
        lines.append("")
    else:
        lines.extend(["- No subset passed the preregistered decomposition threshold.", ""])
    reproduction = remeasurement.get("candidate_reproducibility", {})
    reproduction_candidates = reproduction.get("candidates") or []
    lines.extend(["## Review Ver 27 Reproduction Gate", ""])
    lines.append(
        f"- window_locked_to_review_ver_27: `{remeasurement.get('window_locked_to_review_ver_27')}`"
    )
    lines.append(f"- criteria: `{reproduction.get('criteria')}`")
    lines.append(f"- reproduced_count: `{reproduction.get('reproduced_count')}`")
    lines.append("")
    if reproduction_candidates:
        lines.extend(
            [
                "| symbol | signal | prior_direction | rows | days | mean_ic | t_stat | same_direction | pass | status |",
                "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
            ]
        )
        for row in reproduction_candidates:
            lines.append(
                "| {symbol} | {signal} | {direction} | {rows} | {days} | {mean_ic} | {t_stat} | {same_direction} | {passed} | {status} |".format(
                    symbol=row.get("symbol"),
                    signal=row.get("signal"),
                    direction=row.get("prior_direction"),
                    rows=row.get("rows"),
                    days=row.get("days_usable"),
                    mean_ic=_fmt(row.get("mean_daily_ic")),
                    t_stat=_fmt(row.get("t_stat")),
                    same_direction=row.get("same_direction"),
                    passed=row.get("passes_review_ver_27_gate"),
                    status=row.get("status"),
                )
            )
        lines.append("")

    relationship = remeasurement.get("special_105560_probability_relationship", {})
    relation = relationship.get("down_up_daily_ic_relationship", {})
    flat_105560 = relationship.get("probability_flat", {}).get("summary", {})
    lines.extend(
        [
            "## 105560 Probability Relationship",
            "",
            f"- rows: `{relationship.get('rows')}`",
            f"- probability_flat_mean_daily_ic: `{_fmt(flat_105560.get('mean_daily_ic'))}`",
            f"- probability_flat_t_stat: `{_fmt(flat_105560.get('t_stat'))}`",
            f"- paired_down_up_days: `{relation.get('paired_days')}`",
            f"- down_up_daily_ic_pearson: `{_fmt(relation.get('pearson'))}`",
            f"- same_sign_days: `{relation.get('same_sign_days')}`",
            "",
            "- Diagnostic only. This report does not change thresholds, gates, active models, or order policy.",
            "",
        ]
    )
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
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_summary(
        database_path=args.database_path,
        diagnostics_path=args.diagnostics_path,
        horizon_min=args.horizon_min,
        min_daily_rows=args.min_daily_rows,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    json_path, md_path = write_outputs(summary, args.output_dir, args.horizon_min)
    print(json.dumps({"status": summary.get("status"), "json_path": str(json_path), "md_path": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
