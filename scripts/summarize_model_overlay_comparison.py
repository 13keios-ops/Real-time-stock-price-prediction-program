#!/usr/bin/env python3
"""Compare model overlay roles for buy-avoid, buy-rescue, and hold-rescue.

This is a read-only research diagnostic. It does not submit orders, alter
paper/live runtime behavior, update gates, or change active model state.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.models.loader import load_named_builtin_model
from app.storage.contracts import FeatureSnapshot
from scripts.summarize_hold_rescue_paper_replay import (
    _decision as _hold_decision,
    _eligibility as _hold_eligibility,
    replay_hold_rescue,
)
from scripts.summarize_hold_rescue_paper_replay_feasibility import (
    DEFAULT_SINCE_DATE,
    BarPoint,
    PredictionPoint,
    _load_bars,
    _load_fills,
    reconstruct_closed_lots,
)


DEFAULT_DATABASE = REPO_ROOT / "runtime-data" / "dev.db"
DEFAULT_DIAGNOSTICS = (
    REPO_ROOT / "runtime-data" / "reports" / "challengers" / "latest-lightgbm-performance-diagnostics-h15.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "challengers"
DEFAULT_AVOID_THRESHOLDS = (0.40, 0.45, 0.50, 0.54, 0.58)
DEFAULT_RESCUE_THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65)
DEFAULT_HOLD_THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65)
MIN_DIAGNOSTIC_TRADES = 30


@dataclass(frozen=True)
class ModelSpec:
    name: str
    model_version: str
    source: str
    builtin_name: str | None = None


@dataclass(frozen=True)
class OverlayRow:
    symbol: str
    event_time: str
    probability_up: float
    probability_flat: float
    probability_down: float
    label: str
    future_return_pct: float
    signal_id: str | None = None
    signal_side: str | None = None
    signal_allowed: bool | None = None

    @property
    def predicted_label(self) -> str:
        values = {
            "up": self.probability_up,
            "flat": self.probability_flat,
            "down": self.probability_down,
        }
        return max(values.items(), key=lambda item: item[1])[0]

    @property
    def max_probability(self) -> float:
        return max(self.probability_up, self.probability_flat, self.probability_down)

    @property
    def up_is_argmax(self) -> bool:
        return self.predicted_label == "up"

    @property
    def down_is_argmax(self) -> bool:
        return self.predicted_label == "down"

    @property
    def key(self) -> tuple[str, str]:
        return (self.symbol, self.event_time)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _round(value: float | int, digits: int = 6) -> float:
    return round(float(value), digits)


def _to_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: Any) -> datetime:
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _trade_cost_pct(diagnostics_path: Path) -> float:
    value = _to_float(_read_json(diagnostics_path).get("trade_cost_pct"))
    return value if value is not None else 0.108


def _connect_readonly(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }


def _prediction_point(row: OverlayRow) -> PredictionPoint:
    return PredictionPoint(
        probability_up=row.probability_up,
        probability_flat=row.probability_flat,
        probability_down=row.probability_down,
        predicted_label=row.predicted_label,
    )


def _long_net_return(row: OverlayRow, trade_cost_pct: float) -> float:
    return row.future_return_pct - trade_cost_pct


def _virtual_direction_net_return(row: OverlayRow, trade_cost_pct: float) -> float:
    if row.predicted_label == "up":
        return row.future_return_pct - trade_cost_pct
    if row.predicted_label == "down":
        return -row.future_return_pct - trade_cost_pct
    return 0.0


def _clean_values(values_json: str) -> dict[str, float]:
    raw = json.loads(values_json)
    values: dict[str, float] = {}
    for key, value in raw.items():
        number = _to_float(value)
        if number is not None:
            values[str(key)] = number
    return values


def _predict_builtin_row(
    *,
    model: Any,
    symbol: str,
    event_time: str,
    feature_set_version: str,
    values_json: str,
    horizon_min: int,
) -> tuple[float, float, float]:
    snapshot = FeatureSnapshot(
        symbol=symbol,
        event_time=_parse_datetime(event_time),
        feature_set_version=feature_set_version,
        values=_clean_values(values_json),
    )
    prediction = model.predict(
        snapshot,
        horizon_min=horizon_min,
        prediction_id=f"overlay-{symbol}-{event_time}-{horizon_min}",
    )
    return (
        float(prediction.probability_up),
        float(prediction.probability_flat),
        float(prediction.probability_down),
    )


def _choose_label_threshold(connection: sqlite3.Connection, horizon_min: int, since_date: str) -> float | None:
    row = connection.execute(
        """
        SELECT threshold_pct, COUNT(1) AS row_count
        FROM feature_labels
        WHERE horizon_min = ?
          AND substr(event_time, 1, 10) >= ?
          AND future_return_pct IS NOT NULL
        GROUP BY threshold_pct
        ORDER BY row_count DESC, threshold_pct ASC
        LIMIT 1
        """,
        (horizon_min, since_date),
    ).fetchone()
    return float(row[0]) if row else None


def _signal_filter_sql(pool: str) -> str:
    if pool == "baseline_buy":
        return "AND s.side = 'buy' AND s.allowed = 1"
    if pool == "not_baseline_buy":
        return "AND NOT (s.signal_id IS NOT NULL AND s.side = 'buy' AND s.allowed = 1)"
    if pool == "all_labeled":
        return ""
    raise ValueError(f"Unsupported pool: {pool}")


def _load_baseline_buy_keys(
    connection: sqlite3.Connection,
    *,
    since_date: str,
) -> set[tuple[str, str]]:
    rows = connection.execute(
        """
        SELECT symbol, event_time
        FROM serving_trade_signals
        WHERE side = 'buy'
          AND allowed = 1
          AND substr(event_time, 1, 10) >= ?
        """,
        (since_date,),
    ).fetchall()
    return {(str(row[0]), str(row[1])) for row in rows}


def _load_stored_prediction_rows(
    connection: sqlite3.Connection,
    *,
    model_version: str,
    horizon_min: int,
    label_threshold_pct: float,
    since_date: str,
    pool: str,
) -> list[OverlayRow]:
    if pool == "all_labeled":
        rows = connection.execute(
            """
            SELECT
                p.symbol,
                p.event_time,
                p.probability_up,
                p.probability_flat,
                p.probability_down,
                fl.label,
                fl.future_return_pct
            FROM serving_predictions AS p
            JOIN feature_labels AS fl
              ON fl.symbol = p.symbol
             AND fl.event_time = p.event_time
             AND fl.horizon_min = ?
             AND ABS(fl.threshold_pct - ?) < 0.000000001
            WHERE p.horizon_min = ?
              AND p.model_version = ?
              AND substr(p.event_time, 1, 10) >= ?
              AND fl.future_return_pct IS NOT NULL
            ORDER BY p.event_time ASC, p.symbol ASC
            """,
            (horizon_min, label_threshold_pct, horizon_min, model_version, since_date),
        ).fetchall()
        result: list[OverlayRow] = []
        for row in rows:
            future_return = _to_float(row[6])
            probs = [_to_float(row[2]), _to_float(row[3]), _to_float(row[4])]
            if future_return is None or any(value is None for value in probs):
                continue
            result.append(
                OverlayRow(
                    symbol=str(row[0]),
                    event_time=str(row[1]),
                    probability_up=float(probs[0]),
                    probability_flat=float(probs[1]),
                    probability_down=float(probs[2]),
                    label=str(row[5]),
                    future_return_pct=future_return,
                )
            )
        return result
    signal_filter = _signal_filter_sql(pool)
    if pool == "baseline_buy":
        signal_join = "JOIN serving_trade_signals AS s ON s.symbol = p.symbol AND s.event_time = p.event_time"
    else:
        signal_join = "LEFT JOIN serving_trade_signals AS s ON s.symbol = p.symbol AND s.event_time = p.event_time"
    rows = connection.execute(
        f"""
        SELECT
            p.symbol,
            p.event_time,
            p.probability_up,
            p.probability_flat,
            p.probability_down,
            fl.label,
            fl.future_return_pct,
            s.signal_id,
            s.side,
            s.allowed
        FROM serving_predictions AS p
        {signal_join}
        JOIN feature_labels AS fl
          ON fl.symbol = p.symbol
         AND fl.event_time = p.event_time
         AND fl.horizon_min = ?
         AND ABS(fl.threshold_pct - ?) < 0.000000001
        WHERE p.horizon_min = ?
          AND p.model_version = ?
          AND substr(p.event_time, 1, 10) >= ?
          AND fl.future_return_pct IS NOT NULL
          {signal_filter}
        ORDER BY p.event_time ASC, p.symbol ASC
        """,
        (horizon_min, label_threshold_pct, horizon_min, model_version, since_date),
    ).fetchall()
    result: list[OverlayRow] = []
    for row in rows:
        future_return = _to_float(row[6])
        probs = [_to_float(row[2]), _to_float(row[3]), _to_float(row[4])]
        if future_return is None or any(value is None for value in probs):
            continue
        result.append(
            OverlayRow(
                symbol=str(row[0]),
                event_time=str(row[1]),
                probability_up=float(probs[0]),
                probability_flat=float(probs[1]),
                probability_down=float(probs[2]),
                label=str(row[5]),
                future_return_pct=future_return,
                signal_id=str(row[7]) if row[7] is not None else None,
                signal_side=str(row[8]) if row[8] is not None else None,
                signal_allowed=bool(row[9]) if row[9] is not None else None,
            )
        )
    return result


def _load_builtin_prediction_rows(
    connection: sqlite3.Connection,
    *,
    model: Any,
    horizon_min: int,
    label_threshold_pct: float,
    since_date: str,
    pool: str,
    feature_set_version: str | None,
) -> list[OverlayRow]:
    if pool == "all_labeled":
        feature_filter = "AND f.feature_set_version = ?" if feature_set_version else ""
        params: list[Any] = [horizon_min, label_threshold_pct, since_date]
        if feature_set_version:
            params.append(feature_set_version)
        rows = connection.execute(
            f"""
            SELECT
                f.symbol,
                f.event_time,
                f.feature_set_version,
                f.values_json,
                fl.label,
                fl.future_return_pct
            FROM feature_model_inputs AS f
            JOIN feature_labels AS fl
              ON fl.symbol = f.symbol
             AND fl.event_time = f.event_time
             AND fl.horizon_min = ?
             AND ABS(fl.threshold_pct - ?) < 0.000000001
            WHERE substr(f.event_time, 1, 10) >= ?
              AND fl.future_return_pct IS NOT NULL
              {feature_filter}
            ORDER BY f.event_time ASC, f.symbol ASC
            """,
            tuple(params),
        ).fetchall()
        result: list[OverlayRow] = []
        for row in rows:
            future_return = _to_float(row[5])
            if future_return is None:
                continue
            probability_up, probability_flat, probability_down = _predict_builtin_row(
                model=model,
                symbol=str(row[0]),
                event_time=str(row[1]),
                feature_set_version=str(row[2]),
                values_json=str(row[3]),
                horizon_min=horizon_min,
            )
            result.append(
                OverlayRow(
                    symbol=str(row[0]),
                    event_time=str(row[1]),
                    probability_up=probability_up,
                    probability_flat=probability_flat,
                    probability_down=probability_down,
                    label=str(row[4]),
                    future_return_pct=future_return,
                )
            )
        return result
    signal_filter = _signal_filter_sql(pool)
    if pool == "baseline_buy":
        signal_join = "JOIN serving_trade_signals AS s ON s.symbol = f.symbol AND s.event_time = f.event_time"
    else:
        signal_join = "LEFT JOIN serving_trade_signals AS s ON s.symbol = f.symbol AND s.event_time = f.event_time"
    feature_filter = "AND f.feature_set_version = ?" if feature_set_version else ""
    params: list[Any] = [horizon_min, label_threshold_pct, since_date]
    if feature_set_version:
        params.append(feature_set_version)
    rows = connection.execute(
        f"""
        SELECT
            f.symbol,
            f.event_time,
            f.feature_set_version,
            f.values_json,
            fl.label,
            fl.future_return_pct,
            s.signal_id,
            s.side,
            s.allowed
        FROM feature_model_inputs AS f
        {signal_join}
        JOIN feature_labels AS fl
          ON fl.symbol = f.symbol
         AND fl.event_time = f.event_time
         AND fl.horizon_min = ?
         AND ABS(fl.threshold_pct - ?) < 0.000000001
        WHERE substr(f.event_time, 1, 10) >= ?
          AND fl.future_return_pct IS NOT NULL
          {feature_filter}
          {signal_filter}
        ORDER BY f.event_time ASC, f.symbol ASC
        """,
        tuple(params),
    ).fetchall()
    result: list[OverlayRow] = []
    for row in rows:
        future_return = _to_float(row[5])
        if future_return is None:
            continue
        probability_up, probability_flat, probability_down = _predict_builtin_row(
            model=model,
            symbol=str(row[0]),
            event_time=str(row[1]),
            feature_set_version=str(row[2]),
            values_json=str(row[3]),
            horizon_min=horizon_min,
        )
        result.append(
            OverlayRow(
                symbol=str(row[0]),
                event_time=str(row[1]),
                probability_up=probability_up,
                probability_flat=probability_flat,
                probability_down=probability_down,
                label=str(row[4]),
                future_return_pct=future_return,
                signal_id=str(row[6]) if row[6] is not None else None,
                signal_side=str(row[7]) if row[7] is not None else None,
                signal_allowed=bool(row[8]) if row[8] is not None else None,
            )
        )
    return result


def _load_prediction_rows(
    connection: sqlite3.Connection,
    *,
    spec: ModelSpec,
    builtin_model: Any | None,
    horizon_min: int,
    label_threshold_pct: float,
    since_date: str,
    pool: str,
    feature_set_version: str | None,
) -> list[OverlayRow]:
    if spec.source == "stored_prediction":
        return _load_stored_prediction_rows(
            connection,
            model_version=spec.model_version,
            horizon_min=horizon_min,
            label_threshold_pct=label_threshold_pct,
            since_date=since_date,
            pool=pool,
        )
    if spec.source == "builtin_feature":
        if builtin_model is None:
            raise ValueError(f"builtin_model is required for {spec.model_version}")
        return _load_builtin_prediction_rows(
            connection,
            model=builtin_model,
            horizon_min=horizon_min,
            label_threshold_pct=label_threshold_pct,
            since_date=since_date,
            pool=pool,
            feature_set_version=feature_set_version,
        )
    raise ValueError(f"Unsupported model source: {spec.source}")


def _classification_summary(rows: list[OverlayRow], trade_cost_pct: float) -> dict[str, Any]:
    confusion: dict[str, dict[str, int]] = {}
    predicted_groups: dict[str, list[OverlayRow]] = {"up": [], "flat": [], "down": []}
    correct = 0
    virtual_direction_net = 0.0
    for row in rows:
        predicted = row.predicted_label
        actual = row.label
        confusion.setdefault(predicted, {"up": 0, "flat": 0, "down": 0})
        confusion[predicted][actual] = confusion[predicted].get(actual, 0) + 1
        predicted_groups.setdefault(predicted, []).append(row)
        correct += int(predicted == actual)
        virtual_direction_net += _virtual_direction_net_return(row, trade_cost_pct)

    def class_stats(label: str) -> dict[str, Any]:
        group = predicted_groups.get(label, [])
        if not group:
            return {"rows": 0, "precision": 0.0, "avg_future_return_pct": 0.0, "coverage": 0.0}
        return {
            "rows": len(group),
            "precision": _round(sum(1 for row in group if row.label == label) / len(group)),
            "avg_future_return_pct": _round(sum(row.future_return_pct for row in group) / len(group)),
            "coverage": _round(len(group) / len(rows)) if rows else 0.0,
        }

    buckets = [
        ("0.33-0.40", 0.33, 0.40),
        ("0.40-0.50", 0.40, 0.50),
        ("0.50-0.60", 0.50, 0.60),
        ("0.60+", 0.60, 10.0),
    ]
    confidence_buckets: list[dict[str, Any]] = []
    for name, lower, upper in buckets:
        group = [row for row in rows if lower <= row.max_probability < upper]
        confidence_buckets.append(
            {
                "bucket": name,
                "rows": len(group),
                "accuracy": _round(sum(1 for row in group if row.predicted_label == row.label) / len(group))
                if group
                else 0.0,
                "coverage": _round(len(group) / len(rows)) if rows else 0.0,
            }
        )

    return {
        "rows": len(rows),
        "three_class_accuracy": _round(correct / len(rows)) if rows else 0.0,
        "virtual_direction_cumulative_net_return_pct": _round(virtual_direction_net),
        "predicted_up": class_stats("up"),
        "predicted_flat": class_stats("flat"),
        "predicted_down": class_stats("down"),
        "confidence_buckets": confidence_buckets,
        "strength_segments": _strength_segments(rows, trade_cost_pct),
        "confusion_matrix": confusion,
    }


def _time_bucket(row: OverlayRow) -> str:
    parsed = _parse_datetime(row.event_time)
    minute = parsed.hour * 60 + parsed.minute
    if minute < 10 * 60:
        return "open_0830_1000"
    if minute < 11 * 60 + 30:
        return "morning_1000_1130"
    if minute < 13 * 60:
        return "midday_1130_1300"
    if minute < 14 * 60 + 30:
        return "afternoon_1300_1430"
    return "close_1430_1530"


def _confidence_bucket(row: OverlayRow) -> str:
    value = row.max_probability
    if value < 0.40:
        return "0.33_0.40"
    if value < 0.50:
        return "0.40_0.50"
    if value < 0.60:
        return "0.50_0.60"
    return "0.60_plus"


def _segment_summary(
    *,
    name: str,
    rows: list[OverlayRow],
    total_rows: int,
    trade_cost_pct: float,
) -> dict[str, Any]:
    correct = sum(1 for row in rows if row.predicted_label == row.label)
    return {
        "segment": name,
        "rows": len(rows),
        "coverage": _round(len(rows) / total_rows) if total_rows else 0.0,
        "accuracy": _round(correct / len(rows)) if rows else 0.0,
        "avg_future_return_pct": _round(sum(row.future_return_pct for row in rows) / len(rows)) if rows else 0.0,
        "virtual_direction_net_return_pct": _round(
            sum(_virtual_direction_net_return(row, trade_cost_pct) for row in rows)
        ),
        "up_share": _round(sum(1 for row in rows if row.label == "up") / len(rows)) if rows else 0.0,
        "down_share": _round(sum(1 for row in rows if row.label == "down") / len(rows)) if rows else 0.0,
    }


def _strength_segments(rows: list[OverlayRow], trade_cost_pct: float) -> dict[str, Any]:
    if not rows:
        return {"minimum_rows": 0, "top_accuracy_segments": [], "top_direction_net_segments": []}
    minimum_rows = max(1, min(100, int(len(rows) * 0.005)))
    grouped: dict[str, list[OverlayRow]] = {}
    for row in rows:
        for name in (
            f"direction={row.predicted_label}",
            f"time={_time_bucket(row)}",
            f"confidence={_confidence_bucket(row)}",
            f"direction={row.predicted_label}|time={_time_bucket(row)}",
            f"direction={row.predicted_label}|confidence={_confidence_bucket(row)}",
        ):
            grouped.setdefault(name, []).append(row)
    summaries = [
        _segment_summary(name=name, rows=group, total_rows=len(rows), trade_cost_pct=trade_cost_pct)
        for name, group in grouped.items()
        if len(group) >= minimum_rows
    ]
    top_accuracy = sorted(
        summaries,
        key=lambda item: (float(item["accuracy"]), int(item["rows"])),
        reverse=True,
    )[:8]
    top_direction_net = sorted(
        summaries,
        key=lambda item: float(item["virtual_direction_net_return_pct"]),
        reverse=True,
    )[:8]
    return {
        "minimum_rows": minimum_rows,
        "top_accuracy_segments": top_accuracy,
        "top_direction_net_segments": top_direction_net,
    }


def _buy_avoid_summary(
    rows: list[OverlayRow],
    *,
    thresholds: Iterable[float],
    trade_cost_pct: float,
    require_down_argmax: bool,
) -> dict[str, Any]:
    baseline_net = sum(_long_net_return(row, trade_cost_pct) for row in rows)
    threshold_results: list[dict[str, Any]] = []
    for threshold in thresholds:
        skipped = [
            row
            for row in rows
            if row.probability_down >= threshold and (row.down_is_argmax or not require_down_argmax)
        ]
        skipped_keys = {row.key for row in skipped}
        kept = [row for row in rows if row.key not in skipped_keys]
        kept_net = sum(_long_net_return(row, trade_cost_pct) for row in kept)
        skipped_net = sum(_long_net_return(row, trade_cost_pct) for row in skipped)
        threshold_results.append(
            {
                "threshold": float(threshold),
                "baseline_trades": len(rows),
                "kept_trades": len(kept),
                "skipped_trades": len(skipped),
                "skip_rate": _round(len(skipped) / len(rows)) if rows else 0.0,
                "baseline_net_return_pct": _round(baseline_net),
                "filtered_net_return_pct": _round(kept_net),
                "skipped_net_return_pct": _round(skipped_net),
                "delta_net_return_pct": _round(kept_net - baseline_net),
                "skipped_loss_share": _round(
                    sum(1 for row in skipped if _long_net_return(row, trade_cost_pct) < 0) / len(skipped)
                )
                if skipped
                else 0.0,
            }
        )
    best = max(threshold_results, key=lambda item: float(item["delta_net_return_pct"]), default=None)
    candidate = bool(
        best
        and int(best["skipped_trades"]) >= MIN_DIAGNOSTIC_TRADES
        and float(best["delta_net_return_pct"]) > 0.0
        and 0.05 <= float(best["skip_rate"]) <= 0.80
    )
    return {
        "definition": "baseline buy allowed rows where model down probability can veto a long trade",
        "require_down_argmax": require_down_argmax,
        "rows": len(rows),
        "thresholds": threshold_results,
        "best": best,
        "candidate": candidate,
    }


def _buy_rescue_summary(
    rows: list[OverlayRow],
    *,
    thresholds: Iterable[float],
    trade_cost_pct: float,
    require_up_argmax: bool,
) -> dict[str, Any]:
    threshold_results: list[dict[str, Any]] = []
    for threshold in thresholds:
        rescued = [
            row
            for row in rows
            if row.probability_up >= threshold and (row.up_is_argmax or not require_up_argmax)
        ]
        rescue_net = sum(_long_net_return(row, trade_cost_pct) for row in rescued)
        threshold_results.append(
            {
                "threshold": float(threshold),
                "candidate_rows": len(rows),
                "rescued_trades": len(rescued),
                "rescue_rate": _round(len(rescued) / len(rows)) if rows else 0.0,
                "rescued_net_return_pct": _round(rescue_net),
                "avg_rescued_net_return_pct": _round(rescue_net / len(rescued)) if rescued else 0.0,
                "up_precision": _round(sum(1 for row in rescued if row.label == "up") / len(rescued))
                if rescued
                else 0.0,
                "loss_share": _round(
                    sum(1 for row in rescued if _long_net_return(row, trade_cost_pct) < 0) / len(rescued)
                )
                if rescued
                else 0.0,
            }
        )
    best = max(threshold_results, key=lambda item: float(item["rescued_net_return_pct"]), default=None)
    candidate = bool(
        best
        and int(best["rescued_trades"]) >= MIN_DIAGNOSTIC_TRADES
        and float(best["rescued_net_return_pct"]) > 0.0
        and 0.01 <= float(best["rescue_rate"]) <= 0.50
    )
    return {
        "definition": "non-baseline-buy rows where model up probability can rescue a diagnostic long trade",
        "require_up_argmax": require_up_argmax,
        "rows": len(rows),
        "thresholds": threshold_results,
        "best": best,
        "candidate": candidate,
        "scope_note": "diagnostic only; this is not a live no-trade ledger and does not expand KIS live shadow policy",
    }


def _load_builtin_prediction_points(
    connection: sqlite3.Connection,
    *,
    model: Any,
    horizon_min: int,
    since_date: str,
    feature_set_version: str | None,
) -> tuple[dict[tuple[str, str], PredictionPoint], dict[str, Any]]:
    feature_filter = "AND feature_set_version = ?" if feature_set_version else ""
    params: list[Any] = [since_date]
    if feature_set_version:
        params.append(feature_set_version)
    rows = connection.execute(
        f"""
        SELECT symbol, event_time, feature_set_version, values_json
        FROM feature_model_inputs
        WHERE substr(event_time, 1, 10) >= ?
          {feature_filter}
        ORDER BY event_time ASC, symbol ASC
        """,
        tuple(params),
    ).fetchall()
    predictions: dict[tuple[str, str], PredictionPoint] = {}
    invalid_rows = 0
    for row in rows:
        try:
            probability_up, probability_flat, probability_down = _predict_builtin_row(
                model=model,
                symbol=str(row[0]),
                event_time=str(row[1]),
                feature_set_version=str(row[2]),
                values_json=str(row[3]),
                horizon_min=horizon_min,
            )
            key_time = _parse_datetime(row[1]).replace(second=0, microsecond=0).isoformat()
        except Exception:
            invalid_rows += 1
            continue
        point = PredictionPoint(
            probability_up=probability_up,
            probability_flat=probability_flat,
            probability_down=probability_down,
            predicted_label=max(
                {"up": probability_up, "flat": probability_flat, "down": probability_down}.items(),
                key=lambda item: item[1],
            )[0],
        )
        predictions[(str(row[0]), key_time)] = point
    return predictions, {
        "status": "ok",
        "source": "feature_model_inputs_builtin_prediction",
        "raw_rows": len(rows),
        "matched_key_rows": len(predictions),
        "invalid_rows": invalid_rows,
    }


def _load_stored_prediction_points(
    connection: sqlite3.Connection,
    *,
    model_version: str,
    horizon_min: int,
    since_date: str,
) -> tuple[dict[tuple[str, str], PredictionPoint], dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT symbol, event_time, probability_up, probability_flat, probability_down
        FROM serving_predictions
        WHERE horizon_min = ?
          AND model_version = ?
          AND substr(event_time, 1, 10) >= ?
        ORDER BY event_time ASC, symbol ASC
        """,
        (horizon_min, model_version, since_date),
    ).fetchall()
    predictions: dict[tuple[str, str], PredictionPoint] = {}
    invalid_rows = 0
    for row in rows:
        probs = [_to_float(row[2]), _to_float(row[3]), _to_float(row[4])]
        if any(value is None for value in probs):
            invalid_rows += 1
            continue
        key_time = _parse_datetime(row[1]).replace(second=0, microsecond=0).isoformat()
        predicted_label = max(
            {"up": float(probs[0]), "flat": float(probs[1]), "down": float(probs[2])}.items(),
            key=lambda item: item[1],
        )[0]
        predictions[(str(row[0]), key_time)] = PredictionPoint(
            probability_up=float(probs[0]),
            probability_flat=float(probs[1]),
            probability_down=float(probs[2]),
            predicted_label=predicted_label,
        )
    return predictions, {
        "status": "ok",
        "source": "serving_predictions",
        "model_version": model_version,
        "raw_rows": len(rows),
        "matched_key_rows": len(predictions),
        "invalid_rows": invalid_rows,
    }


def _hold_rescue_summary(
    connection: sqlite3.Connection,
    *,
    spec: ModelSpec,
    builtin_model: Any | None,
    horizon_min: int,
    since_date: str,
    thresholds: tuple[float, ...],
    max_extension_minutes: int,
    max_loss_pct: float | None,
    trade_cost_pct: float,
    forced_flat_time: str,
    feature_set_version: str | None,
) -> dict[str, Any]:
    fills, fill_summary = _load_fills(connection, since_date)
    closed_lots, reconstruction_summary = reconstruct_closed_lots(fills)
    if spec.source == "stored_prediction":
        predictions, prediction_summary = _load_stored_prediction_points(
            connection,
            model_version=spec.model_version,
            horizon_min=horizon_min,
            since_date=since_date,
        )
    else:
        if builtin_model is None:
            raise ValueError("builtin_model is required for builtin hold-rescue")
        predictions, prediction_summary = _load_builtin_prediction_points(
            connection,
            model=builtin_model,
            horizon_min=horizon_min,
            since_date=since_date,
            feature_set_version=feature_set_version,
        )
    bars_by_symbol, bar_summary = _load_bars(connection, since_date)
    parsed_forced_flat_time = datetime.strptime(forced_flat_time, "%H:%M").time()
    eligible_lots, eligibility = _hold_eligibility(
        closed_lots,
        predictions,
        bars_by_symbol,
        max_extension_minutes=max_extension_minutes,
        forced_flat_time=parsed_forced_flat_time,
    )
    replay = replay_hold_rescue(
        eligible_lots,
        predictions,
        thresholds=thresholds,
        max_loss_pct=max_loss_pct,
        trade_cost_pct=trade_cost_pct,
    )
    decision = _hold_decision(eligibility, replay)
    best = max(
        replay.get("threshold_results", []),
        key=lambda item: float(item.get("delta_cash_sum", 0.0)),
        default=None,
    )
    return {
        "definition": "paper closed lots where model up probability can delay the actual paper sell fill",
        "fill_source": fill_summary,
        "position_reconstruction": reconstruction_summary,
        "prediction_source": prediction_summary,
        "future_bar_source": bar_summary,
        "eligibility": eligibility,
        "replay": replay,
        "decision": decision,
        "best": best,
        "candidate": decision.get("status") == "diagnostic_candidate_paper_only",
    }


def _row_map(rows: list[OverlayRow]) -> dict[tuple[str, str], OverlayRow]:
    return {row.key: row for row in rows}


def _policy_result(
    *,
    policy: str,
    family: str,
    baseline_rows: list[OverlayRow],
    executed_rows: list[OverlayRow],
    trade_cost_pct: float,
) -> dict[str, Any]:
    baseline_net = sum(_long_net_return(row, trade_cost_pct) for row in baseline_rows)
    executed_net = sum(_long_net_return(row, trade_cost_pct) for row in executed_rows)
    return {
        "family": family,
        "policy": policy,
        "baseline_rows": len(baseline_rows),
        "executed_rows": len(executed_rows),
        "skipped_or_filtered_rows": len(baseline_rows) - len(executed_rows),
        "coverage": _round(len(executed_rows) / len(baseline_rows)) if baseline_rows else 0.0,
        "baseline_net_return_pct": _round(baseline_net),
        "policy_net_return_pct": _round(executed_net),
        "delta_net_return_pct": _round(executed_net - baseline_net),
        "loss_share": _round(
            sum(1 for row in executed_rows if _long_net_return(row, trade_cost_pct) < 0) / len(executed_rows)
        )
        if executed_rows
        else 0.0,
    }


def _combined_policy_summary(
    model_rows_by_name: dict[str, list[OverlayRow]],
    baseline_buy_keys: set[tuple[str, str]],
    trade_cost_pct: float,
) -> dict[str, Any]:
    lightgbm = _row_map(model_rows_by_name.get("LightGBM", []))
    linear = _row_map(model_rows_by_name.get("linear-score", []))
    common_keys = set(lightgbm) & set(linear)
    common_buy_keys = sorted(common_keys & baseline_buy_keys)
    common_no_buy_keys = sorted(common_keys - baseline_buy_keys)
    baseline_rows = [lightgbm[key] for key in common_buy_keys]

    def lightgbm_down(key: tuple[str, str], threshold: float = 0.40) -> bool:
        row = lightgbm[key]
        return row.down_is_argmax and row.probability_down >= threshold

    def linear_down(key: tuple[str, str], threshold: float = 0.40) -> bool:
        row = linear[key]
        return row.down_is_argmax and row.probability_down >= threshold

    def both_up(key: tuple[str, str], threshold: float = 0.40) -> bool:
        return (
            lightgbm[key].up_is_argmax
            and linear[key].up_is_argmax
            and lightgbm[key].probability_up >= threshold
            and linear[key].probability_up >= threshold
        )

    policy_candidates = [
        _policy_result(
            policy="baseline_no_overlay",
            family="buy_avoid",
            baseline_rows=baseline_rows,
            executed_rows=baseline_rows,
            trade_cost_pct=trade_cost_pct,
        ),
        _policy_result(
            policy="lightgbm_down_veto_0.40",
            family="buy_avoid",
            baseline_rows=baseline_rows,
            executed_rows=[lightgbm[key] for key in common_buy_keys if not lightgbm_down(key)],
            trade_cost_pct=trade_cost_pct,
        ),
        _policy_result(
            policy="linear_score_down_veto_0.40",
            family="buy_avoid",
            baseline_rows=baseline_rows,
            executed_rows=[lightgbm[key] for key in common_buy_keys if not linear_down(key)],
            trade_cost_pct=trade_cost_pct,
        ),
        _policy_result(
            policy="either_model_down_veto_0.40",
            family="buy_avoid",
            baseline_rows=baseline_rows,
            executed_rows=[
                lightgbm[key]
                for key in common_buy_keys
                if not (lightgbm_down(key) or linear_down(key))
            ],
            trade_cost_pct=trade_cost_pct,
        ),
        _policy_result(
            policy="both_models_down_veto_0.40",
            family="buy_avoid",
            baseline_rows=baseline_rows,
            executed_rows=[
                lightgbm[key]
                for key in common_buy_keys
                if not (lightgbm_down(key) and linear_down(key))
            ],
            trade_cost_pct=trade_cost_pct,
        ),
    ]
    rescue_rows = [lightgbm[key] for key in common_no_buy_keys if both_up(key)]
    rescue_net = sum(_long_net_return(row, trade_cost_pct) for row in rescue_rows)
    policy_candidates.append(
        {
            "family": "buy_rescue",
            "policy": "both_models_up_rescue_0.40",
            "baseline_rows": len(common_no_buy_keys),
            "executed_rows": len(rescue_rows),
            "skipped_or_filtered_rows": len(common_no_buy_keys) - len(rescue_rows),
            "coverage": _round(len(rescue_rows) / len(common_no_buy_keys)) if common_no_buy_keys else 0.0,
            "baseline_net_return_pct": 0.0,
            "policy_net_return_pct": _round(rescue_net),
            "delta_net_return_pct": _round(rescue_net),
            "loss_share": _round(
                sum(1 for row in rescue_rows if _long_net_return(row, trade_cost_pct) < 0) / len(rescue_rows)
            )
            if rescue_rows
            else 0.0,
        }
    )
    ranked = sorted(
        [row for row in policy_candidates if row["policy"] != "baseline_no_overlay"],
        key=lambda item: float(item["delta_net_return_pct"]),
        reverse=True,
    )
    return {
        "status": "ok" if common_keys else "missing_common_model_rows",
        "common_rows": len(common_keys),
        "common_baseline_buy_rows": len(common_buy_keys),
        "common_non_baseline_buy_rows": len(common_no_buy_keys),
        "policy_candidates": policy_candidates,
        "best_policy": ranked[0] if ranked else None,
        "decision": {
            "status": "diagnostic_only_no_order_policy_change",
            "recommended_action": "조합 정책은 후보 비교로만 유지하고 KIS live shadow/주문 정책 변경 전 누적 표본과 비용 후 일관성을 확인",
        },
    }


def _model_role(summary: dict[str, Any]) -> dict[str, Any]:
    roles: list[str] = []
    if summary["buy_avoid"]["candidate"]:
        roles.append("defensive_buy_avoid")
    if summary["buy_rescue"]["candidate"]:
        roles.append("offensive_buy_rescue")
    if summary["hold_rescue"]["candidate"]:
        roles.append("position_hold_rescue")
    if not roles:
        roles.append("observe_only")
    return {
        "suggested_roles": roles,
        "policy_status": "diagnostic_only_no_order_policy_change",
        "recommended_next_step": (
            "모델별 역할 후보를 dashboard/report 에 누적 표시하고 KIS live shadow 표본이 충분해질 때까지 주문 정책에는 반영하지 않음"
        ),
    }


def _default_model_specs(horizon_min: int) -> list[ModelSpec]:
    return [
        ModelSpec(
            name="LightGBM",
            model_version=f"lightgbm-h{horizon_min}-v1",
            source="stored_prediction",
        ),
        ModelSpec(
            name="linear-score",
            model_version=f"linear-score-h{horizon_min}-v1",
            source="builtin_feature",
            builtin_name="linear_score",
        ),
    ]


def build_report(
    *,
    database_path: Path,
    diagnostics_path: Path,
    horizon_min: int,
    since_date: str,
    avoid_thresholds: tuple[float, ...],
    rescue_thresholds: tuple[float, ...],
    hold_thresholds: tuple[float, ...],
    require_down_argmax: bool,
    require_up_argmax: bool,
    max_extension_minutes: int,
    max_loss_pct: float | None,
    forced_flat_time: str,
) -> dict[str, Any]:
    settings = load_settings(REPO_ROOT)
    trade_cost_pct = _trade_cost_pct(diagnostics_path)
    connection = _connect_readonly(database_path)
    try:
        available_tables = _tables(connection)
        required_tables = {
            "feature_labels",
            "feature_model_inputs",
            "serving_predictions",
            "serving_trade_signals",
            "paper_orders",
            "paper_fills",
            "curated_minute_bars",
        }
        missing = sorted(required_tables - available_tables)
        if missing:
            return {
                "generated_at": _now_iso(),
                "status": "missing_required_tables",
                "missing_tables": missing,
            }
        label_threshold_pct = _choose_label_threshold(connection, horizon_min, since_date)
        if label_threshold_pct is None:
            return {
                "generated_at": _now_iso(),
                "status": "missing_feature_labels",
                "horizon_min": horizon_min,
                "since_date": since_date,
            }
        model_summaries: list[dict[str, Any]] = []
        model_rows_by_name: dict[str, list[OverlayRow]] = {}
        baseline_buy_keys = _load_baseline_buy_keys(connection, since_date=since_date)
        for spec in _default_model_specs(horizon_min):
            builtin_model = (
                load_named_builtin_model(settings, horizon_min=horizon_min, builtin_name=str(spec.builtin_name))
                if spec.builtin_name
                else None
            )
            all_rows = _load_prediction_rows(
                connection,
                spec=spec,
                builtin_model=builtin_model,
                horizon_min=horizon_min,
                label_threshold_pct=label_threshold_pct,
                since_date=since_date,
                pool="all_labeled",
                feature_set_version=settings.feature_set_version,
            )
            model_rows_by_name[spec.name] = all_rows
            buy_rows = [row for row in all_rows if row.key in baseline_buy_keys]
            no_buy_rows = [row for row in all_rows if row.key not in baseline_buy_keys]
            model_summary = {
                "name": spec.name,
                "model_version": spec.model_version,
                "source": spec.source,
                "builtin_name": spec.builtin_name,
                "classification": _classification_summary(all_rows, trade_cost_pct),
                "buy_avoid": _buy_avoid_summary(
                    buy_rows,
                    thresholds=avoid_thresholds,
                    trade_cost_pct=trade_cost_pct,
                    require_down_argmax=require_down_argmax,
                ),
                "buy_rescue": _buy_rescue_summary(
                    no_buy_rows,
                    thresholds=rescue_thresholds,
                    trade_cost_pct=trade_cost_pct,
                    require_up_argmax=require_up_argmax,
                ),
                "hold_rescue": _hold_rescue_summary(
                    connection,
                    spec=spec,
                    builtin_model=builtin_model,
                    horizon_min=horizon_min,
                    since_date=since_date,
                    thresholds=hold_thresholds,
                    max_extension_minutes=max_extension_minutes,
                    max_loss_pct=max_loss_pct,
                    trade_cost_pct=trade_cost_pct,
                    forced_flat_time=forced_flat_time,
                    feature_set_version=settings.feature_set_version,
                ),
            }
            model_summary["role_assessment"] = _model_role(model_summary)
            model_summaries.append(model_summary)
        combination_policy_review = _combined_policy_summary(
            model_rows_by_name,
            baseline_buy_keys,
            trade_cost_pct,
        )
    finally:
        connection.close()

    return {
        "generated_at": _now_iso(),
        "status": "ok",
        "report": "model_overlay_comparison",
        "database_path": str(database_path),
        "horizon_min": horizon_min,
        "since_date": since_date,
        "label_threshold_pct": label_threshold_pct,
        "trade_cost_pct": trade_cost_pct,
        "models": model_summaries,
        "combination_policy_review": combination_policy_review,
        "scope_guardrail": (
            "read-only diagnostic; no paper/live order, gate, config, active model, or KIS live shadow expansion change"
        ),
        "interpretation": {
            "why": "LightGBM 전용 rescue/avoid 해석을 linear-score 승격 후보와 같은 기준에서 비교하기 위함",
            "buy_avoid": "baseline 매수 허용 건 중 모델 하락 확률이 높은 건을 피했을 때 손익 변화",
            "buy_rescue": "baseline 매수 비허용 건 중 모델 상승 확률이 높은 건을 진단상 매수했을 때 손익 변화",
            "hold_rescue": "실제 paper 청산 시점에서 모델 상승 확률이 높을 때 보유 연장 replay 손익 변화",
            "not_yet": "모델 조합 주문 정책 자체는 아직 만들지 않았고, 이 보고서는 역할 분류를 위한 증거 생성 단계",
        },
    }


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Model Overlay Comparison",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{report.get('status')}`",
        f"- horizon_min: `{report.get('horizon_min')}`",
        f"- since_date: `{report.get('since_date')}`",
        f"- scope: `{report.get('scope_guardrail')}`",
        "",
        "## 비교 요약",
        "",
        "| 모델 | 3분류 정확도 | 상승 precision | 하락 precision | buy-avoid delta | buy-rescue net | hold-rescue delta_cash | 역할 후보 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for model in report.get("models", []):
        classification = model.get("classification", {})
        buy_avoid_best = (model.get("buy_avoid", {}) or {}).get("best") or {}
        buy_rescue_best = (model.get("buy_rescue", {}) or {}).get("best") or {}
        hold_best = (model.get("hold_rescue", {}) or {}).get("best") or {}
        roles = ", ".join((model.get("role_assessment", {}) or {}).get("suggested_roles", []))
        lines.append(
            "| "
            f"{model.get('name')} `{model.get('model_version')}` | "
            f"{_fmt(classification.get('three_class_accuracy'))} | "
            f"{_fmt((classification.get('predicted_up') or {}).get('precision'))} | "
            f"{_fmt((classification.get('predicted_down') or {}).get('precision'))} | "
            f"{_fmt(buy_avoid_best.get('delta_net_return_pct'))}% | "
            f"{_fmt(buy_rescue_best.get('rescued_net_return_pct'))}% | "
            f"{_fmt(hold_best.get('delta_cash_sum'), 0)} | "
            f"{roles} |"
        )
    combo = report.get("combination_policy_review", {})
    lines.extend(
        [
            "",
            "## 모델 조합 후보",
            "",
            "| 정책 | 계열 | 기준 row | 실행 row | net | delta | loss share |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for policy in combo.get("policy_candidates", []):
        lines.append(
            "| "
            f"{policy.get('policy')} | "
            f"{policy.get('family')} | "
            f"{policy.get('baseline_rows')} | "
            f"{policy.get('executed_rows')} | "
            f"{_fmt(policy.get('policy_net_return_pct'))}% | "
            f"{_fmt(policy.get('delta_net_return_pct'))}% | "
            f"{_fmt(policy.get('loss_share'))} |"
        )
    best_policy = combo.get("best_policy") or {}
    lines.extend(
        [
            "",
            f"- best_policy: `{best_policy.get('policy')}`",
            f"- decision: `{(combo.get('decision') or {}).get('status')}`",
            "",
            "## 모델별 강점 구간",
            "",
        ]
    )
    for model in report.get("models", []):
        lines.append(f"### {model.get('name')}")
        segments = ((model.get("classification") or {}).get("strength_segments") or {})
        lines.append("")
        lines.append("| 구간 | rows | accuracy | virtual net | coverage |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for segment in segments.get("top_accuracy_segments", [])[:5]:
            lines.append(
                "| "
                f"{segment.get('segment')} | "
                f"{segment.get('rows')} | "
                f"{_fmt(segment.get('accuracy'))} | "
                f"{_fmt(segment.get('virtual_direction_net_return_pct'))}% | "
                f"{_fmt(segment.get('coverage'))} |"
            )
        lines.append("")
    lines.extend(
        [
            "",
            "## 해석 기준",
            "",
            "- `buy-avoid delta`: baseline 매수 허용 건을 모델의 하락 위험 신호로 피했을 때 순수익률 변화입니다.",
            "- `buy-rescue net`: baseline이 매수하지 않은 건 중 모델 상승 신호만 가상 매수했을 때 순수익률 합입니다.",
            "- `hold-rescue delta_cash`: 실제 paper 청산을 모델 상승 신호로 늦췄을 때의 현금 손익 차이입니다.",
            "- 이 보고서는 역할 분류용 진단이며 주문 정책, gate, active model, KIS live shadow 확장을 변경하지 않습니다.",
            "",
        ]
    )
    for model in report.get("models", []):
        lines.extend(
            [
                f"## {model.get('name')} 상세",
                "",
                f"- source: `{model.get('source')}`",
                f"- classification rows: `{(model.get('classification') or {}).get('rows')}`",
                f"- buy-avoid rows: `{(model.get('buy_avoid') or {}).get('rows')}`",
                f"- buy-rescue rows: `{(model.get('buy_rescue') or {}).get('rows')}`",
                f"- hold-rescue status: `{((model.get('hold_rescue') or {}).get('decision') or {}).get('status')}`",
                f"- recommended_next_step: `{((model.get('role_assessment') or {}).get('recommended_next_step'))}`",
                "",
            ]
        )
    return "\n".join(lines)


def _parse_thresholds(value: str) -> tuple[float, ...]:
    return tuple(float(part.strip()) for part in value.split(",") if part.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--diagnostics-path", type=Path, default=DEFAULT_DIAGNOSTICS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--since-date", default=DEFAULT_SINCE_DATE)
    parser.add_argument("--avoid-thresholds", default=",".join(str(value) for value in DEFAULT_AVOID_THRESHOLDS))
    parser.add_argument("--rescue-thresholds", default=",".join(str(value) for value in DEFAULT_RESCUE_THRESHOLDS))
    parser.add_argument("--hold-thresholds", default=",".join(str(value) for value in DEFAULT_HOLD_THRESHOLDS))
    parser.add_argument("--no-require-down-argmax", action="store_true")
    parser.add_argument("--no-require-up-argmax", action="store_true")
    parser.add_argument("--max-extension-minutes", type=int, default=20)
    parser.add_argument("--max-loss-pct", type=float, default=1.2)
    parser.add_argument("--forced-flat-time", default="15:10")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        database_path=args.database_path,
        diagnostics_path=args.diagnostics_path,
        horizon_min=args.horizon_min,
        since_date=args.since_date,
        avoid_thresholds=_parse_thresholds(args.avoid_thresholds),
        rescue_thresholds=_parse_thresholds(args.rescue_thresholds),
        hold_thresholds=_parse_thresholds(args.hold_thresholds),
        require_down_argmax=not args.no_require_down_argmax,
        require_up_argmax=not args.no_require_up_argmax,
        max_extension_minutes=args.max_extension_minutes,
        max_loss_pct=args.max_loss_pct,
        forced_flat_time=args.forced_flat_time,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"latest-model-overlay-comparison-h{args.horizon_min}.json"
    markdown_path = args.output_dir / f"latest-model-overlay-comparison-h{args.horizon_min}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(json.dumps({"json_path": str(json_path), "markdown_path": str(markdown_path), "status": report.get("status")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
