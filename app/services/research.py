"""Research and training services built on the local SQLite runtime store."""

from __future__ import annotations

from bisect import bisect_left
import heapq
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from lightgbm import LGBMClassifier
import numpy as np

from app.collectors.market_data import orderbook_from_kis_ws_record
from app.config.settings import load_settings
from app.features.minute_bars import build_feature_snapshot
from app.labels.thresholds import classify_return
from app.models.baseline import BaselineDirectionModel
from app.models.centroid import CentroidArtifact, CentroidDirectionModel
from app.models.lightgbm_model import LightGbmArtifact, LightGbmDirectionModel, find_latest_lightgbm_artifact
from app.models.loader import load_named_builtin_model, load_prediction_model
from app.models.registry import ModelRegistry, ModelRegistryEntry
from app.observability.logging import configure_logging
from app.services.runtime_cleanup import cleanup_non_actual_runtime_rows
from app.services.runtime_scope import build_runtime_scope, filter_actual_rows
from app.storage.contracts import FeatureLabel, FeatureSnapshot, MinuteBar, ModelEvaluation, OrderbookSnapshot, TrainingRun
from app.storage.runtime_writer import RuntimeWriter, get_sqlite_store
from app.utils.time import now_local


PYKRX_DAILY_PROXY_SOURCE = "pykrx-daily-proxy"
CYBOS_HISTORICAL_SOURCE = "cybos-historical"
PROXY_EXCLUDED_TRAINING_FEATURES = frozenset({"spread_bps", "bid_ask_imbalance", "mid_price"})
BAR_ONLY_FEATURE_NAMES = ["avg_trade_size", "hl_range_pct", "return_1m_pct"]
CYBOS_PROFITABILITY_COST_PCT = 0.13
CYBOS_CONFIDENCE_THRESHOLD_GRID = (0.58, 0.60, 0.62, 0.64, 0.66, 0.68, 0.70, 0.75, 0.80)
CYBOS_LABEL_SENSITIVITY_BASE_GRID = (0.13, 0.20, 0.35, 0.50)
CYBOS_LABEL_REPRODUCIBILITY_THRESHOLD = 0.20
CYBOS_RULE_CHALLENGER_STRATEGIES = (
    "opening_momentum",
    "range_expansion",
    "momentum_follow",
    "pullback_bounce",
    "quiet_breakout",
)
CYBOS_EXPERIMENT_FEATURE_SETS: dict[str, list[str]] = {
    "bar_only": BAR_ONLY_FEATURE_NAMES,
    "bar_context": [
        "avg_trade_size",
        "hl_range_pct",
        "return_1m_pct",
        "close_position_pct",
        "minute_slot_pct",
        "log_volume",
    ],
    "bar_context_momentum": [
        "avg_trade_size",
        "hl_range_pct",
        "return_1m_pct",
        "close_position_pct",
        "minute_slot_pct",
        "log_volume",
        "prev_return_pct",
        "prev_hl_range_pct",
        "log_volume_delta",
    ],
}


@dataclass(slots=True)
class MinuteBarBuildResult:
    bars_written: int
    symbols_processed: list[str]
    runtime_root: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "bars_written": self.bars_written,
            "symbols_processed": self.symbols_processed,
            "runtime_root": str(self.runtime_root),
        }


@dataclass(slots=True)
class FeatureDatasetBuildResult:
    features_written: int
    labels_written: int
    horizons: list[int]
    runtime_root: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "features_written": self.features_written,
            "labels_written": self.labels_written,
            "horizons": self.horizons,
            "runtime_root": str(self.runtime_root),
        }


@dataclass(slots=True)
class BaselineTrainingResult:
    training_run_id: str
    evaluation_id: str
    model_version: str
    horizon_min: int
    train_rows: int
    validation_rows: int
    validation_accuracy: float
    artifact_path: Path
    activation_applied: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "training_run_id": self.training_run_id,
            "evaluation_id": self.evaluation_id,
            "model_version": self.model_version,
            "horizon_min": self.horizon_min,
            "train_rows": self.train_rows,
            "validation_rows": self.validation_rows,
            "validation_accuracy": round(self.validation_accuracy, 6),
            "artifact_path": str(self.artifact_path),
            "activation_applied": self.activation_applied,
        }


@dataclass(slots=True)
class ActiveModelSetResult:
    horizon_min: int
    model_version: str
    model_kind: str
    builtin_name: str | None
    artifact_path: Path | None
    registry_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "horizon_min": self.horizon_min,
            "model_version": self.model_version,
            "model_kind": self.model_kind,
            "builtin_name": self.builtin_name,
            "artifact_path": str(self.artifact_path) if self.artifact_path else None,
            "registry_path": str(self.registry_path),
        }


@dataclass(slots=True)
class BacktestResult:
    evaluation_id: str
    training_run_id: str
    model_version: str
    horizon_min: int
    dataset_scope: str
    rows_evaluated: int
    trades_taken: int
    overall_accuracy: float
    trade_hit_rate: float
    win_rate: float
    average_net_return_pct: float
    cumulative_net_return_pct: float
    report_markdown_path: Path
    report_json_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "evaluation_id": self.evaluation_id,
            "training_run_id": self.training_run_id,
            "model_version": self.model_version,
            "horizon_min": self.horizon_min,
            "dataset_scope": self.dataset_scope,
            "rows_evaluated": self.rows_evaluated,
            "trades_taken": self.trades_taken,
            "overall_accuracy": round(self.overall_accuracy, 6),
            "trade_hit_rate": round(self.trade_hit_rate, 6),
            "win_rate": round(self.win_rate, 6),
            "average_net_return_pct": round(self.average_net_return_pct, 6),
            "cumulative_net_return_pct": round(self.cumulative_net_return_pct, 6),
            "report_markdown_path": str(self.report_markdown_path),
            "report_json_path": str(self.report_json_path),
        }


@dataclass(slots=True)
class WalkForwardBacktestResult:
    evaluation_id: str
    training_run_id: str
    model_version: str
    horizon_min: int
    folds: int
    rows_evaluated: int
    trades_taken: int
    overall_accuracy: float
    trade_hit_rate: float
    win_rate: float
    average_net_return_pct: float
    cumulative_net_return_pct: float
    gap_rows: int
    max_train_rows: int | None
    report_markdown_path: Path
    report_json_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "evaluation_id": self.evaluation_id,
            "training_run_id": self.training_run_id,
            "model_version": self.model_version,
            "horizon_min": self.horizon_min,
            "folds": self.folds,
            "rows_evaluated": self.rows_evaluated,
            "trades_taken": self.trades_taken,
            "overall_accuracy": round(self.overall_accuracy, 6),
            "trade_hit_rate": round(self.trade_hit_rate, 6),
            "win_rate": round(self.win_rate, 6),
            "average_net_return_pct": round(self.average_net_return_pct, 6),
            "cumulative_net_return_pct": round(self.cumulative_net_return_pct, 6),
            "gap_rows": self.gap_rows,
            "max_train_rows": self.max_train_rows,
            "report_markdown_path": str(self.report_markdown_path),
            "report_json_path": str(self.report_json_path),
        }


@dataclass(slots=True)
class ChallengerCandidateResult:
    rank: int
    candidate_name: str
    model_version: str
    model_kind: str
    training_run_id: str
    promotable: bool
    overall_accuracy: float
    trade_hit_rate: float
    win_rate: float
    average_net_return_pct: float
    cumulative_net_return_pct: float
    trades_taken: int
    rows_evaluated: int
    ranking_score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "candidate_name": self.candidate_name,
            "model_version": self.model_version,
            "model_kind": self.model_kind,
            "training_run_id": self.training_run_id,
            "promotable": self.promotable,
            "overall_accuracy": round(self.overall_accuracy, 6),
            "trade_hit_rate": round(self.trade_hit_rate, 6),
            "win_rate": round(self.win_rate, 6),
            "average_net_return_pct": round(self.average_net_return_pct, 6),
            "cumulative_net_return_pct": round(self.cumulative_net_return_pct, 6),
            "trades_taken": self.trades_taken,
            "rows_evaluated": self.rows_evaluated,
            "ranking_score": round(self.ranking_score, 6),
        }


@dataclass(slots=True)
class ChallengerRunResult:
    challenger_run_id: str
    horizon_min: int
    active_model_version: str
    best_model_version: str
    best_candidate_name: str
    recommended_action: str
    recommended_model_version: str
    decision_reason: str
    walk_forward_gate_status: str
    walk_forward_gate_reason: str
    promotion_requested: bool
    promotion_applied: bool
    promoted_model_version: str | None
    active_model_version_after_run: str
    report_markdown_path: Path
    report_json_path: Path
    leaderboard_json_path: Path
    candidates: list[ChallengerCandidateResult]

    def to_dict(self) -> dict[str, object]:
        return {
            "challenger_run_id": self.challenger_run_id,
            "horizon_min": self.horizon_min,
            "active_model_version": self.active_model_version,
            "best_model_version": self.best_model_version,
            "best_candidate_name": self.best_candidate_name,
            "recommended_action": self.recommended_action,
            "recommended_model_version": self.recommended_model_version,
            "decision_reason": self.decision_reason,
            "walk_forward_gate_status": self.walk_forward_gate_status,
            "walk_forward_gate_reason": self.walk_forward_gate_reason,
            "promotion_requested": self.promotion_requested,
            "promotion_applied": self.promotion_applied,
            "promoted_model_version": self.promoted_model_version,
            "active_model_version_after_run": self.active_model_version_after_run,
            "report_markdown_path": str(self.report_markdown_path),
            "report_json_path": str(self.report_json_path),
            "leaderboard_json_path": str(self.leaderboard_json_path),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _find_first_same_day_future_bar(
    bars: list[MinuteBar],
    bar_times: list[datetime],
    target_time: datetime,
) -> MinuteBar | None:
    if not bars:
        return None
    index = bisect_left(bar_times, target_time)
    while index < len(bars):
        candidate = bars[index]
        if candidate.bar_time.date() != target_time.date():
            return None
        return candidate
    return None


def _get_research_sqlite_store(settings):
    return get_sqlite_store(
        settings,
        initialize_schema=False,
        busy_timeout_ms=30_000,
        read_retry_delays=(0.0, 0.25, 0.75, 1.5, 3.0, 6.0),
        write_retry_delays=(0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0),
    )


def _get_research_writer(settings) -> RuntimeWriter:
    return RuntimeWriter.from_settings(
        settings,
        sqlite_initialize_schema=False,
        sqlite_busy_timeout_ms=30_000,
        sqlite_read_retry_delays=(0.0, 0.25, 0.75, 1.5, 3.0, 6.0),
        sqlite_write_retry_delays=(0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0),
    )


@dataclass(slots=True)
class ActualMlRebuildResult:
    feature_build: dict[str, object]
    active_model: dict[str, object]
    lightgbm_training: dict[str, object] | None
    backtest: dict[str, object] | None
    walk_forward: dict[str, object] | None
    challenger: dict[str, object] | None
    deleted_files: list[str]
    deleted_tables: dict[str, int]
    deleted_runtime_rows: dict[str, int]
    errors: dict[str, str]
    runtime_root: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_build": self.feature_build,
            "active_model": self.active_model,
            "lightgbm_training": self.lightgbm_training,
            "backtest": self.backtest,
            "walk_forward": self.walk_forward,
            "challenger": self.challenger,
            "deleted_files": self.deleted_files,
            "deleted_tables": self.deleted_tables,
            "deleted_runtime_rows": self.deleted_runtime_rows,
            "errors": self.errors,
            "runtime_root": str(self.runtime_root),
        }


def _minute_floor(timestamp: datetime) -> datetime:
    return timestamp.replace(second=0, microsecond=0)


def _row_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _split_source_list(value: object) -> set[str]:
    return {
        item.strip().lower()
        for item in str(value or "").split(",")
        if item.strip()
    }


def _resolve_feature_row_source(row) -> str:
    sources = _split_source_list(row["orderbook_sources"] if "orderbook_sources" in row.keys() else "")
    market_sources = _split_source_list(row["market_sources"] if "market_sources" in row.keys() else "")
    if "kis-ws" in sources:
        return "kis-ws"
    if "kis-rest-historical" in sources:
        return "kis-rest-historical"
    if PYKRX_DAILY_PROXY_SOURCE in sources:
        return PYKRX_DAILY_PROXY_SOURCE
    if sources:
        return sorted(sources)[0]
    if "kis-rest-historical" in market_sources:
        return "kis-rest-historical"
    if market_sources:
        return sorted(market_sources)[0]
    return "unknown"


def _load_labeled_feature_dataset(sqlite_store, horizon_min: int) -> tuple[list[str], list[dict[str, object]]]:
    rows = sqlite_store.fetch_feature_rows(horizon_min=horizon_min)
    if len(rows) < 5:
        raise ValueError("Not enough labeled feature rows are available for training.")

    pending_rows: list[dict[str, object]] = []
    raw_feature_names: set[str] = set()
    has_proxy_rows = False
    for row in rows:
        raw_values = {str(key): float(value) for key, value in json.loads(row["values_json"]).items()}
        feature_source = _resolve_feature_row_source(row)
        excluded_features: list[str] = []
        effective_values = dict(raw_values)
        if feature_source == PYKRX_DAILY_PROXY_SOURCE:
            has_proxy_rows = True
            excluded_features = sorted(name for name in PROXY_EXCLUDED_TRAINING_FEATURES if name in effective_values)
            for name in PROXY_EXCLUDED_TRAINING_FEATURES:
                effective_values.pop(name, None)
        raw_feature_names.update(effective_values.keys())
        pending_rows.append(
            {
                "symbol": row["symbol"],
                "event_time": _row_timestamp(str(row["event_time"])),
                "label": str(row["label"]),
                "future_return_pct": float(row["future_return_pct"]),
                "feature_source": feature_source,
                "excluded_feature_names": excluded_features,
                "raw_values": raw_values,
                "effective_values": effective_values,
            }
        )

    if has_proxy_rows:
        raw_feature_names.difference_update(PROXY_EXCLUDED_TRAINING_FEATURES)
    feature_names = sorted(raw_feature_names)
    dataset: list[dict[str, object]] = []
    for row in pending_rows:
        effective_values = dict(row.pop("effective_values"))
        values = {name: float(effective_values[name]) for name in feature_names if name in effective_values}
        if len(values) != len(feature_names):
            missing = sorted(set(feature_names).difference(values.keys()))
            raise ValueError(f"Feature row is missing required training features: {missing}")
        row["values"] = values
        row["features"] = [float(values[name]) for name in feature_names]
        dataset.append(row)
    dataset.sort(key=lambda item: (str(item["event_time"]), str(item["symbol"])))
    return feature_names, dataset


def _has_complete_direction_labels(rows: list[dict[str, object]]) -> bool:
    labels = {str(row["label"]) for row in rows}
    return {"down", "flat", "up"}.issubset(labels)


def _row_level_tail_split(dataset: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    split_index = max(1, math.floor(len(dataset) * 0.8))
    split_index = min(split_index, len(dataset) - 1)
    validation_start_time = dataset[split_index]["event_time"]
    while split_index > 0 and dataset[split_index - 1]["event_time"] == validation_start_time:
        split_index -= 1
    return dataset[:split_index], dataset[split_index:]


def _date_level_tail_split(dataset: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    trade_dates = sorted({row["event_time"].date() for row in dataset})
    if len(trade_dates) < 2:
        return [], []
    split_date_index = max(1, math.floor(len(trade_dates) * 0.8))
    split_date_index = min(split_date_index, len(trade_dates) - 1)
    validation_start_date = trade_dates[split_date_index]
    train_rows = [row for row in dataset if row["event_time"].date() < validation_start_date]
    validation_rows = [row for row in dataset if row["event_time"].date() >= validation_start_date]
    return train_rows, validation_rows


def _apply_horizon_purge(
    train_rows: list[dict[str, object]],
    validation_rows: list[dict[str, object]],
    horizon_min: int,
) -> list[dict[str, object]]:
    if horizon_min <= 0 or not validation_rows:
        return train_rows
    validation_start_time = validation_rows[0]["event_time"]
    purge_delta = timedelta(minutes=horizon_min)
    purged_train_rows = [
        row for row in train_rows
        if row["event_time"] + purge_delta < validation_start_time
    ]
    if _has_complete_direction_labels(purged_train_rows):
        return purged_train_rows
    return train_rows


def _split_window_summary(
    train_rows: list[dict[str, object]],
    validation_rows: list[dict[str, object]],
) -> dict[str, object]:
    train_dates = sorted({row["event_time"].date().isoformat() for row in train_rows})
    validation_dates = sorted({row["event_time"].date().isoformat() for row in validation_rows})
    last_train_event_time = max((row["event_time"] for row in train_rows), default=None)
    first_validation_event_time = min((row["event_time"] for row in validation_rows), default=None)
    return {
        "method": "trade_date_tail_20pct",
        "train_date_count": len(train_dates),
        "validation_date_count": len(validation_dates),
        "last_train_date": train_dates[-1] if train_dates else None,
        "first_validation_date": validation_dates[0] if validation_dates else None,
        "last_train_event_time": last_train_event_time.isoformat() if last_train_event_time else None,
        "first_validation_event_time": first_validation_event_time.isoformat()
        if first_validation_event_time
        else None,
    }


def _split_dataset(
    dataset: list[dict[str, object]],
    *,
    horizon_min: int = 0,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    train_rows, validation_rows = _date_level_tail_split(dataset)
    if not train_rows or not validation_rows or not _has_complete_direction_labels(train_rows):
        train_rows, validation_rows = _row_level_tail_split(dataset)
    return _apply_horizon_purge(train_rows, validation_rows, horizon_min), validation_rows


def _prediction_label(probability_up: float, probability_flat: float, probability_down: float) -> str:
    labels = {
        "up": probability_up,
        "flat": probability_flat,
        "down": probability_down,
    }
    return max(labels.items(), key=lambda item: item[1])[0]


def _resolve_training_run_id(sqlite_store, model_version: str, horizon_min: int) -> str:
    for row in reversed(sqlite_store.fetch_all_rows("ml_training_runs", "completed_at")):
        if row["model_version"] == model_version and int(row["horizon_min"]) == horizon_min:
            return str(row["training_run_id"])
    return f"adhoc-{model_version}"


def _estimate_trade_cost_pct(settings) -> float:
    return (
        (settings.strategy.slippage_bps * 2) / 100.0
        + (0.00015 * 2 * 100.0)
        + (0.00018 * 100.0)
    )


def _effective_trade_cost_pct(settings, override: float | None = None) -> float:
    return float(_estimate_trade_cost_pct(settings) if override is None else override)


def _effective_signal_confidence(settings, override: float | None = None) -> float:
    return float(settings.strategy.min_signal_confidence if override is None else override)


def _prediction_directional_return_pct(predicted_label: str, future_return_pct: float) -> float:
    if predicted_label == "up":
        return future_return_pct
    if predicted_label == "down":
        return -future_return_pct
    return 0.0


def _confidence_bin(confidence: float) -> str:
    if confidence < 0.60:
        return "0.58-0.60"
    if confidence < 0.65:
        return "0.60-0.65"
    if confidence < 0.70:
        return "0.65-0.70"
    if confidence < 0.75:
        return "0.70-0.75"
    return "0.75+"


def _new_prediction_direction_bucket() -> dict[str, float]:
    return {
        "count": 0.0,
        "future_return_sum": 0.0,
        "directional_return_sum": 0.0,
        "confidence_sum": 0.0,
    }


def _add_prediction_direction_stat(
    buckets: dict[str, dict[str, float]],
    *,
    predicted_label: str,
    future_return_pct: float,
    confidence: float,
) -> None:
    bucket = buckets.setdefault(predicted_label, _new_prediction_direction_bucket())
    bucket["count"] += 1
    bucket["future_return_sum"] += future_return_pct
    bucket["directional_return_sum"] += _prediction_directional_return_pct(predicted_label, future_return_pct)
    bucket["confidence_sum"] += confidence


def _finalize_prediction_direction_stats(
    buckets: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    finalized: dict[str, dict[str, float]] = {}
    for label in ("up", "down", "flat"):
        bucket = buckets.get(label, _new_prediction_direction_bucket())
        count = int(bucket["count"])
        finalized[label] = {
            "count": count,
            "average_confidence": (bucket["confidence_sum"] / count) if count else 0.0,
            "average_future_return_pct": (bucket["future_return_sum"] / count) if count else 0.0,
            "cumulative_future_return_pct": bucket["future_return_sum"],
            "average_directional_return_pct": (bucket["directional_return_sum"] / count) if count else 0.0,
            "cumulative_directional_return_pct": bucket["directional_return_sum"],
        }
    return finalized


def _merge_prediction_direction_stats(
    target: dict[str, dict[str, float]],
    finalized: dict[str, dict[str, float]],
) -> None:
    for label, stats in finalized.items():
        bucket = target.setdefault(label, _new_prediction_direction_bucket())
        bucket["count"] += int(stats.get("count", 0))
        bucket["future_return_sum"] += float(stats.get("cumulative_future_return_pct", 0.0))
        bucket["directional_return_sum"] += float(stats.get("cumulative_directional_return_pct", 0.0))
        bucket["confidence_sum"] += float(stats.get("average_confidence", 0.0)) * int(stats.get("count", 0))


def _new_trade_group_bucket() -> dict[str, float]:
    return {
        "trades": 0.0,
        "hits": 0.0,
        "wins": 0.0,
        "gross_return_sum": 0.0,
        "net_return_sum": 0.0,
        "confidence_sum": 0.0,
    }


def _add_trade_group_stat(
    buckets: dict[str, dict[str, float]],
    key: str,
    *,
    gross_return_pct: float,
    net_return_pct: float,
    confidence: float,
    is_hit: bool,
    is_win: bool,
) -> None:
    bucket = buckets.setdefault(key, _new_trade_group_bucket())
    bucket["trades"] += 1
    bucket["hits"] += 1 if is_hit else 0
    bucket["wins"] += 1 if is_win else 0
    bucket["gross_return_sum"] += gross_return_pct
    bucket["net_return_sum"] += net_return_pct
    bucket["confidence_sum"] += confidence


def _finalize_trade_group_stats(
    buckets: dict[str, dict[str, float]],
    *,
    sort_by_net: bool = False,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key, bucket in buckets.items():
        trades = int(bucket["trades"])
        rows.append(
            {
                "key": key,
                "trades": trades,
                "hit_rate": (bucket["hits"] / trades) if trades else 0.0,
                "win_rate": (bucket["wins"] / trades) if trades else 0.0,
                "average_confidence": (bucket["confidence_sum"] / trades) if trades else 0.0,
                "average_gross_return_pct": (bucket["gross_return_sum"] / trades) if trades else 0.0,
                "average_net_return_pct": (bucket["net_return_sum"] / trades) if trades else 0.0,
                "cumulative_net_return_pct": bucket["net_return_sum"],
            }
        )
    if sort_by_net:
        return sorted(rows, key=lambda item: float(item["cumulative_net_return_pct"]))
    return sorted(rows, key=lambda item: str(item["key"]))


def _summarize_trade_ledger(trade_ledger: list[dict[str, object]]) -> dict[str, object]:
    by_symbol: dict[str, dict[str, float]] = {}
    by_hour: dict[str, dict[str, float]] = {}
    by_predicted_label: dict[str, dict[str, float]] = {}
    by_confidence_bin: dict[str, dict[str, float]] = {}
    hit_gross_sum = 0.0
    hit_count = 0
    miss_gross_sum = 0.0
    miss_count = 0

    for trade in trade_ledger:
        gross_return_pct = float(trade["gross_return_pct"])
        net_return_pct = float(trade["net_return_pct"])
        confidence = float(trade["confidence"])
        is_hit = bool(trade["is_hit"])
        is_win = bool(trade["is_win"])
        event_time = str(trade["event_time"])
        hour = event_time[11:13] if len(event_time) >= 13 else "unknown"
        if is_hit:
            hit_gross_sum += gross_return_pct
            hit_count += 1
        else:
            miss_gross_sum += gross_return_pct
            miss_count += 1
        for buckets, key in (
            (by_symbol, str(trade["symbol"])),
            (by_hour, hour),
            (by_predicted_label, str(trade["predicted_label"])),
            (by_confidence_bin, _confidence_bin(confidence)),
        ):
            _add_trade_group_stat(
                buckets,
                key,
                gross_return_pct=gross_return_pct,
                net_return_pct=net_return_pct,
                confidence=confidence,
                is_hit=is_hit,
                is_win=is_win,
            )

    trades = len(trade_ledger)
    total_net = sum(float(trade["net_return_pct"]) for trade in trade_ledger)
    total_gross = sum(float(trade["gross_return_pct"]) for trade in trade_ledger)
    return {
        "trades": trades,
        "cumulative_gross_return_pct": total_gross,
        "cumulative_net_return_pct": total_net,
        "average_gross_return_pct": (total_gross / trades) if trades else 0.0,
        "average_net_return_pct": (total_net / trades) if trades else 0.0,
        "average_hit_gross_return_pct": (hit_gross_sum / hit_count) if hit_count else 0.0,
        "average_miss_gross_return_pct": (miss_gross_sum / miss_count) if miss_count else 0.0,
        "hit_count": hit_count,
        "miss_count": miss_count,
        "by_symbol": _finalize_trade_group_stats(by_symbol, sort_by_net=True),
        "by_hour": _finalize_trade_group_stats(by_hour),
        "by_predicted_label": _finalize_trade_group_stats(by_predicted_label),
        "by_confidence_bin": _finalize_trade_group_stats(by_confidence_bin),
    }


def _build_profitability_hypothesis(summary: dict[str, object]) -> str:
    hit_avg = float(summary.get("average_hit_gross_return_pct", 0.0))
    miss_avg = float(summary.get("average_miss_gross_return_pct", 0.0))
    if abs(miss_avg) > hit_avg:
        return "F-5 손실은 hit-rate보다 손익 비대칭이 핵심이며, 틀린 거래의 평균 손실이 맞춘 거래의 평균 이익보다 큽니다."
    return "F-5 손실은 소수 거래와 비용 민감도가 핵심이며, confidence가 수익 거래를 안정적으로 분리하지 못합니다."


def _fit_centroid_model(
    *,
    train_rows: list[dict[str, object]],
    feature_names: list[str],
    feature_set_version: str,
    horizon_min: int,
    model_version: str,
) -> CentroidDirectionModel:
    centroids: dict[str, list[float]] = {}
    for label in sorted({str(row["label"]) for row in train_rows}):
        label_vectors = [row["features"] for row in train_rows if row["label"] == label]
        centroid = [
            sum(vector[index] for vector in label_vectors) / len(label_vectors)
            for index in range(len(feature_names))
        ]
        centroids[label] = centroid

    artifact = CentroidArtifact(
        model_version=model_version,
        feature_set_version=feature_set_version,
        horizon_min=horizon_min,
        feature_names=feature_names,
        centroids=centroids,
    )
    return CentroidDirectionModel(artifact)


def _write_centroid_artifact(
    *,
    runtime_root: Path,
    model: CentroidDirectionModel,
) -> Path:
    artifact_dir = runtime_root / "ml" / "models"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{model.artifact.model_version}.json"
    artifact_payload = {
        "model_version": model.artifact.model_version,
        "feature_set_version": model.artifact.feature_set_version,
        "horizon_min": model.artifact.horizon_min,
        "feature_names": model.artifact.feature_names,
        "centroids": model.artifact.centroids,
    }
    artifact_path.write_text(json.dumps(artifact_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return artifact_path


def _fit_lightgbm_model(
    *,
    train_rows: list[dict[str, object]],
    feature_names: list[str],
    feature_set_version: str,
    horizon_min: int,
    model_version: str,
) -> LightGbmDirectionModel:
    labels_seen = sorted({str(row["label"]) for row in train_rows})
    if len(labels_seen) < 2:
        raise ValueError("LightGBM training requires at least two distinct labels.")

    min_child_samples = max(4, min(20, len(train_rows) // 8 or 4))
    model = LGBMClassifier(
        boosting_type="gbdt",
        objective="multiclass",
        class_weight="balanced",
        n_estimators=140 if horizon_min >= 60 else 100,
        learning_rate=0.05,
        num_leaves=31,
        max_depth=5,
        min_child_samples=min_child_samples,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
        verbose=-1,
        force_col_wise=True,
    )
    model.fit(
        np.asarray([row["features"] for row in train_rows], dtype=float),
        np.asarray([str(row["label"]) for row in train_rows], dtype=object),
    )
    artifact = LightGbmArtifact(
        model_version=model_version,
        feature_set_version=feature_set_version,
        horizon_min=horizon_min,
        feature_names=feature_names,
        class_labels=[str(label) for label in model.classes_],
    )
    return LightGbmDirectionModel(model=model, artifact=artifact)


def _write_lightgbm_artifact(
    *,
    runtime_root: Path,
    model: LightGbmDirectionModel,
) -> Path:
    artifact_dir = runtime_root / "ml" / "models"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{model.artifact.model_version}.joblib"
    model.save(artifact_path)
    return artifact_path


def _resolve_builtin_model_version(settings, horizon_min: int, builtin_name: str) -> str:
    if builtin_name == "baseline":
        return settings.model_version_h60 if horizon_min >= 60 else settings.model_version_h15
    if builtin_name == "linear_score":
        return f"linear-score-h{horizon_min}-v1"
    raise ValueError(f"Unsupported builtin model name: {builtin_name}")


def _challenger_sort_key(candidate: dict[str, object]) -> tuple[float, ...]:
    trades_taken = int(candidate["trades_taken"])
    has_trades = 1.0 if trades_taken > 0 else 0.0
    return (
        has_trades,
        float(candidate["cumulative_net_return_pct"]),
        float(candidate["trade_hit_rate"]),
        float(candidate["overall_accuracy"]),
        float(trades_taken),
        float(candidate["average_net_return_pct"]),
    )


def _challenger_ranking_score(candidate: dict[str, object]) -> float:
    trades_taken = int(candidate["trades_taken"])
    return (
        float(candidate["cumulative_net_return_pct"])
        + (float(candidate["trade_hit_rate"]) * 5.0)
        + (float(candidate["overall_accuracy"]) * 2.0)
        + (min(trades_taken, 20) * 0.02)
    )


def _recommend_challenger_action(
    *,
    active_candidate: dict[str, object],
    ranked_candidates: list[dict[str, object]],
    walk_forward_gate: dict[str, object] | None = None,
) -> tuple[str, str, str]:
    best_promotable = next((candidate for candidate in ranked_candidates if bool(candidate["promotable"])), None)
    if best_promotable is None:
        return "keep_active", str(active_candidate["model_version"]), "No promotable challenger is available."

    if str(best_promotable["model_version"]) == str(active_candidate["model_version"]):
        return "keep_active", str(active_candidate["model_version"]), "The top challenger matches the current active model."

    if int(best_promotable["trades_taken"]) < 5:
        return "keep_active", str(active_candidate["model_version"]), "The top challenger does not have enough trades."

    active_net = float(active_candidate["cumulative_net_return_pct"])
    best_net = float(best_promotable["cumulative_net_return_pct"])
    if best_net < active_net + 0.25:
        return "keep_active", str(active_candidate["model_version"]), "Net return improvement is too small."

    active_accuracy = float(active_candidate["overall_accuracy"])
    best_accuracy = float(best_promotable["overall_accuracy"])
    if best_accuracy + 0.05 < active_accuracy:
        return "keep_active", str(active_candidate["model_version"]), "Accuracy regression is too large."

    if walk_forward_gate:
        gate_status = str(walk_forward_gate.get("status", "missing"))
        gate_reason = str(walk_forward_gate.get("reason", "Walk-forward gate status is unavailable."))
        if gate_status != "pass":
            return "review_required", str(best_promotable["model_version"]), gate_reason

    return "promote", str(best_promotable["model_version"]), "Promote the challenger based on return and trade coverage."


def _load_latest_walk_forward_report(runtime_root: Path, horizon_min: int) -> dict[str, object] | None:
    report_path = runtime_root / "reports" / "backtests" / f"latest-walk-forward-h{horizon_min}.json"
    if not report_path.exists():
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_walk_forward_setup_review(payload: dict[str, object]) -> dict[str, object]:
    min_train_rows = _optional_int(payload.get("min_train_rows"))
    test_window_rows = _optional_int(payload.get("test_window_rows"))
    step_rows = _optional_int(payload.get("step_rows"))
    gap_rows = _optional_int(payload.get("gap_rows"))
    max_train_rows = _optional_int(payload.get("max_train_rows"))
    folds = _optional_int(payload.get("folds"))
    reasons: list[str] = []

    if min_train_rows is not None and min_train_rows < 1000:
        reasons.append(f"min_train_rows={min_train_rows} is below 1000")
    if test_window_rows is not None and test_window_rows < 100:
        reasons.append(f"test_window_rows={test_window_rows} is below 100")
    if max_train_rows is not None and max_train_rows < 1000:
        reasons.append(f"max_train_rows={max_train_rows} is below 1000")
    if folds is not None and folds > 5000:
        reasons.append(f"folds={folds} is above 5000")

    return {
        "status": "needs_review" if reasons else "ok",
        "reasons": reasons,
        "min_train_rows": min_train_rows,
        "test_window_rows": test_window_rows,
        "step_rows": step_rows,
        "gap_rows": gap_rows,
        "max_train_rows": max_train_rows,
        "folds": folds,
    }


def _build_walk_forward_gate(payload: dict[str, object] | None) -> dict[str, object]:
    if not payload:
        return {
            "status": "missing",
            "reason": "No latest walk-forward report is available.",
        }

    overall_accuracy = float(payload.get("overall_accuracy", 0.0))
    cumulative_net = float(payload.get("cumulative_net_return_pct", 0.0))
    gap_rows = int(payload.get("gap_rows", 0) or 0)
    max_train_rows = payload.get("max_train_rows")
    fold_summaries = payload.get("fold_summaries", [])
    setup_review = _build_walk_forward_setup_review(payload)
    base_fields = {
        "overall_accuracy": overall_accuracy,
        "cumulative_net_return_pct": cumulative_net,
        "gap_rows": gap_rows,
        "max_train_rows": max_train_rows,
        "setup_status": setup_review["status"],
        "setup_reasons": setup_review["reasons"],
        "min_train_rows": setup_review["min_train_rows"],
        "test_window_rows": setup_review["test_window_rows"],
        "step_rows": setup_review["step_rows"],
        "folds": setup_review["folds"],
    }

    weakest_fold_accuracy = None
    if isinstance(fold_summaries, list) and fold_summaries:
        fold_accuracies = [
            float(fold.get("overall_accuracy", 0.0))
            for fold in fold_summaries
            if isinstance(fold, dict)
        ]
        if fold_accuracies:
            weakest_fold_accuracy = min(fold_accuracies)

    if setup_review["status"] == "needs_review":
        return {
            "status": "needs_review",
            "reason": "Walk-forward setup needs review (" + "; ".join(str(item) for item in setup_review["reasons"]) + ").",
            "weakest_fold_accuracy": weakest_fold_accuracy,
            **base_fields,
        }

    if overall_accuracy < 0.55:
        return {
            "status": "needs_review",
            "reason": f"Walk-forward overall accuracy is too low ({overall_accuracy:.4f}).",
            "weakest_fold_accuracy": weakest_fold_accuracy,
            **base_fields,
        }

    if weakest_fold_accuracy is not None and weakest_fold_accuracy <= 0.0:
        return {
            "status": "needs_review",
            "reason": "At least one walk-forward fold has zero accuracy.",
            "weakest_fold_accuracy": weakest_fold_accuracy,
            **base_fields,
        }

    if cumulative_net <= 0.0:
        return {
            "status": "needs_review",
            "reason": f"Walk-forward cumulative net return is not positive ({cumulative_net:.4f}).",
            "weakest_fold_accuracy": weakest_fold_accuracy,
            **base_fields,
        }

    return {
        "status": "pass",
        "reason": "Walk-forward gate passed.",
        "weakest_fold_accuracy": weakest_fold_accuracy,
        **base_fields,
    }


def _evaluate_rows_with_model(
    *,
    rows: list[dict[str, object]],
    model,
    settings,
    horizon_min: int,
    prediction_prefix: str,
    trade_cost_pct_override: float | None = None,
    min_signal_confidence_override: float | None = None,
    trade_ledger: list[dict[str, object]] | None = None,
    fold_number: int | None = None,
    collect_prediction_stats: bool = True,
) -> dict[str, object]:
    trade_cost_pct = _effective_trade_cost_pct(settings, trade_cost_pct_override)
    min_signal_confidence = _effective_signal_confidence(settings, min_signal_confidence_override)
    rows_evaluated = len(rows)
    overall_correct = 0
    trades_taken = 0
    trade_correct = 0
    wins = 0
    gross_return_sum = 0.0
    net_return_sum = 0.0
    confidence_sum = 0.0
    actual_counter: Counter[str] = Counter()
    predicted_counter: Counter[str] = Counter()
    prediction_direction_buckets: dict[str, dict[str, float]] = {}

    model_version = getattr(getattr(model, "artifact", None), "model_version", None)
    if model_version is None:
        model_version = "unknown-model"

    for index, row in enumerate(rows, start=1):
        feature_snapshot = FeatureSnapshot(
            symbol=str(row["symbol"]),
            event_time=row["event_time"],
            feature_set_version=settings.feature_set_version,
            values=dict(row["values"]),
        )
        prediction = model.predict(
            feature_snapshot=feature_snapshot,
            horizon_min=horizon_min,
            prediction_id=f"{prediction_prefix}-{index:06d}",
        )
        model_version = prediction.model_version
        predicted_label = _prediction_label(
            prediction.probability_up,
            prediction.probability_flat,
            prediction.probability_down,
        )
        probability_pairs = sorted(
            [
                ("up", prediction.probability_up),
                ("flat", prediction.probability_flat),
                ("down", prediction.probability_down),
            ],
            key=lambda item: item[1],
            reverse=True,
        )
        actual_label = str(row["label"])
        confidence = max(prediction.probability_up, prediction.probability_flat, prediction.probability_down)
        confidence_margin = probability_pairs[0][1] - probability_pairs[1][1]
        future_return_pct = float(row["future_return_pct"])
        actual_counter[actual_label] += 1
        predicted_counter[predicted_label] += 1
        confidence_sum += confidence
        if collect_prediction_stats:
            _add_prediction_direction_stat(
                prediction_direction_buckets,
                predicted_label=predicted_label,
                future_return_pct=future_return_pct,
                confidence=confidence,
            )

        if predicted_label == actual_label:
            overall_correct += 1

        if predicted_label != "up" or prediction.probability_up < min_signal_confidence:
            continue

        trades_taken += 1
        gross_return_sum += future_return_pct
        net_return_pct = future_return_pct - trade_cost_pct
        net_return_sum += net_return_pct
        is_hit = actual_label == "up"
        is_win = net_return_pct > 0
        if is_hit:
            trade_correct += 1
        if is_win:
            wins += 1
        if trade_ledger is not None:
            event_time = row["event_time"]
            trade_ledger.append(
                {
                    "fold": fold_number,
                    "row_index": index,
                    "symbol": str(row["symbol"]),
                    "event_time": event_time.isoformat() if isinstance(event_time, datetime) else str(event_time),
                    "predicted_label": predicted_label,
                    "actual_label": actual_label,
                    "probability_up": prediction.probability_up,
                    "probability_flat": prediction.probability_flat,
                    "probability_down": prediction.probability_down,
                    "confidence": confidence,
                    "confidence_margin": confidence_margin,
                    "future_return_pct": future_return_pct,
                    "gross_return_pct": future_return_pct,
                    "trade_cost_pct": trade_cost_pct,
                    "net_return_pct": net_return_pct,
                    "is_hit": is_hit,
                    "is_win": is_win,
                }
            )

    metrics = {
        "model_version": model_version,
        "rows_evaluated": rows_evaluated,
        "trades_taken": trades_taken,
        "overall_correct": overall_correct,
        "overall_accuracy": (overall_correct / rows_evaluated) if rows_evaluated else 0.0,
        "trade_hit_rate": (trade_correct / trades_taken) if trades_taken else 0.0,
        "win_rate": (wins / trades_taken) if trades_taken else 0.0,
        "average_confidence": (confidence_sum / rows_evaluated) if rows_evaluated else 0.0,
        "average_gross_return_pct": (gross_return_sum / trades_taken) if trades_taken else 0.0,
        "average_net_return_pct": (net_return_sum / trades_taken) if trades_taken else 0.0,
        "cumulative_gross_return_pct": gross_return_sum,
        "cumulative_net_return_pct": net_return_sum,
        "trade_cost_pct": trade_cost_pct,
        "signal_confidence_threshold": min_signal_confidence,
        "actual_label_counts": dict(actual_counter),
        "predicted_label_counts": dict(predicted_counter),
    }
    if collect_prediction_stats:
        metrics["prediction_direction_stats"] = _finalize_prediction_direction_stats(prediction_direction_buckets)
    return metrics


def _score_rows_with_model(
    *,
    rows: list[dict[str, object]],
    model,
    settings,
    horizon_min: int,
    prediction_prefix: str,
    fold_number: int | None = None,
) -> list[dict[str, object]]:
    scored_rows: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        feature_snapshot = FeatureSnapshot(
            symbol=str(row["symbol"]),
            event_time=row["event_time"],
            feature_set_version=settings.feature_set_version,
            values=dict(row["values"]),
        )
        prediction = model.predict(
            feature_snapshot=feature_snapshot,
            horizon_min=horizon_min,
            prediction_id=f"{prediction_prefix}-{index:06d}",
        )
        predicted_label = _prediction_label(
            prediction.probability_up,
            prediction.probability_flat,
            prediction.probability_down,
        )
        probability_pairs = sorted(
            [
                ("up", prediction.probability_up),
                ("flat", prediction.probability_flat),
                ("down", prediction.probability_down),
            ],
            key=lambda item: item[1],
            reverse=True,
        )
        event_time = row["event_time"]
        scored_rows.append(
            {
                "fold": fold_number,
                "row_index": index,
                "symbol": str(row["symbol"]),
                "event_time": event_time.isoformat() if isinstance(event_time, datetime) else str(event_time),
                "actual_label": str(row["label"]),
                "predicted_label": predicted_label,
                "probability_up": prediction.probability_up,
                "probability_flat": prediction.probability_flat,
                "probability_down": prediction.probability_down,
                "confidence": probability_pairs[0][1],
                "confidence_margin": probability_pairs[0][1] - probability_pairs[1][1],
                "future_return_pct": float(row["future_return_pct"]),
                "model_version": prediction.model_version,
            }
        )
    return scored_rows


def _metrics_from_scored_predictions(
    *,
    scored_rows: list[dict[str, object]],
    settings,
    trade_cost_pct: float,
    signal_confidence_threshold: float,
    trade_ledger: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    rows_evaluated = len(scored_rows)
    overall_correct = 0
    trades_taken = 0
    trade_correct = 0
    wins = 0
    gross_return_sum = 0.0
    net_return_sum = 0.0
    confidence_sum = 0.0
    actual_counter: Counter[str] = Counter()
    predicted_counter: Counter[str] = Counter()
    prediction_direction_buckets: dict[str, dict[str, float]] = {}
    model_version = "unknown-model"

    for record in scored_rows:
        model_version = str(record.get("model_version", model_version))
        predicted_label = str(record["predicted_label"])
        actual_label = str(record["actual_label"])
        confidence = float(record["confidence"])
        probability_up = float(record["probability_up"])
        future_return_pct = float(record["future_return_pct"])
        actual_counter[actual_label] += 1
        predicted_counter[predicted_label] += 1
        confidence_sum += confidence
        _add_prediction_direction_stat(
            prediction_direction_buckets,
            predicted_label=predicted_label,
            future_return_pct=future_return_pct,
            confidence=confidence,
        )
        if predicted_label == actual_label:
            overall_correct += 1
        if predicted_label != "up" or probability_up < signal_confidence_threshold:
            continue
        trades_taken += 1
        gross_return_sum += future_return_pct
        net_return_pct = future_return_pct - trade_cost_pct
        net_return_sum += net_return_pct
        is_hit = actual_label == "up"
        is_win = net_return_pct > 0
        if is_hit:
            trade_correct += 1
        if is_win:
            wins += 1
        if trade_ledger is not None:
            ledger_record = dict(record)
            ledger_record.update(
                {
                    "gross_return_pct": future_return_pct,
                    "trade_cost_pct": trade_cost_pct,
                    "net_return_pct": net_return_pct,
                    "is_hit": is_hit,
                    "is_win": is_win,
                }
            )
            trade_ledger.append(ledger_record)

    return {
        "model_version": model_version,
        "rows_evaluated": rows_evaluated,
        "trades_taken": trades_taken,
        "overall_correct": overall_correct,
        "overall_accuracy": (overall_correct / rows_evaluated) if rows_evaluated else 0.0,
        "trade_hit_rate": (trade_correct / trades_taken) if trades_taken else 0.0,
        "win_rate": (wins / trades_taken) if trades_taken else 0.0,
        "average_confidence": (confidence_sum / rows_evaluated) if rows_evaluated else 0.0,
        "average_gross_return_pct": (gross_return_sum / trades_taken) if trades_taken else 0.0,
        "average_net_return_pct": (net_return_sum / trades_taken) if trades_taken else 0.0,
        "cumulative_gross_return_pct": gross_return_sum,
        "cumulative_net_return_pct": net_return_sum,
        "trade_cost_pct": trade_cost_pct,
        "signal_confidence_threshold": signal_confidence_threshold,
        "actual_label_counts": dict(actual_counter),
        "predicted_label_counts": dict(predicted_counter),
        "prediction_direction_stats": _finalize_prediction_direction_stats(prediction_direction_buckets),
    }


def _cybos_feature_set_names(feature_set_name: str) -> list[str]:
    try:
        return list(CYBOS_EXPERIMENT_FEATURE_SETS[feature_set_name])
    except KeyError as exc:
        supported = ", ".join(sorted(CYBOS_EXPERIMENT_FEATURE_SETS))
        raise ValueError(f"Unsupported Cybos experiment feature set: {feature_set_name}. Supported: {supported}") from exc


def _market_minute_slot_pct(event_time: datetime) -> float:
    regular_open_minute = (9 * 60)
    regular_close_minute = (15 * 60) + 30
    total_minutes = max(1, regular_close_minute - regular_open_minute)
    current_minute = (event_time.hour * 60) + event_time.minute
    return min(1.0, max(0.0, (current_minute - regular_open_minute) / total_minutes))


def _bar_return_pct(bar: MinuteBar) -> float:
    if bar.open <= 0:
        return 0.0
    return ((bar.close - bar.open) / bar.open) * 100


def _bar_hl_range_pct(bar: MinuteBar) -> float:
    if bar.open <= 0:
        return 0.0
    return ((bar.high - bar.low) / bar.open) * 100


def _build_bar_feature_values(bar: MinuteBar, previous_bar: MinuteBar | None) -> dict[str, float]:
    bar_range = bar.high - bar.low
    close_position_pct = ((bar.close - bar.low) / bar_range) * 100 if bar_range > 0 else 50.0
    previous_return = _bar_return_pct(previous_bar) if previous_bar is not None else 0.0
    previous_range = _bar_hl_range_pct(previous_bar) if previous_bar is not None else 0.0
    previous_log_volume = math.log1p(previous_bar.volume) if previous_bar is not None else math.log1p(bar.volume)
    return {
        "avg_trade_size": bar.volume / max(bar.trade_count, 1),
        "hl_range_pct": _bar_hl_range_pct(bar),
        "return_1m_pct": _bar_return_pct(bar),
        "close_position_pct": close_position_pct,
        "minute_slot_pct": _market_minute_slot_pct(bar.bar_time),
        "log_volume": math.log1p(bar.volume),
        "prev_return_pct": previous_return,
        "prev_hl_range_pct": previous_range,
        "log_volume_delta": math.log1p(bar.volume) - previous_log_volume,
    }


def _build_bar_training_row(
    *,
    bar: MinuteBar,
    previous_bar: MinuteBar | None,
    future_bar: MinuteBar,
    horizon_min: int,
    threshold_pct: float,
    feature_source: str,
    feature_names: list[str],
) -> dict[str, object] | None:
    if bar.open <= 0 or bar.close <= 0:
        return None
    future_return_pct = ((future_bar.close - bar.close) / bar.close) * 100
    values = _build_bar_feature_values(bar, previous_bar)
    return {
        "symbol": bar.symbol,
        "event_time": bar.bar_time,
        "label": classify_return(future_return_pct, threshold_pct),
        "future_return_pct": future_return_pct,
        "feature_source": feature_source,
        "values": values,
        "features": [float(values[name]) for name in feature_names],
        "horizon_min": horizon_min,
    }


def _source_bar_train_validation_rows(
    *,
    sqlite_store,
    source: str,
    horizon_min: int,
    threshold_pct: float,
    train_max_rows: int,
    feature_set_name: str,
    label_sensitivity_thresholds: tuple[float, ...] | None = None,
) -> dict[str, object]:
    feature_names = _cybos_feature_set_names(feature_set_name)
    label_sensitivity_counts: dict[str, Counter[str]] = {
        _threshold_key(threshold): Counter()
        for threshold in (label_sensitivity_thresholds or ())
    }
    trade_dates = sqlite_store.fetch_market_source_trade_dates(source)
    if len(trade_dates) < 5:
        raise ValueError(f"Not enough trade dates are available for source={source}.")
    split_date_index = max(1, math.floor(len(trade_dates) * 0.8))
    split_date_index = min(split_date_index, len(trade_dates) - 1)
    validation_start_date = datetime.fromisoformat(trade_dates[split_date_index]).date()

    symbols = sqlite_store.fetch_market_source_symbols(source)
    if not symbols:
        raise ValueError(f"No symbols are available for source={source}.")

    train_heap: list[tuple[tuple[float, str], dict[str, object]]] = []
    validation_rows: list[dict[str, object]] = []
    label_counts: Counter[str] = Counter()
    source_rows = 0
    labeled_rows = 0
    first_event_time: datetime | None = None
    last_event_time: datetime | None = None

    for symbol in symbols:
        bars: list[MinuteBar] = []
        for row in sqlite_store.fetch_minute_bars_for_market_source(source, symbol=symbol):
            bar = MinuteBar(
                symbol=str(row["symbol"]),
                bar_time=_row_timestamp(str(row["bar_time"])),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                trade_count=int(row["trade_count"]),
            )
            bars.append(bar)
        if not bars:
            continue
        bars.sort(key=lambda item: item.bar_time)
        source_rows += len(bars)
        bar_times = [bar.bar_time for bar in bars]
        for index, bar in enumerate(bars):
            target_time = bar.bar_time + timedelta(minutes=horizon_min)
            future_bar = _find_first_same_day_future_bar(bars, bar_times, target_time)
            if future_bar is None:
                continue
            previous_bar = bars[index - 1] if index > 0 and bars[index - 1].bar_time.date() == bar.bar_time.date() else None
            item = _build_bar_training_row(
                bar=bar,
                previous_bar=previous_bar,
                future_bar=future_bar,
                horizon_min=horizon_min,
                threshold_pct=threshold_pct,
                feature_source=source,
                feature_names=feature_names,
            )
            if item is None:
                continue
            labeled_rows += 1
            label_counts[str(item["label"])] += 1
            for sensitivity_threshold in label_sensitivity_thresholds or ():
                label_sensitivity_counts[_threshold_key(sensitivity_threshold)][
                    classify_return(float(item["future_return_pct"]), sensitivity_threshold)
                ] += 1
            event_time = item["event_time"]
            if isinstance(event_time, datetime):
                first_event_time = event_time if first_event_time is None else min(first_event_time, event_time)
                last_event_time = event_time if last_event_time is None else max(last_event_time, event_time)
                if event_time.date() >= validation_start_date:
                    validation_rows.append(item)
                else:
                    heap_key = (event_time.timestamp(), str(item["symbol"]))
                    if len(train_heap) < train_max_rows:
                        heapq.heappush(train_heap, (heap_key, item))
                    elif heap_key > train_heap[0][0]:
                        heapq.heapreplace(train_heap, (heap_key, item))

    train_rows = [item for _, item in sorted(train_heap, key=lambda pair: pair[0])]
    validation_rows.sort(key=lambda item: (item["event_time"], str(item["symbol"])))
    if len(train_rows) < 5 or len(validation_rows) < 5:
        raise ValueError(
            f"Not enough source={source} bar-only rows for experiment "
            f"(train={len(train_rows)}, validation={len(validation_rows)})."
        )
    if not _has_complete_direction_labels(train_rows):
        raise ValueError(f"Training window for source={source} does not contain down/flat/up labels.")

    return {
        "source": source,
        "feature_set_name": feature_set_name,
        "feature_names": feature_names,
        "symbols": symbols,
        "trade_dates": trade_dates,
        "validation_start_date": validation_start_date.isoformat(),
        "source_rows": source_rows,
        "labeled_rows": labeled_rows,
        "label_counts": dict(label_counts),
        "label_sensitivity_counts": {
            threshold: dict(counts)
            for threshold, counts in label_sensitivity_counts.items()
        },
        "first_event_time": first_event_time.isoformat() if first_event_time else None,
        "last_event_time": last_event_time.isoformat() if last_event_time else None,
        "train_rows": train_rows,
        "validation_rows": validation_rows,
    }


def _source_bar_period_rows(
    *,
    sqlite_store,
    source: str,
    horizon_min: int,
    threshold_pct: float,
    feature_set_name: str,
    periods: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    feature_names = _cybos_feature_set_names(feature_set_name)
    period_state: dict[str, dict[str, object]] = {}
    for period in periods:
        name = str(period["name"])
        period_state[name] = {
            "name": name,
            "start_date": str(period["start_date"]),
            "end_date": str(period["end_date"]),
            "max_rows": int(period["max_rows"]),
            "rows_heap": [],
            "label_counts": Counter(),
            "source_rows": 0,
            "labeled_rows": 0,
            "first_event_time": None,
            "last_event_time": None,
        }

    symbols = sqlite_store.fetch_market_source_symbols(source)
    if not symbols:
        raise ValueError(f"No symbols are available for source={source}.")

    for symbol in symbols:
        bars: list[MinuteBar] = []
        for row in sqlite_store.fetch_minute_bars_for_market_source(source, symbol=symbol):
            bar = MinuteBar(
                symbol=str(row["symbol"]),
                bar_time=_row_timestamp(str(row["bar_time"])),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                trade_count=int(row["trade_count"]),
            )
            bars.append(bar)
        if not bars:
            continue
        bars.sort(key=lambda item: item.bar_time)
        bar_times = [bar.bar_time for bar in bars]
        for index, bar in enumerate(bars):
            bar_date = bar.bar_time.date().isoformat()
            matched_periods = [
                state
                for state in period_state.values()
                if str(state["start_date"]) <= bar_date <= str(state["end_date"])
            ]
            if not matched_periods:
                continue
            for state in matched_periods:
                state["source_rows"] = int(state["source_rows"]) + 1
            target_time = bar.bar_time + timedelta(minutes=horizon_min)
            future_bar = _find_first_same_day_future_bar(bars, bar_times, target_time)
            if future_bar is None:
                continue
            previous_bar = bars[index - 1] if index > 0 and bars[index - 1].bar_time.date() == bar.bar_time.date() else None
            item = _build_bar_training_row(
                bar=bar,
                previous_bar=previous_bar,
                future_bar=future_bar,
                horizon_min=horizon_min,
                threshold_pct=threshold_pct,
                feature_source=source,
                feature_names=feature_names,
            )
            if item is None:
                continue
            for state in matched_periods:
                state["labeled_rows"] = int(state["labeled_rows"]) + 1
                label_counts = state["label_counts"]
                if isinstance(label_counts, Counter):
                    label_counts[str(item["label"])] += 1
                first_event_time = state["first_event_time"]
                last_event_time = state["last_event_time"]
                if first_event_time is None or bar.bar_time < first_event_time:
                    state["first_event_time"] = bar.bar_time
                if last_event_time is None or bar.bar_time > last_event_time:
                    state["last_event_time"] = bar.bar_time
                rows_heap = state["rows_heap"]
                if not isinstance(rows_heap, list):
                    continue
                heap_key = (bar.bar_time.timestamp(), str(item["symbol"]))
                max_rows = int(state["max_rows"])
                if len(rows_heap) < max_rows:
                    heapq.heappush(rows_heap, (heap_key, item))
                elif heap_key > rows_heap[0][0]:
                    heapq.heapreplace(rows_heap, (heap_key, item))

    results: dict[str, dict[str, object]] = {}
    for name, state in period_state.items():
        rows_heap = state["rows_heap"]
        rows = [item for _, item in sorted(rows_heap, key=lambda pair: pair[0])] if isinstance(rows_heap, list) else []
        label_counts = state["label_counts"]
        first_event_time = state["first_event_time"]
        last_event_time = state["last_event_time"]
        results[name] = {
            "name": name,
            "start_date": state["start_date"],
            "end_date": state["end_date"],
            "max_rows": state["max_rows"],
            "source_rows": state["source_rows"],
            "labeled_rows": state["labeled_rows"],
            "selected_rows": len(rows),
            "label_counts": dict(label_counts) if isinstance(label_counts, Counter) else {},
            "first_event_time": first_event_time.isoformat() if isinstance(first_event_time, datetime) else None,
            "last_event_time": last_event_time.isoformat() if isinstance(last_event_time, datetime) else None,
            "rows": rows,
        }
    return results


def _lightgbm_feature_importance(model: LightGbmDirectionModel) -> list[dict[str, object]]:
    importances = getattr(model.model, "feature_importances_", None)
    if importances is None:
        return []
    pairs = [
        {"feature": feature, "importance": int(importance)}
        for feature, importance in zip(model.artifact.feature_names, importances)
    ]
    return sorted(pairs, key=lambda item: int(item["importance"]), reverse=True)


def _run_lightgbm_walk_forward(
    *,
    rows: list[dict[str, object]],
    feature_names: list[str],
    settings,
    horizon_min: int,
    train_rows: int,
    test_rows: int,
    gap_rows: int,
    step_rows: int,
    max_folds: int,
    feature_set_name: str,
    trade_cost_pct: float | None = None,
    signal_confidence_threshold: float | None = None,
    collect_trade_ledger: bool = False,
    collect_prediction_stats: bool = True,
) -> dict[str, object]:
    if len(rows) < train_rows + gap_rows + test_rows:
        raise ValueError("Not enough rows for LightGBM walk-forward evaluation.")
    train_end_values = list(range(train_rows, len(rows) - gap_rows - test_rows + 1, step_rows))
    if max_folds > 0 and len(train_end_values) > max_folds:
        selected_indices = np.linspace(0, len(train_end_values) - 1, max_folds, dtype=int)
        train_end_values = [train_end_values[int(index)] for index in selected_indices]

    aggregate_rows = 0
    aggregate_trades = 0
    aggregate_correct = 0
    aggregate_trade_hits = 0.0
    aggregate_wins = 0.0
    aggregate_gross = 0.0
    aggregate_net = 0.0
    aggregate_actual: Counter[str] = Counter()
    aggregate_predicted: Counter[str] = Counter()
    aggregate_prediction_direction: dict[str, dict[str, float]] = {}
    trade_ledger: list[dict[str, object]] = []
    fold_summaries: list[dict[str, object]] = []
    effective_trade_cost_pct = _effective_trade_cost_pct(settings, trade_cost_pct)
    effective_signal_confidence = _effective_signal_confidence(settings, signal_confidence_threshold)

    for fold_number, train_end in enumerate(train_end_values, start=1):
        train_start = max(0, train_end - train_rows)
        fold_train = rows[train_start:train_end]
        test_start = train_end + gap_rows
        fold_test = rows[test_start : test_start + test_rows]
        if not _has_complete_direction_labels(fold_train) or not fold_test:
            continue
        model = _fit_lightgbm_model(
            train_rows=fold_train,
            feature_names=feature_names,
            feature_set_version=f"{settings.feature_set_version}-{feature_set_name}",
            horizon_min=horizon_min,
            model_version=f"lightgbm-cybos-{feature_set_name.replace('_', '-')}-wf-h{horizon_min}-v1",
        )
        metrics = _evaluate_rows_with_model(
            rows=fold_test,
            model=model,
            settings=settings,
            horizon_min=horizon_min,
            prediction_prefix=f"cybos-{feature_set_name}-wf-{fold_number}",
            trade_cost_pct_override=effective_trade_cost_pct,
            min_signal_confidence_override=effective_signal_confidence,
            trade_ledger=trade_ledger if collect_trade_ledger else None,
            fold_number=fold_number,
            collect_prediction_stats=collect_prediction_stats,
        )
        rows_evaluated = int(metrics["rows_evaluated"])
        trades_taken = int(metrics["trades_taken"])
        aggregate_rows += rows_evaluated
        aggregate_trades += trades_taken
        aggregate_correct += int(metrics["overall_correct"])
        aggregate_trade_hits += float(metrics["trade_hit_rate"]) * trades_taken
        aggregate_wins += float(metrics["win_rate"]) * trades_taken
        aggregate_gross += float(metrics["cumulative_gross_return_pct"])
        aggregate_net += float(metrics["cumulative_net_return_pct"])
        aggregate_actual.update(metrics["actual_label_counts"])
        aggregate_predicted.update(metrics["predicted_label_counts"])
        if collect_prediction_stats:
            _merge_prediction_direction_stats(
                aggregate_prediction_direction,
                metrics.get("prediction_direction_stats", {}),
            )
        fold_summaries.append(
            {
                "fold": fold_number,
                "train_start_row": train_start,
                "train_end_row": train_end - 1,
                "test_start_row": test_start,
                "test_end_row": test_start + rows_evaluated - 1,
                "train_start_event_time": fold_train[0]["event_time"].isoformat(),
                "train_end_event_time": fold_train[-1]["event_time"].isoformat(),
                "test_start_event_time": fold_test[0]["event_time"].isoformat(),
                "test_end_event_time": fold_test[-1]["event_time"].isoformat(),
                "overall_accuracy": float(metrics["overall_accuracy"]),
                "trades_taken": trades_taken,
                "trade_hit_rate": float(metrics["trade_hit_rate"]),
                "cumulative_net_return_pct": float(metrics["cumulative_net_return_pct"]),
                "trade_cost_pct": effective_trade_cost_pct,
                "signal_confidence_threshold": effective_signal_confidence,
            }
        )

    if aggregate_rows <= 0:
        raise ValueError("LightGBM walk-forward did not produce any folds.")
    result = {
        "folds": len(fold_summaries),
        "rows_evaluated": aggregate_rows,
        "trades_taken": aggregate_trades,
        "overall_accuracy": aggregate_correct / aggregate_rows,
        "trade_hit_rate": aggregate_trade_hits / aggregate_trades if aggregate_trades else 0.0,
        "win_rate": aggregate_wins / aggregate_trades if aggregate_trades else 0.0,
        "cumulative_gross_return_pct": aggregate_gross,
        "cumulative_net_return_pct": aggregate_net,
        "average_net_return_pct": aggregate_net / aggregate_trades if aggregate_trades else 0.0,
        "trade_cost_pct": effective_trade_cost_pct,
        "signal_confidence_threshold": effective_signal_confidence,
        "actual_label_counts": dict(aggregate_actual),
        "predicted_label_counts": dict(aggregate_predicted),
        "train_rows": train_rows,
        "test_rows": test_rows,
        "gap_rows": gap_rows,
        "step_rows": step_rows,
        "max_folds": max_folds,
        "fold_summaries": fold_summaries,
    }
    if collect_prediction_stats:
        result["prediction_direction_stats"] = _finalize_prediction_direction_stats(aggregate_prediction_direction)
    if collect_trade_ledger:
        result["trade_ledger"] = trade_ledger
    return result


def _run_lightgbm_walk_forward_train_only_threshold(
    *,
    rows: list[dict[str, object]],
    feature_names: list[str],
    settings,
    horizon_min: int,
    train_rows: int,
    test_rows: int,
    gap_rows: int,
    step_rows: int,
    max_folds: int,
    feature_set_name: str,
    trade_cost_pct: float,
    threshold_grid: tuple[float, ...],
    threshold_calibration_rows: int = 20_000,
    min_train_trades: int = 10,
) -> dict[str, object]:
    if len(rows) < train_rows + gap_rows + test_rows:
        raise ValueError("Not enough rows for threshold walk-forward evaluation.")
    train_end_values = list(range(train_rows, len(rows) - gap_rows - test_rows + 1, step_rows))
    if max_folds > 0 and len(train_end_values) > max_folds:
        selected_indices = np.linspace(0, len(train_end_values) - 1, max_folds, dtype=int)
        train_end_values = [train_end_values[int(index)] for index in selected_indices]

    aggregate_rows = 0
    aggregate_trades = 0
    aggregate_correct = 0
    aggregate_trade_hits = 0.0
    aggregate_wins = 0.0
    aggregate_gross = 0.0
    aggregate_net = 0.0
    aggregate_actual: Counter[str] = Counter()
    aggregate_predicted: Counter[str] = Counter()
    aggregate_prediction_direction: dict[str, dict[str, float]] = {}
    trade_ledger: list[dict[str, object]] = []
    fold_summaries: list[dict[str, object]] = []
    thresholds = tuple(sorted({float(item) for item in threshold_grid}))
    default_threshold = _effective_signal_confidence(settings)

    for fold_number, train_end in enumerate(train_end_values, start=1):
        train_start = max(0, train_end - train_rows)
        fold_train = rows[train_start:train_end]
        test_start = train_end + gap_rows
        fold_test = rows[test_start : test_start + test_rows]
        if not _has_complete_direction_labels(fold_train) or not fold_test:
            continue
        model = _fit_lightgbm_model(
            train_rows=fold_train,
            feature_names=feature_names,
            feature_set_version=f"{settings.feature_set_version}-{feature_set_name}-threshold",
            horizon_min=horizon_min,
            model_version=f"lightgbm-cybos-{feature_set_name.replace('_', '-')}-threshold-h{horizon_min}-v1",
        )
        calibration_rows = fold_train[-min(len(fold_train), threshold_calibration_rows) :]
        scored_calibration = _score_rows_with_model(
            rows=calibration_rows,
            model=model,
            settings=settings,
            horizon_min=horizon_min,
            prediction_prefix=f"cybos-{feature_set_name}-threshold-cal-{fold_number}",
            fold_number=fold_number,
        )
        threshold_candidates: list[dict[str, object]] = []
        for threshold in thresholds:
            candidate_metrics = _metrics_from_scored_predictions(
                scored_rows=scored_calibration,
                settings=settings,
                trade_cost_pct=trade_cost_pct,
                signal_confidence_threshold=threshold,
            )
            threshold_candidates.append(
                {
                    "threshold": threshold,
                    "eligible": int(candidate_metrics["trades_taken"]) >= min_train_trades,
                    "trades_taken": int(candidate_metrics["trades_taken"]),
                    "trade_hit_rate": float(candidate_metrics["trade_hit_rate"]),
                    "cumulative_net_return_pct": float(candidate_metrics["cumulative_net_return_pct"]),
                }
            )
        eligible_candidates = [candidate for candidate in threshold_candidates if bool(candidate["eligible"])]
        if eligible_candidates:
            selected = max(
                eligible_candidates,
                key=lambda item: (
                    float(item["cumulative_net_return_pct"]),
                    float(item["trade_hit_rate"]),
                    int(item["trades_taken"]),
                ),
            )
        else:
            selected = min(threshold_candidates, key=lambda item: abs(float(item["threshold"]) - default_threshold))

        selected_threshold = float(selected["threshold"])
        scored_test = _score_rows_with_model(
            rows=fold_test,
            model=model,
            settings=settings,
            horizon_min=horizon_min,
            prediction_prefix=f"cybos-{feature_set_name}-threshold-test-{fold_number}",
            fold_number=fold_number,
        )
        metrics = _metrics_from_scored_predictions(
            scored_rows=scored_test,
            settings=settings,
            trade_cost_pct=trade_cost_pct,
            signal_confidence_threshold=selected_threshold,
            trade_ledger=trade_ledger,
        )
        rows_evaluated = int(metrics["rows_evaluated"])
        trades_taken = int(metrics["trades_taken"])
        aggregate_rows += rows_evaluated
        aggregate_trades += trades_taken
        aggregate_correct += int(metrics["overall_correct"])
        aggregate_trade_hits += float(metrics["trade_hit_rate"]) * trades_taken
        aggregate_wins += float(metrics["win_rate"]) * trades_taken
        aggregate_gross += float(metrics["cumulative_gross_return_pct"])
        aggregate_net += float(metrics["cumulative_net_return_pct"])
        aggregate_actual.update(metrics["actual_label_counts"])
        aggregate_predicted.update(metrics["predicted_label_counts"])
        _merge_prediction_direction_stats(
            aggregate_prediction_direction,
            metrics.get("prediction_direction_stats", {}),
        )
        fold_summaries.append(
            {
                "fold": fold_number,
                "train_start_row": train_start,
                "train_end_row": train_end - 1,
                "test_start_row": test_start,
                "test_end_row": test_start + rows_evaluated - 1,
                "train_start_event_time": fold_train[0]["event_time"].isoformat(),
                "train_end_event_time": fold_train[-1]["event_time"].isoformat(),
                "test_start_event_time": fold_test[0]["event_time"].isoformat(),
                "test_end_event_time": fold_test[-1]["event_time"].isoformat(),
                "selected_threshold": selected_threshold,
                "threshold_selection": selected,
                "threshold_candidates": threshold_candidates,
                "overall_accuracy": float(metrics["overall_accuracy"]),
                "trades_taken": trades_taken,
                "trade_hit_rate": float(metrics["trade_hit_rate"]),
                "cumulative_net_return_pct": float(metrics["cumulative_net_return_pct"]),
            }
        )

    if aggregate_rows <= 0:
        raise ValueError("Threshold walk-forward did not produce any folds.")
    return {
        "folds": len(fold_summaries),
        "rows_evaluated": aggregate_rows,
        "trades_taken": aggregate_trades,
        "overall_accuracy": aggregate_correct / aggregate_rows,
        "trade_hit_rate": aggregate_trade_hits / aggregate_trades if aggregate_trades else 0.0,
        "win_rate": aggregate_wins / aggregate_trades if aggregate_trades else 0.0,
        "cumulative_gross_return_pct": aggregate_gross,
        "cumulative_net_return_pct": aggregate_net,
        "average_net_return_pct": aggregate_net / aggregate_trades if aggregate_trades else 0.0,
        "trade_cost_pct": trade_cost_pct,
        "threshold_grid": list(thresholds),
        "threshold_selection": "train_calibration_net_return",
        "threshold_calibration_rows": threshold_calibration_rows,
        "min_train_trades": min_train_trades,
        "actual_label_counts": dict(aggregate_actual),
        "predicted_label_counts": dict(aggregate_predicted),
        "prediction_direction_stats": _finalize_prediction_direction_stats(aggregate_prediction_direction),
        "train_rows": train_rows,
        "test_rows": test_rows,
        "gap_rows": gap_rows,
        "step_rows": step_rows,
        "max_folds": max_folds,
        "fold_summaries": fold_summaries,
        "trade_ledger": trade_ledger,
    }


def _cost_adjusted_metric_summary(metrics: dict[str, object], trade_cost_pct: float) -> dict[str, object]:
    trades_taken = int(metrics.get("trades_taken", 0))
    cumulative_gross = float(metrics.get("cumulative_gross_return_pct", 0.0))
    cumulative_net = cumulative_gross - (trades_taken * trade_cost_pct)
    return {
        "trades_taken": trades_taken,
        "trade_cost_pct": trade_cost_pct,
        "cumulative_gross_return_pct": cumulative_gross,
        "cumulative_net_return_pct": cumulative_net,
        "average_net_return_pct": (cumulative_net / trades_taken) if trades_taken else 0.0,
        "trade_hit_rate": float(metrics.get("trade_hit_rate", 0.0)),
        "win_rate": float(metrics.get("win_rate", 0.0)),
        "overall_accuracy": float(metrics.get("overall_accuracy", 0.0)),
    }


def _top_group_rows(rows: list[dict[str, object]], *, limit: int = 8) -> list[dict[str, object]]:
    return rows[:limit]


def _threshold_key(threshold_pct: float) -> str:
    return f"{threshold_pct:.6f}".rstrip("0").rstrip(".")


def _relabel_training_rows(rows: list[dict[str, object]], threshold_pct: float) -> list[dict[str, object]]:
    relabeled_rows: list[dict[str, object]] = []
    for row in rows:
        copied = dict(row)
        copied["label"] = classify_return(float(row["future_return_pct"]), threshold_pct)
        relabeled_rows.append(copied)
    return relabeled_rows


def _label_counts_for_rows(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts[str(row["label"])] += 1
    return dict(counts)


def _fixed_label_sensitivity_grid(current_threshold_pct: float) -> tuple[float, ...]:
    values = [*CYBOS_LABEL_SENSITIVITY_BASE_GRID, current_threshold_pct]
    return tuple(sorted({round(float(value), 6) for value in values}))


def _label_sensitivity_decision(results: list[dict[str, object]]) -> dict[str, str]:
    ok_results = [item for item in results if item.get("status") == "ok"]
    positive_results = [
        item
        for item in ok_results
        if float(item.get("cumulative_net_return_pct", 0.0)) > 0.0
    ]
    reliable_positive_results = [
        item
        for item in positive_results
        if int(item.get("trades_taken", 0)) >= 30
    ]
    if len(reliable_positive_results) >= 2:
        return {
            "status": "follow_up_candidate",
            "label": "후속 검증 후보",
            "conclusion": "여러 threshold에서 비용 반영 수익이 양수이고 trades >= 30이므로 후속 검증 후보로만 기록한다. 자동 채택은 하지 않는다.",
        }
    if positive_results:
        return {
            "status": "hold_overfit_risk",
            "label": "채택 보류, 과최적화 의심",
            "conclusion": "일부 threshold에서만 양수이거나 표본이 부족하므로 threshold를 채택하지 않고 과최적화 위험으로 보류한다.",
        }
    if ok_results and all(float(item.get("cumulative_net_return_pct", 0.0)) <= 0.0 for item in ok_results):
        return {
            "status": "alpha_insufficient",
            "label": "bar-only ML 알파 부족",
            "conclusion": "모든 threshold에서 비용 반영 수익이 음수이므로 현재 Cybos 15분 bar-only ML은 비용 초과 알파가 부족한 것으로 판단한다.",
        }
    return {
        "status": "inconclusive",
        "label": "판단 보류",
        "conclusion": "일부 threshold 평가가 실패해 라벨 민감도 결론을 확정하지 않는다.",
    }


def _label_reproducibility_decision(
    fold_design_results: list[dict[str, object]],
    period_results: list[dict[str, object]],
) -> dict[str, str]:
    checked_results = [
        item
        for item in [*fold_design_results, *period_results]
        if item.get("status") == "ok"
    ]
    reliable_results = [
        item
        for item in checked_results
        if int(item.get("trades_taken", 0)) >= 30
    ]
    reliable_positive = [
        item
        for item in reliable_results
        if float(item.get("cumulative_net_return_pct", 0.0)) > 0.0
    ]
    if reliable_results and len(reliable_positive) == len(reliable_results):
        return {
            "status": "follow_up_candidate",
            "label": "후속 검증 후보",
            "conclusion": "검증한 fold 설계와 기간 구간에서 모두 비용 반영 수익이 양수이므로 후속 검증 후보로 기록한다. 그래도 threshold 자동 채택은 하지 않는다.",
        }
    if reliable_positive:
        return {
            "status": "not_reproducible",
            "label": "재현성 부족",
            "conclusion": "일부 fold 설계 또는 기간에서만 양수이고 전체 재현성이 부족하다. threshold 0.20은 채택하지 않는다.",
        }
    return {
        "status": "alpha_insufficient",
        "label": "bar-only ML 알파 부족",
        "conclusion": "재현성 검증에서 비용 반영 양수가 안정적으로 나오지 않았다. 현재 Cybos 15분 bar-only ML 경로는 우선순위를 낮춘다.",
    }


def _optional_float_text(value: object, digits: int = 6) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _rule_strategy_specs() -> dict[str, dict[str, object]]:
    return {
        "opening_momentum": {
            "description": "장 초반 강한 양봉과 종가 위치를 보는 long-only momentum rule",
            "direction": "long_only",
        },
        "range_expansion": {
            "description": "큰 장중 범위와 상단 종가 마감을 보는 long-only breakout rule",
            "direction": "long_only",
        },
        "momentum_follow": {
            "description": "직전 봉과 현재 봉이 함께 양수인 단기 추세 지속 rule",
            "direction": "long_only",
        },
        "pullback_bounce": {
            "description": "직전 하락 뒤 현재 봉 반등과 종가 위치를 보는 long-only bounce rule",
            "direction": "long_only",
        },
        "quiet_breakout": {
            "description": "직전 좁은 변동 뒤 거래량 증가와 상방 돌파를 보는 long-only breakout rule",
            "direction": "long_only",
        },
    }


def _bar_value(row: dict[str, object], name: str, default: float = 0.0) -> float:
    values = row.get("values", {})
    if not isinstance(values, dict):
        return default
    try:
        return float(values.get(name, default))
    except (TypeError, ValueError):
        return default


def _rule_signal(row: dict[str, object], strategy_name: str) -> bool:
    ret = _bar_value(row, "return_1m_pct")
    prev_ret = _bar_value(row, "prev_return_pct")
    hl_range = _bar_value(row, "hl_range_pct")
    prev_range = _bar_value(row, "prev_hl_range_pct")
    close_position = _bar_value(row, "close_position_pct", 50.0)
    minute_slot = _bar_value(row, "minute_slot_pct")
    log_volume_delta = _bar_value(row, "log_volume_delta")

    if strategy_name == "opening_momentum":
        return minute_slot <= 0.25 and ret >= 0.12 and close_position >= 65.0 and log_volume_delta >= 0.0
    if strategy_name == "range_expansion":
        return hl_range >= 0.45 and ret >= 0.12 and close_position >= 70.0
    if strategy_name == "momentum_follow":
        return prev_ret >= 0.08 and ret >= 0.08 and close_position >= 60.0
    if strategy_name == "pullback_bounce":
        return prev_ret <= -0.20 and ret >= 0.08 and close_position >= 55.0
    if strategy_name == "quiet_breakout":
        return prev_range <= 0.20 and ret >= 0.10 and close_position >= 65.0 and log_volume_delta >= 0.25
    raise ValueError(f"Unsupported Cybos rule challenger strategy: {strategy_name}")


def _max_drawdown_pct(net_returns: list[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for net_return in net_returns:
        cumulative += net_return
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    return max_drawdown


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _longest_losing_streak(net_returns: list[float]) -> int:
    longest = 0
    current = 0
    for net_return in net_returns:
        if net_return <= 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _rule_metrics_from_ledger(
    *,
    strategy_name: str,
    rows_evaluated: int,
    trade_ledger: list[dict[str, object]],
    trade_cost_pct: float,
) -> dict[str, object]:
    trades = len(trade_ledger)
    hit_count = sum(1 for trade in trade_ledger if bool(trade["is_hit"]))
    win_count = sum(1 for trade in trade_ledger if bool(trade["is_win"]))
    gross_returns = [float(trade["gross_return_pct"]) for trade in trade_ledger]
    net_returns = [float(trade["net_return_pct"]) for trade in trade_ledger]
    positive_net = [value for value in net_returns if value > 0]
    negative_net = [value for value in net_returns if value <= 0]
    gross_sum = sum(gross_returns)
    net_sum = sum(net_returns)
    positive_sum = sum(positive_net)
    negative_sum = sum(negative_net)
    average_win = (positive_sum / len(positive_net)) if positive_net else 0.0
    average_loss = (negative_sum / len(negative_net)) if negative_net else 0.0
    daily_net: dict[str, float] = defaultdict(float)
    by_symbol: dict[str, dict[str, float]] = {}
    by_hour: dict[str, dict[str, float]] = {}
    for trade in trade_ledger:
        event_time = str(trade["event_time"])
        trade_date = event_time[:10] if len(event_time) >= 10 else "unknown"
        hour = event_time[11:13] if len(event_time) >= 13 else "unknown"
        daily_net[trade_date] += float(trade["net_return_pct"])
        for buckets, key in ((by_symbol, str(trade["symbol"])), (by_hour, hour)):
            _add_trade_group_stat(
                buckets,
                key,
                gross_return_pct=float(trade["gross_return_pct"]),
                net_return_pct=float(trade["net_return_pct"]),
                confidence=1.0,
                is_hit=bool(trade["is_hit"]),
                is_win=bool(trade["is_win"]),
            )

    daily_values = list(daily_net.values())
    return {
        "strategy_name": strategy_name,
        "rows_evaluated": rows_evaluated,
        "trades_taken": trades,
        "trade_hit_rate": (hit_count / trades) if trades else 0.0,
        "win_rate": (win_count / trades) if trades else 0.0,
        "average_gross_return_pct": (gross_sum / trades) if trades else 0.0,
        "average_net_return_pct": (net_sum / trades) if trades else 0.0,
        "average_win_net_return_pct": average_win,
        "average_loss_net_return_pct": average_loss,
        "payoff_ratio": (average_win / abs(average_loss)) if average_loss < 0 else None,
        "profit_factor": (positive_sum / abs(negative_sum)) if negative_sum < 0 else None,
        "cumulative_gross_return_pct": gross_sum,
        "cumulative_net_return_pct": net_sum,
        "max_drawdown_pct": _max_drawdown_pct(net_returns),
        "longest_losing_streak": _longest_losing_streak(net_returns),
        "trade_cost_pct": trade_cost_pct,
        "daily_return_stats": {
            "days_traded": len(daily_values),
            "positive_day_rate": (
                sum(1 for value in daily_values if value > 0) / len(daily_values)
                if daily_values
                else 0.0
            ),
            "average_daily_net_return_pct": (sum(daily_values) / len(daily_values)) if daily_values else 0.0,
            "median_daily_net_return_pct": _median(daily_values),
            "best_daily_net_return_pct": max(daily_values) if daily_values else 0.0,
            "worst_daily_net_return_pct": min(daily_values) if daily_values else 0.0,
        },
        "by_symbol": _finalize_trade_group_stats(by_symbol, sort_by_net=True),
        "by_hour": _finalize_trade_group_stats(by_hour),
    }


def _evaluate_rule_rows(
    *,
    rows: list[dict[str, object]],
    strategy_name: str,
    trade_cost_pct: float,
    fold_number: int | None = None,
) -> dict[str, object]:
    trade_ledger: list[dict[str, object]] = []
    for row_index, row in enumerate(rows, start=1):
        if not _rule_signal(row, strategy_name):
            continue
        future_return_pct = float(row["future_return_pct"])
        net_return_pct = future_return_pct - trade_cost_pct
        event_time = row["event_time"]
        actual_label = str(row["label"])
        trade_ledger.append(
            {
                "fold": fold_number,
                "row_index": row_index,
                "symbol": str(row["symbol"]),
                "event_time": event_time.isoformat() if isinstance(event_time, datetime) else str(event_time),
                "predicted_label": "up",
                "actual_label": actual_label,
                "gross_return_pct": future_return_pct,
                "trade_cost_pct": trade_cost_pct,
                "net_return_pct": net_return_pct,
                "is_hit": actual_label == "up",
                "is_win": net_return_pct > 0,
            }
        )
    metrics = _rule_metrics_from_ledger(
        strategy_name=strategy_name,
        rows_evaluated=len(rows),
        trade_ledger=trade_ledger,
        trade_cost_pct=trade_cost_pct,
    )
    metrics["trade_ledger"] = trade_ledger
    return metrics


def _run_rule_walk_forward(
    *,
    rows: list[dict[str, object]],
    strategy_names: tuple[str, ...],
    train_rows: int,
    test_rows: int,
    gap_rows: int,
    step_rows: int,
    max_folds: int,
    trade_cost_pct: float,
) -> dict[str, object]:
    if len(rows) < train_rows + gap_rows + test_rows:
        raise ValueError("Not enough rows for Cybos rule challenger walk-forward evaluation.")
    train_end_values = list(range(train_rows, len(rows) - gap_rows - test_rows + 1, step_rows))
    if max_folds > 0 and len(train_end_values) > max_folds:
        selected_indices = np.linspace(0, len(train_end_values) - 1, max_folds, dtype=int)
        train_end_values = [train_end_values[int(index)] for index in selected_indices]

    strategy_ledgers: dict[str, list[dict[str, object]]] = {name: [] for name in strategy_names}
    strategy_rows_evaluated: dict[str, int] = {name: 0 for name in strategy_names}
    fold_summaries: dict[str, list[dict[str, object]]] = {name: [] for name in strategy_names}

    for fold_number, train_end in enumerate(train_end_values, start=1):
        test_start = train_end + gap_rows
        fold_test = rows[test_start : test_start + test_rows]
        if not fold_test:
            continue
        for strategy_name in strategy_names:
            metrics = _evaluate_rule_rows(
                rows=fold_test,
                strategy_name=strategy_name,
                trade_cost_pct=trade_cost_pct,
                fold_number=fold_number,
            )
            strategy_rows_evaluated[strategy_name] += len(fold_test)
            strategy_ledgers[strategy_name].extend(list(metrics["trade_ledger"]))
            fold_summaries[strategy_name].append(
                {
                    "fold": fold_number,
                    "train_start_row": max(0, train_end - train_rows),
                    "train_end_row": train_end - 1,
                    "test_start_row": test_start,
                    "test_end_row": test_start + len(fold_test) - 1,
                    "test_start_event_time": fold_test[0]["event_time"].isoformat(),
                    "test_end_event_time": fold_test[-1]["event_time"].isoformat(),
                    "trades_taken": int(metrics["trades_taken"]),
                    "trade_hit_rate": float(metrics["trade_hit_rate"]),
                    "cumulative_net_return_pct": float(metrics["cumulative_net_return_pct"]),
                }
            )

    strategy_results: list[dict[str, object]] = []
    for strategy_name in strategy_names:
        metrics = _rule_metrics_from_ledger(
            strategy_name=strategy_name,
            rows_evaluated=strategy_rows_evaluated[strategy_name],
            trade_ledger=strategy_ledgers[strategy_name],
            trade_cost_pct=trade_cost_pct,
        )
        metrics["fold_summaries"] = fold_summaries[strategy_name]
        metrics["trade_ledger_sample"] = strategy_ledgers[strategy_name][:50]
        strategy_results.append(metrics)

    return {
        "folds": len(train_end_values),
        "train_rows": train_rows,
        "test_rows": test_rows,
        "gap_rows": gap_rows,
        "step_rows": step_rows,
        "max_folds": max_folds,
        "trade_cost_pct": trade_cost_pct,
        "strategy_results": strategy_results,
    }


def _rule_challenger_decision(strategy_results: list[dict[str, object]], min_reliable_trades: int) -> dict[str, object]:
    reliable_positive = [
        row
        for row in strategy_results
        if int(row.get("trades_taken", 0)) >= min_reliable_trades
        and float(row.get("cumulative_net_return_pct", 0.0)) > 0.0
    ]
    if not reliable_positive:
        return {
            "label": "research_only_no_promotion",
            "conclusion": "고정 룰 challenger 중 비용 반영 양수와 최소 거래 수를 함께 만족한 후보가 없습니다.",
        }
    if len(reliable_positive) == 1:
        return {
            "label": "single_candidate_needs_reproducibility_check",
            "conclusion": "비용 반영 양수 후보가 하나뿐이므로 바로 채택하지 않고 기간 분리 재현성 검증으로 넘깁니다.",
        }
    return {
        "label": "follow_up_candidates",
        "conclusion": "복수의 고정 룰이 비용 반영 양수를 보여 후속 기간 분리 검증 후보로 기록합니다.",
    }


def run_cybos_bar_only_experiment_from_sqlite(
    *,
    project_root: Path,
    horizon_min: int = 15,
    train_max_rows: int = 2_000,
    walk_forward_test_rows: int = 2_000,
    walk_forward_step_rows: int = 10_000,
    walk_forward_gap_rows: int = 15,
    walk_forward_max_folds: int = 120,
    feature_set_name: str = "bar_only",
) -> dict[str, object]:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for Cybos bar-only experiment.")
    threshold = settings.strategy.label_threshold_15 if horizon_min == 15 else settings.strategy.label_threshold_60
    feature_names = _cybos_feature_set_names(feature_set_name)
    feature_slug = feature_set_name.replace("_", "-")
    experiment_name = f"cybos {feature_slug}"
    dataset_payload = _source_bar_train_validation_rows(
        sqlite_store=sqlite_store,
        source=CYBOS_HISTORICAL_SOURCE,
        horizon_min=horizon_min,
        threshold_pct=threshold,
        train_max_rows=train_max_rows,
        feature_set_name=feature_set_name,
    )
    train_rows = list(dataset_payload["train_rows"])
    validation_rows = list(dataset_payload["validation_rows"])
    model_version = f"lightgbm-cybos-{feature_slug}-h{horizon_min}-v1"
    model = _fit_lightgbm_model(
        train_rows=train_rows,
        feature_names=feature_names,
        feature_set_version=f"{settings.feature_set_version}-{feature_set_name}",
        horizon_min=horizon_min,
        model_version=model_version,
    )
    artifact_path = _write_lightgbm_artifact(runtime_root=settings.runtime_data_dir, model=model)
    validation_metrics = _evaluate_rows_with_model(
        rows=validation_rows,
        model=model,
        settings=settings,
        horizon_min=horizon_min,
        prediction_prefix=f"cybos-{feature_set_name}-validation",
    )
    walk_rows = sorted(train_rows + validation_rows, key=lambda item: (item["event_time"], str(item["symbol"])))
    walk_forward_metrics = _run_lightgbm_walk_forward(
        rows=walk_rows,
        feature_names=feature_names,
        settings=settings,
        horizon_min=horizon_min,
        train_rows=train_max_rows,
        test_rows=walk_forward_test_rows,
        gap_rows=walk_forward_gap_rows,
        step_rows=walk_forward_step_rows,
        max_folds=walk_forward_max_folds,
        feature_set_name=feature_set_name,
    )

    completed_at = now_local(settings.timezone)
    timestamp_token = completed_at.strftime("%Y%m%d%H%M%S%f")
    training_run_id = f"train-cybos-bar-only-h{horizon_min}-{timestamp_token}"
    eval_id = f"eval-cybos-bar-only-h{horizon_min}-{timestamp_token}"
    wf_eval_id = f"walk-cybos-bar-only-h{horizon_min}-{timestamp_token}"
    writer = _get_research_writer(settings)
    writer.write_training_run(
        TrainingRun(
            training_run_id=training_run_id,
            started_at=completed_at,
            completed_at=completed_at,
            model_version=model_version,
            feature_set_version=f"{settings.feature_set_version}-{feature_set_name}",
            horizon_min=horizon_min,
            train_rows=len(train_rows),
            validation_rows=len(validation_rows),
            training_summary={
                "experiment": experiment_name,
                "framework": "lightgbm",
                "class_weight": "balanced",
                "source": CYBOS_HISTORICAL_SOURCE,
                "feature_set_name": feature_set_name,
                "feature_names": feature_names,
                "label_counts": dataset_payload["label_counts"],
                "train_max_rows": train_max_rows,
                "validation_start_date": dataset_payload["validation_start_date"],
                "artifact_path": str(artifact_path),
                "activation_applied": False,
            },
        )
    )
    writer.write_model_evaluation(
        ModelEvaluation(
            evaluation_id=eval_id,
            training_run_id=training_run_id,
            evaluated_at=completed_at,
            split_name=f"cybos_{feature_set_name}_validation_h{horizon_min}",
            accuracy=float(validation_metrics["overall_accuracy"]),
            total_rows=int(validation_metrics["rows_evaluated"]),
            metrics=validation_metrics,
        )
    )
    writer.write_model_evaluation(
        ModelEvaluation(
            evaluation_id=wf_eval_id,
            training_run_id=training_run_id,
            evaluated_at=completed_at,
            split_name=f"cybos_{feature_set_name}_walk_forward_h{horizon_min}",
            accuracy=float(walk_forward_metrics["overall_accuracy"]),
            total_rows=int(walk_forward_metrics["rows_evaluated"]),
            metrics=walk_forward_metrics,
        )
    )

    report_dir = settings.runtime_data_dir / "reports" / "backtests"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = report_dir / f"latest-cybos-{feature_slug}-h{horizon_min}.json"
    report_md_path = report_dir / f"latest-cybos-{feature_slug}-h{horizon_min}.md"
    payload = {
        "experiment": experiment_name,
        "completed_at": completed_at.isoformat(),
        "source": CYBOS_HISTORICAL_SOURCE,
        "feature_set_name": feature_set_name,
        "horizon_min": horizon_min,
        "model_version": model_version,
        "training_run_id": training_run_id,
        "evaluation_id": eval_id,
        "walk_forward_evaluation_id": wf_eval_id,
        "artifact_path": str(artifact_path),
        "feature_names": feature_names,
        "feature_importance_top5": _lightgbm_feature_importance(model)[:5],
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
        "training": {
            "train_rows": len(train_rows),
            "validation_rows": len(validation_rows),
            "train_first_event_time": train_rows[0]["event_time"].isoformat(),
            "train_last_event_time": train_rows[-1]["event_time"].isoformat(),
            "validation_first_event_time": validation_rows[0]["event_time"].isoformat(),
            "validation_last_event_time": validation_rows[-1]["event_time"].isoformat(),
        },
        "validation": validation_metrics,
        "walk_forward": walk_forward_metrics,
    }
    report_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md_path.write_text(
        "\n".join(
            [
                f"# Cybos {feature_slug} H{horizon_min}",
                "",
                f"- source: `{CYBOS_HISTORICAL_SOURCE}`",
                f"- feature_set_name: `{feature_set_name}`",
                f"- feature_names: {', '.join(feature_names)}",
                f"- train_rows: {len(train_rows)}",
                f"- validation_rows: {len(validation_rows)}",
                f"- validation_accuracy: {float(validation_metrics['overall_accuracy']):.6f}",
                f"- validation_trades_taken: {int(validation_metrics['trades_taken'])}",
                f"- validation_trade_hit_rate: {float(validation_metrics['trade_hit_rate']):.6f}",
                f"- validation_cumulative_net_return_pct: {float(validation_metrics['cumulative_net_return_pct']):.6f}",
                f"- walk_forward_overall_accuracy: {float(walk_forward_metrics['overall_accuracy']):.6f}",
                f"- walk_forward_trades_taken: {int(walk_forward_metrics['trades_taken'])}",
                f"- walk_forward_trade_hit_rate: {float(walk_forward_metrics['trade_hit_rate']):.6f}",
                f"- walk_forward_cumulative_net_return_pct: {float(walk_forward_metrics['cumulative_net_return_pct']):.6f}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    payload["report_json_path"] = str(report_json_path)
    payload["report_markdown_path"] = str(report_md_path)
    return payload


def run_cybos_profitability_review_from_sqlite(
    *,
    project_root: Path,
    train_max_rows: int = 100_000,
    walk_forward_test_rows: int = 2_000,
    walk_forward_step_rows: int = 30_000,
    walk_forward_gap_rows: int = 15,
    walk_forward_max_folds: int = 50,
    trade_cost_pct: float = CYBOS_PROFITABILITY_COST_PCT,
    threshold_grid: tuple[float, ...] = CYBOS_CONFIDENCE_THRESHOLD_GRID,
    threshold_calibration_rows: int = 20_000,
    threshold_min_train_trades: int = 10,
) -> dict[str, object]:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for Cybos profitability review.")

    feature_set_name = "bar_only"
    feature_names = _cybos_feature_set_names(feature_set_name)
    default_trade_cost_pct = _estimate_trade_cost_pct(settings)
    default_signal_confidence = settings.strategy.min_signal_confidence

    h15_threshold = settings.strategy.label_threshold_15
    h15_dataset = _source_bar_train_validation_rows(
        sqlite_store=sqlite_store,
        source=CYBOS_HISTORICAL_SOURCE,
        horizon_min=15,
        threshold_pct=h15_threshold,
        train_max_rows=train_max_rows,
        feature_set_name=feature_set_name,
    )
    h15_rows = sorted(
        list(h15_dataset["train_rows"]) + list(h15_dataset["validation_rows"]),
        key=lambda item: (item["event_time"], str(item["symbol"])),
    )
    f5_cost_metrics = _run_lightgbm_walk_forward(
        rows=h15_rows,
        feature_names=feature_names,
        settings=settings,
        horizon_min=15,
        train_rows=train_max_rows,
        test_rows=walk_forward_test_rows,
        gap_rows=walk_forward_gap_rows,
        step_rows=walk_forward_step_rows,
        max_folds=walk_forward_max_folds,
        feature_set_name=feature_set_name,
        trade_cost_pct=trade_cost_pct,
        signal_confidence_threshold=default_signal_confidence,
        collect_trade_ledger=True,
        collect_prediction_stats=True,
    )
    trade_ledger = list(f5_cost_metrics.get("trade_ledger", []))
    f5_diagnosis = _summarize_trade_ledger(trade_ledger)
    f5_hypothesis = _build_profitability_hypothesis(f5_diagnosis)
    f5_default_cost_summary = _cost_adjusted_metric_summary(f5_cost_metrics, default_trade_cost_pct)
    f5_requested_cost_summary = _cost_adjusted_metric_summary(f5_cost_metrics, trade_cost_pct)

    threshold_metrics = _run_lightgbm_walk_forward_train_only_threshold(
        rows=h15_rows,
        feature_names=feature_names,
        settings=settings,
        horizon_min=15,
        train_rows=train_max_rows,
        test_rows=walk_forward_test_rows,
        gap_rows=walk_forward_gap_rows,
        step_rows=walk_forward_step_rows,
        max_folds=walk_forward_max_folds,
        feature_set_name=feature_set_name,
        trade_cost_pct=trade_cost_pct,
        threshold_grid=threshold_grid,
        threshold_calibration_rows=threshold_calibration_rows,
        min_train_trades=threshold_min_train_trades,
    )

    h60_threshold = settings.strategy.label_threshold_60
    h60_dataset = _source_bar_train_validation_rows(
        sqlite_store=sqlite_store,
        source=CYBOS_HISTORICAL_SOURCE,
        horizon_min=60,
        threshold_pct=h60_threshold,
        train_max_rows=train_max_rows,
        feature_set_name=feature_set_name,
    )
    h60_train_rows = list(h60_dataset["train_rows"])
    h60_validation_rows = list(h60_dataset["validation_rows"])
    h60_model = _fit_lightgbm_model(
        train_rows=h60_train_rows,
        feature_names=feature_names,
        feature_set_version=f"{settings.feature_set_version}-{feature_set_name}",
        horizon_min=60,
        model_version="lightgbm-cybos-bar-only-h60-v1",
    )
    h60_validation_metrics = _evaluate_rows_with_model(
        rows=h60_validation_rows,
        model=h60_model,
        settings=settings,
        horizon_min=60,
        prediction_prefix="cybos-bar-only-h60-validation",
        trade_cost_pct_override=trade_cost_pct,
        min_signal_confidence_override=default_signal_confidence,
        collect_prediction_stats=True,
    )
    h60_rows = sorted(
        h60_train_rows + h60_validation_rows,
        key=lambda item: (item["event_time"], str(item["symbol"])),
    )
    h60_walk_forward_metrics = _run_lightgbm_walk_forward(
        rows=h60_rows,
        feature_names=feature_names,
        settings=settings,
        horizon_min=60,
        train_rows=train_max_rows,
        test_rows=walk_forward_test_rows,
        gap_rows=walk_forward_gap_rows,
        step_rows=walk_forward_step_rows,
        max_folds=walk_forward_max_folds,
        feature_set_name=feature_set_name,
        trade_cost_pct=trade_cost_pct,
        signal_confidence_threshold=default_signal_confidence,
        collect_trade_ledger=True,
        collect_prediction_stats=True,
    )

    completed_at = now_local(settings.timezone)
    report_dir = settings.runtime_data_dir / "reports" / "backtests"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = report_dir / "latest-cybos-profitability-review.json"
    report_md_path = report_dir / "latest-cybos-profitability-review.md"
    payload = {
        "review": "cybos_profitability_review",
        "completed_at": completed_at.isoformat(),
        "source": CYBOS_HISTORICAL_SOURCE,
        "feature_set_name": feature_set_name,
        "feature_names": feature_names,
        "settings": {
            "train_max_rows": train_max_rows,
            "walk_forward_test_rows": walk_forward_test_rows,
            "walk_forward_step_rows": walk_forward_step_rows,
            "walk_forward_gap_rows": walk_forward_gap_rows,
            "walk_forward_max_folds": walk_forward_max_folds,
            "default_trade_cost_pct": default_trade_cost_pct,
            "requested_trade_cost_pct": trade_cost_pct,
            "default_signal_confidence": default_signal_confidence,
            "threshold_grid": list(threshold_grid),
        },
        "stage_1_f5_diagnosis": {
            "dataset": {
                "symbols": len(h15_dataset["symbols"]),
                "trade_dates": len(h15_dataset["trade_dates"]),
                "labeled_rows": h15_dataset["labeled_rows"],
                "label_counts": h15_dataset["label_counts"],
                "validation_start_date": h15_dataset["validation_start_date"],
            },
            "walk_forward": f5_cost_metrics,
            "trade_diagnosis": f5_diagnosis,
            "prediction_direction_stats": f5_cost_metrics.get("prediction_direction_stats", {}),
            "hypothesis": f5_hypothesis,
        },
        "stage_2_cost_baseline": {
            "cost_basis": "commission 0.015% one-way plus slippage 0.05% one-way; tax excluded",
            "default_cost_summary": f5_default_cost_summary,
            "requested_cost_summary": f5_requested_cost_summary,
        },
        "stage_3_train_only_confidence_threshold": threshold_metrics,
        "stage_4_h60_bar_only": {
            "dataset": {
                "symbols": len(h60_dataset["symbols"]),
                "trade_dates": len(h60_dataset["trade_dates"]),
                "labeled_rows": h60_dataset["labeled_rows"],
                "label_counts": h60_dataset["label_counts"],
                "validation_start_date": h60_dataset["validation_start_date"],
            },
            "validation": h60_validation_metrics,
            "walk_forward": h60_walk_forward_metrics,
            "feature_importance_top5": _lightgbm_feature_importance(h60_model)[:5],
        },
    }
    report_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_lines = [
        "# Cybos Profitability Review",
        "",
        "## Stage 1. F-5 Diagnosis",
        "",
        f"- trades: `{int(f5_cost_metrics['trades_taken'])}`",
        f"- trade_hit_rate: `{float(f5_cost_metrics['trade_hit_rate']):.6f}`",
        f"- net_return_cost_0_13_pct: `{float(f5_requested_cost_summary['cumulative_net_return_pct']):.6f}`",
        f"- hypothesis: {f5_hypothesis}",
        "",
        "### Worst Symbol Buckets",
        "",
        "| symbol | trades | hit_rate | net_pct |",
        "|---|---:|---:|---:|",
    ]
    for row in _top_group_rows(f5_diagnosis["by_symbol"]):
        markdown_lines.append(
            f"| `{row['key']}` | {row['trades']} | {float(row['hit_rate']):.3f} | "
            f"{float(row['cumulative_net_return_pct']):.6f} |"
        )
    markdown_lines.extend(
        [
            "",
            "### Hour Buckets",
            "",
            "| hour | trades | hit_rate | net_pct |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in f5_diagnosis["by_hour"]:
        markdown_lines.append(
            f"| `{row['key']}` | {row['trades']} | {float(row['hit_rate']):.3f} | "
            f"{float(row['cumulative_net_return_pct']):.6f} |"
        )
    markdown_lines.extend(
        [
            "",
            "## Stage 2. Cost Baseline",
            "",
            f"- default_cost_pct: `{default_trade_cost_pct:.6f}`",
            f"- requested_cost_pct: `{trade_cost_pct:.6f}`",
            f"- default_cost_net_pct: `{float(f5_default_cost_summary['cumulative_net_return_pct']):.6f}`",
            f"- requested_cost_net_pct: `{float(f5_requested_cost_summary['cumulative_net_return_pct']):.6f}`",
            "",
            "## Stage 3. Train-Only Confidence Threshold",
            "",
            f"- trades: `{int(threshold_metrics['trades_taken'])}`",
            f"- trade_hit_rate: `{float(threshold_metrics['trade_hit_rate']):.6f}`",
            f"- cost_adjusted_net_pct: `{float(threshold_metrics['cumulative_net_return_pct']):.6f}`",
            "",
            "## Stage 4. H60 Bar-Only",
            "",
            f"- validation_accuracy: `{float(h60_validation_metrics['overall_accuracy']):.6f}`",
            f"- walk_forward_accuracy: `{float(h60_walk_forward_metrics['overall_accuracy']):.6f}`",
            f"- walk_forward_trades: `{int(h60_walk_forward_metrics['trades_taken'])}`",
            f"- walk_forward_trade_hit_rate: `{float(h60_walk_forward_metrics['trade_hit_rate']):.6f}`",
            f"- walk_forward_cost_adjusted_net_pct: `{float(h60_walk_forward_metrics['cumulative_net_return_pct']):.6f}`",
        ]
    )
    report_md_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    payload["report_json_path"] = str(report_json_path)
    payload["report_markdown_path"] = str(report_md_path)
    return payload


def run_cybos_label_sensitivity_review_from_sqlite(
    *,
    project_root: Path,
    train_max_rows: int = 100_000,
    walk_forward_test_rows: int = 2_000,
    walk_forward_step_rows: int = 30_000,
    walk_forward_gap_rows: int = 15,
    walk_forward_max_folds: int = 50,
    trade_cost_pct: float = CYBOS_PROFITABILITY_COST_PCT,
    min_reliable_trades: int = 30,
) -> dict[str, object]:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for Cybos label sensitivity review.")

    feature_set_name = "bar_only"
    feature_names = _cybos_feature_set_names(feature_set_name)
    current_threshold = float(settings.strategy.label_threshold_15)
    threshold_grid = _fixed_label_sensitivity_grid(current_threshold)
    dataset_payload = _source_bar_train_validation_rows(
        sqlite_store=sqlite_store,
        source=CYBOS_HISTORICAL_SOURCE,
        horizon_min=15,
        threshold_pct=current_threshold,
        train_max_rows=train_max_rows,
        feature_set_name=feature_set_name,
        label_sensitivity_thresholds=threshold_grid,
    )
    base_rows = sorted(
        list(dataset_payload["train_rows"]) + list(dataset_payload["validation_rows"]),
        key=lambda item: (item["event_time"], str(item["symbol"])),
    )
    threshold_results: list[dict[str, object]] = []
    for threshold in threshold_grid:
        relabeled_rows = _relabel_training_rows(base_rows, threshold)
        selected_label_counts = _label_counts_for_rows(relabeled_rows)
        total_label_counts = dict(dataset_payload["label_sensitivity_counts"].get(_threshold_key(threshold), {}))
        result: dict[str, object] = {
            "threshold_pct": threshold,
            "is_current_setting": math.isclose(threshold, current_threshold, rel_tol=0.0, abs_tol=1e-9),
            "cost_relationship": "above_cost" if threshold > trade_cost_pct else "at_or_below_cost",
            "total_label_counts": total_label_counts,
            "selected_label_counts": selected_label_counts,
            "up_label_count": int(total_label_counts.get("up", 0)),
            "down_label_count": int(total_label_counts.get("down", 0)),
        }
        try:
            metrics = _run_lightgbm_walk_forward(
                rows=relabeled_rows,
                feature_names=feature_names,
                settings=settings,
                horizon_min=15,
                train_rows=train_max_rows,
                test_rows=walk_forward_test_rows,
                gap_rows=walk_forward_gap_rows,
                step_rows=walk_forward_step_rows,
                max_folds=walk_forward_max_folds,
                feature_set_name=feature_set_name,
                trade_cost_pct=trade_cost_pct,
                signal_confidence_threshold=settings.strategy.min_signal_confidence,
                collect_trade_ledger=False,
                collect_prediction_stats=False,
            )
        except ValueError as exc:
            result.update(
                {
                    "status": "failed",
                    "error": str(exc),
                    "reliability": "평가 실패",
                }
            )
            threshold_results.append(result)
            continue
        trades_taken = int(metrics["trades_taken"])
        result.update(
            {
                "status": "ok",
                "folds": int(metrics["folds"]),
                "rows_evaluated": int(metrics["rows_evaluated"]),
                "trades_taken": trades_taken,
                "overall_accuracy": float(metrics["overall_accuracy"]),
                "trade_hit_rate": float(metrics["trade_hit_rate"]),
                "win_rate": float(metrics["win_rate"]),
                "cumulative_gross_return_pct": float(metrics["cumulative_gross_return_pct"]),
                "cumulative_net_return_pct": float(metrics["cumulative_net_return_pct"]),
                "average_net_return_pct": float(metrics["average_net_return_pct"]),
                "reliability": "신뢰 낮음" if trades_taken < min_reliable_trades else "기록 가능",
                "fold_summaries": metrics["fold_summaries"],
            }
        )
        threshold_results.append(result)

    decision = _label_sensitivity_decision(threshold_results)
    completed_at = now_local(settings.timezone)
    report_dir = settings.runtime_data_dir / "reports" / "backtests"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = report_dir / "latest-cybos-label-sensitivity-review.json"
    report_md_path = report_dir / "latest-cybos-label-sensitivity-review.md"
    payload = {
        "review": "cybos_label_sensitivity_review",
        "completed_at": completed_at.isoformat(),
        "source": CYBOS_HISTORICAL_SOURCE,
        "feature_set_name": feature_set_name,
        "feature_names": feature_names,
        "settings": {
            "current_label_threshold_15": current_threshold,
            "trade_cost_pct": trade_cost_pct,
            "current_threshold_vs_cost": "higher" if current_threshold > trade_cost_pct else "not_higher",
            "threshold_grid": list(threshold_grid),
            "train_max_rows": train_max_rows,
            "walk_forward_test_rows": walk_forward_test_rows,
            "walk_forward_step_rows": walk_forward_step_rows,
            "walk_forward_gap_rows": walk_forward_gap_rows,
            "walk_forward_max_folds": walk_forward_max_folds,
            "min_signal_confidence": settings.strategy.min_signal_confidence,
            "min_reliable_trades": min_reliable_trades,
            "selection_policy": "diagnostic_only_no_threshold_adoption",
        },
        "dataset": {
            "symbols": len(dataset_payload["symbols"]),
            "trade_dates": len(dataset_payload["trade_dates"]),
            "source_rows": dataset_payload["source_rows"],
            "labeled_rows": dataset_payload["labeled_rows"],
            "first_event_time": dataset_payload["first_event_time"],
            "last_event_time": dataset_payload["last_event_time"],
            "validation_start_date": dataset_payload["validation_start_date"],
        },
        "threshold_results": threshold_results,
        "decision": decision,
    }
    report_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_lines = [
        "# Cybos Label Sensitivity Review",
        "",
        f"- source: `{CYBOS_HISTORICAL_SOURCE}`",
        f"- feature_set_name: `{feature_set_name}`",
        f"- current_label_threshold_15: `{current_threshold:.6f}`",
        f"- round_trip_cost_pct: `{trade_cost_pct:.6f}`",
        f"- current_threshold_vs_cost: `{payload['settings']['current_threshold_vs_cost']}`",
        f"- threshold_grid: `{', '.join(_threshold_key(item) for item in threshold_grid)}`",
        f"- policy: `{payload['settings']['selection_policy']}`",
        "",
        "| threshold | current | up labels | down labels | trades | hit_rate | net_pct | reliability |",
        "|---:|:---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in threshold_results:
        if row.get("status") != "ok":
            markdown_lines.append(
                f"| {float(row['threshold_pct']):.2f} | "
                f"{'yes' if row['is_current_setting'] else ''} | "
                f"{int(row.get('up_label_count', 0))} | {int(row.get('down_label_count', 0))} | "
                f"0 | 0.000000 | 0.000000 | {row.get('reliability', 'failed')} |"
            )
            continue
        markdown_lines.append(
            f"| {float(row['threshold_pct']):.2f} | "
            f"{'yes' if row['is_current_setting'] else ''} | "
            f"{int(row['up_label_count'])} | {int(row['down_label_count'])} | "
            f"{int(row['trades_taken'])} | {float(row['trade_hit_rate']):.6f} | "
            f"{float(row['cumulative_net_return_pct']):.6f} | {row['reliability']} |"
        )
    markdown_lines.extend(
        [
            "",
            f"- decision: `{decision['label']}`",
            f"- conclusion: {decision['conclusion']}",
            "",
            "Note: This review is diagnostic only. No label threshold is promoted automatically.",
        ]
    )
    report_md_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    payload["report_json_path"] = str(report_json_path)
    payload["report_markdown_path"] = str(report_md_path)
    return payload


def run_cybos_label_reproducibility_review_from_sqlite(
    *,
    project_root: Path,
    target_threshold_pct: float = CYBOS_LABEL_REPRODUCIBILITY_THRESHOLD,
    train_max_rows: int = 100_000,
    trade_cost_pct: float = CYBOS_PROFITABILITY_COST_PCT,
    min_reliable_trades: int = 30,
) -> dict[str, object]:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for Cybos label reproducibility review.")

    feature_set_name = "bar_only"
    feature_names = _cybos_feature_set_names(feature_set_name)
    fold_designs = [
        {
            "name": "f6_baseline",
            "train_rows": train_max_rows,
            "test_rows": 2_000,
            "step_rows": 30_000,
            "gap_rows": 15,
            "max_folds": 50,
        },
        {
            "name": "denser_step",
            "train_rows": train_max_rows,
            "test_rows": 2_000,
            "step_rows": 15_000,
            "gap_rows": 15,
            "max_folds": 50,
        },
        {
            "name": "shorter_train",
            "train_rows": 50_000,
            "test_rows": 2_000,
            "step_rows": 30_000,
            "gap_rows": 15,
            "max_folds": 50,
        },
    ]
    dataset_payload = _source_bar_train_validation_rows(
        sqlite_store=sqlite_store,
        source=CYBOS_HISTORICAL_SOURCE,
        horizon_min=15,
        threshold_pct=target_threshold_pct,
        train_max_rows=train_max_rows,
        feature_set_name=feature_set_name,
    )
    base_rows = sorted(
        list(dataset_payload["train_rows"]) + list(dataset_payload["validation_rows"]),
        key=lambda item: (item["event_time"], str(item["symbol"])),
    )
    fold_design_results: list[dict[str, object]] = []
    baseline_trade_diagnosis: dict[str, object] | None = None
    for design in fold_designs:
        result: dict[str, object] = {
            "name": design["name"],
            "train_rows": design["train_rows"],
            "test_rows": design["test_rows"],
            "step_rows": design["step_rows"],
            "gap_rows": design["gap_rows"],
            "max_folds": design["max_folds"],
        }
        collect_trade_ledger = design["name"] == "f6_baseline"
        try:
            metrics = _run_lightgbm_walk_forward(
                rows=base_rows,
                feature_names=feature_names,
                settings=settings,
                horizon_min=15,
                train_rows=int(design["train_rows"]),
                test_rows=int(design["test_rows"]),
                gap_rows=int(design["gap_rows"]),
                step_rows=int(design["step_rows"]),
                max_folds=int(design["max_folds"]),
                feature_set_name=feature_set_name,
                trade_cost_pct=trade_cost_pct,
                signal_confidence_threshold=settings.strategy.min_signal_confidence,
                collect_trade_ledger=collect_trade_ledger,
                collect_prediction_stats=False,
            )
        except ValueError as exc:
            result.update({"status": "failed", "error": str(exc), "reliability": "평가 실패"})
            fold_design_results.append(result)
            continue
        if collect_trade_ledger:
            baseline_trade_diagnosis = _summarize_trade_ledger(list(metrics.get("trade_ledger", [])))
        trades_taken = int(metrics["trades_taken"])
        result.update(
            {
                "status": "ok",
                "folds": int(metrics["folds"]),
                "rows_evaluated": int(metrics["rows_evaluated"]),
                "trades_taken": trades_taken,
                "overall_accuracy": float(metrics["overall_accuracy"]),
                "trade_hit_rate": float(metrics["trade_hit_rate"]),
                "win_rate": float(metrics["win_rate"]),
                "cumulative_gross_return_pct": float(metrics["cumulative_gross_return_pct"]),
                "cumulative_net_return_pct": float(metrics["cumulative_net_return_pct"]),
                "average_net_return_pct": float(metrics["average_net_return_pct"]),
                "reliability": "신뢰 낮음" if trades_taken < min_reliable_trades else "기록 가능",
            }
        )
        fold_design_results.append(result)

    period_specs = [
        {
            "name": "early_2021_2023_sample",
            "start_date": "2021-03-30",
            "end_date": "2023-12-31",
            "max_rows": 250_000,
        },
        {
            "name": "recent_2024_2026_sample",
            "start_date": "2024-01-01",
            "end_date": "2026-05-04",
            "max_rows": 250_000,
        },
    ]
    period_rows = _source_bar_period_rows(
        sqlite_store=sqlite_store,
        source=CYBOS_HISTORICAL_SOURCE,
        horizon_min=15,
        threshold_pct=target_threshold_pct,
        feature_set_name=feature_set_name,
        periods=period_specs,
    )
    period_results: list[dict[str, object]] = []
    for period_name, period_payload in period_rows.items():
        rows = list(period_payload["rows"])
        result = {
            "name": period_name,
            "start_date": period_payload["start_date"],
            "end_date": period_payload["end_date"],
            "source_rows": period_payload["source_rows"],
            "labeled_rows": period_payload["labeled_rows"],
            "selected_rows": period_payload["selected_rows"],
            "label_counts": period_payload["label_counts"],
            "first_event_time": period_payload["first_event_time"],
            "last_event_time": period_payload["last_event_time"],
            "train_rows": 50_000,
            "test_rows": 2_000,
            "step_rows": 20_000,
            "gap_rows": 15,
            "max_folds": 25,
        }
        try:
            metrics = _run_lightgbm_walk_forward(
                rows=rows,
                feature_names=feature_names,
                settings=settings,
                horizon_min=15,
                train_rows=50_000,
                test_rows=2_000,
                gap_rows=15,
                step_rows=20_000,
                max_folds=25,
                feature_set_name=feature_set_name,
                trade_cost_pct=trade_cost_pct,
                signal_confidence_threshold=settings.strategy.min_signal_confidence,
                collect_trade_ledger=False,
                collect_prediction_stats=False,
            )
        except ValueError as exc:
            result.update({"status": "failed", "error": str(exc), "reliability": "평가 실패"})
            period_results.append(result)
            continue
        trades_taken = int(metrics["trades_taken"])
        result.update(
            {
                "status": "ok",
                "folds": int(metrics["folds"]),
                "rows_evaluated": int(metrics["rows_evaluated"]),
                "trades_taken": trades_taken,
                "overall_accuracy": float(metrics["overall_accuracy"]),
                "trade_hit_rate": float(metrics["trade_hit_rate"]),
                "win_rate": float(metrics["win_rate"]),
                "cumulative_gross_return_pct": float(metrics["cumulative_gross_return_pct"]),
                "cumulative_net_return_pct": float(metrics["cumulative_net_return_pct"]),
                "average_net_return_pct": float(metrics["average_net_return_pct"]),
                "reliability": "신뢰 낮음" if trades_taken < min_reliable_trades else "기록 가능",
            }
        )
        period_results.append(result)

    decision = _label_reproducibility_decision(fold_design_results, period_results)
    completed_at = now_local(settings.timezone)
    report_dir = settings.runtime_data_dir / "reports" / "backtests"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = report_dir / "latest-cybos-label-reproducibility-review.json"
    report_md_path = report_dir / "latest-cybos-label-reproducibility-review.md"
    payload = {
        "review": "cybos_label_reproducibility_review",
        "completed_at": completed_at.isoformat(),
        "source": CYBOS_HISTORICAL_SOURCE,
        "feature_set_name": feature_set_name,
        "feature_names": feature_names,
        "target_threshold_pct": target_threshold_pct,
        "trade_cost_pct": trade_cost_pct,
        "min_signal_confidence": settings.strategy.min_signal_confidence,
        "min_reliable_trades": min_reliable_trades,
        "selection_policy": "diagnostic_only_no_threshold_adoption",
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
        "fold_design_results": fold_design_results,
        "period_results": period_results,
        "baseline_trade_diagnosis": baseline_trade_diagnosis or {},
        "decision": decision,
    }
    report_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_lines = [
        "# Cybos Label Reproducibility Review",
        "",
        f"- target_threshold_pct: `{target_threshold_pct:.6f}`",
        f"- round_trip_cost_pct: `{trade_cost_pct:.6f}`",
        f"- policy: `{payload['selection_policy']}`",
        "",
        "## Fold Design Checks",
        "",
        "| design | folds | trades | hit_rate | net_pct | reliability |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in fold_design_results:
        markdown_lines.append(
            f"| `{row['name']}` | {int(row.get('folds', 0))} | {int(row.get('trades_taken', 0))} | "
            f"{float(row.get('trade_hit_rate', 0.0)):.6f} | "
            f"{float(row.get('cumulative_net_return_pct', 0.0)):.6f} | {row.get('reliability', '')} |"
        )
    markdown_lines.extend(
        [
            "",
            "## Period Checks",
            "",
            "| period | rows | folds | trades | hit_rate | net_pct | reliability |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in period_results:
        markdown_lines.append(
            f"| `{row['name']}` | {int(row.get('selected_rows', 0))} | {int(row.get('folds', 0))} | "
            f"{int(row.get('trades_taken', 0))} | {float(row.get('trade_hit_rate', 0.0)):.6f} | "
            f"{float(row.get('cumulative_net_return_pct', 0.0)):.6f} | {row.get('reliability', '')} |"
        )
    markdown_lines.extend(
        [
            "",
            f"- decision: `{decision['label']}`",
            f"- conclusion: {decision['conclusion']}",
            "",
            "Note: This review is diagnostic only. No label threshold is promoted automatically.",
        ]
    )
    report_md_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    payload["report_json_path"] = str(report_json_path)
    payload["report_markdown_path"] = str(report_md_path)
    return payload


def run_cybos_rule_challenger_review_from_sqlite(
    *,
    project_root: Path,
    train_max_rows: int = 100_000,
    walk_forward_test_rows: int = 2_000,
    walk_forward_step_rows: int = 30_000,
    walk_forward_gap_rows: int = 15,
    walk_forward_max_folds: int = 50,
    trade_cost_pct: float = CYBOS_PROFITABILITY_COST_PCT,
    min_reliable_trades: int = 30,
) -> dict[str, object]:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for Cybos rule challenger review.")

    feature_set_name = "bar_context_momentum"
    threshold = settings.strategy.label_threshold_15
    dataset_payload = _source_bar_train_validation_rows(
        sqlite_store=sqlite_store,
        source=CYBOS_HISTORICAL_SOURCE,
        horizon_min=15,
        threshold_pct=threshold,
        train_max_rows=train_max_rows,
        feature_set_name=feature_set_name,
    )
    rows = sorted(
        list(dataset_payload["train_rows"]) + list(dataset_payload["validation_rows"]),
        key=lambda item: (item["event_time"], str(item["symbol"])),
    )
    walk_forward = _run_rule_walk_forward(
        rows=rows,
        strategy_names=CYBOS_RULE_CHALLENGER_STRATEGIES,
        train_rows=train_max_rows,
        test_rows=walk_forward_test_rows,
        gap_rows=walk_forward_gap_rows,
        step_rows=walk_forward_step_rows,
        max_folds=walk_forward_max_folds,
        trade_cost_pct=trade_cost_pct,
    )
    strategy_results = list(walk_forward["strategy_results"])
    leaderboard = sorted(
        strategy_results,
        key=lambda row: (
            float(row.get("cumulative_net_return_pct", 0.0)),
            int(row.get("trades_taken", 0)),
            float(row.get("profit_factor") or 0.0),
        ),
        reverse=True,
    )
    for rank, row in enumerate(leaderboard, start=1):
        row["rank"] = rank
        row["reliability"] = "기록 가능" if int(row.get("trades_taken", 0)) >= min_reliable_trades else "신뢰 낮음"

    decision = _rule_challenger_decision(leaderboard, min_reliable_trades)
    completed_at = now_local(settings.timezone)
    report_dir = settings.runtime_data_dir / "reports" / "backtests"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = report_dir / "latest-cybos-rule-challengers-review.json"
    report_md_path = report_dir / "latest-cybos-rule-challengers-review.md"
    payload = {
        "review": "cybos_rule_challenger_review",
        "completed_at": completed_at.isoformat(),
        "source": CYBOS_HISTORICAL_SOURCE,
        "horizon_min": 15,
        "feature_set_name": feature_set_name,
        "feature_names": _cybos_feature_set_names(feature_set_name),
        "label_threshold_pct": threshold,
        "trade_cost_pct": trade_cost_pct,
        "min_reliable_trades": min_reliable_trades,
        "selection_policy": "research_only_no_auto_promotion",
        "strategy_specs": _rule_strategy_specs(),
        "settings": {
            "train_max_rows": train_max_rows,
            "walk_forward_test_rows": walk_forward_test_rows,
            "walk_forward_step_rows": walk_forward_step_rows,
            "walk_forward_gap_rows": walk_forward_gap_rows,
            "walk_forward_max_folds": walk_forward_max_folds,
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
            "selected_rows": len(rows),
        },
        "walk_forward": {
            key: value
            for key, value in walk_forward.items()
            if key != "strategy_results"
        },
        "leaderboard": leaderboard,
        "decision": decision,
    }
    report_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    markdown_lines = [
        "# Cybos Rule Challenger Review",
        "",
        f"- source: `{CYBOS_HISTORICAL_SOURCE}`",
        "- horizon_min: `15`",
        f"- feature_set_name: `{feature_set_name}`",
        f"- trade_cost_pct: `{trade_cost_pct:.6f}`",
        f"- selection_policy: `{payload['selection_policy']}`",
        "",
        "| rank | strategy | trades | hit_rate | win_rate | net_pct | profit_factor | max_dd | reliability |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in leaderboard:
        markdown_lines.append(
            f"| {int(row['rank'])} | `{row['strategy_name']}` | {int(row['trades_taken'])} | "
            f"{float(row['trade_hit_rate']):.6f} | {float(row['win_rate']):.6f} | "
            f"{float(row['cumulative_net_return_pct']):.6f} | {_optional_float_text(row.get('profit_factor'))} | "
            f"{float(row['max_drawdown_pct']):.6f} | {row['reliability']} |"
        )
    markdown_lines.extend(
        [
            "",
            f"- decision: `{decision['label']}`",
            f"- conclusion: {decision['conclusion']}",
            "",
            "Note: These are fixed research rules. The best historical row is not promoted automatically.",
        ]
    )
    report_md_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    payload["report_json_path"] = str(report_json_path)
    payload["report_markdown_path"] = str(report_md_path)
    return payload


def build_minute_bars_from_sqlite(project_root: Path) -> MinuteBarBuildResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for minute bar generation.")

    ticks = sqlite_store.fetch_market_ticks()
    grouped: dict[tuple[str, datetime], list[dict[str, object]]] = defaultdict(list)
    for row in ticks:
        event_time = _row_timestamp(row["event_time"])
        grouped[(row["symbol"], _minute_floor(event_time))].append(
            {
                "event_time": event_time,
                "price": float(row["price"]),
                "volume": int(row["volume"]),
            }
        )

    writer = _get_research_writer(settings)
    symbols_seen: set[str] = set()
    bars_written = 0
    for (symbol, minute), values in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        ordered = sorted(values, key=lambda item: item["event_time"])
        prices = [float(item["price"]) for item in ordered]
        volumes = [int(item["volume"]) for item in ordered]
        bar = MinuteBar(
            symbol=symbol,
            bar_time=minute,
            open=prices[0],
            high=max(prices),
            low=min(prices),
            close=prices[-1],
            volume=sum(volumes),
            trade_count=len(ordered),
        )
        writer.write_minute_bar(bar)
        bars_written += 1
        symbols_seen.add(symbol)

    return MinuteBarBuildResult(
        bars_written=bars_written,
        symbols_processed=sorted(symbols_seen),
        runtime_root=settings.runtime_data_dir,
    )


def build_feature_dataset_from_sqlite(
    project_root: Path,
    horizons: tuple[int, ...] = (15, 60),
    *,
    actual_only: bool = False,
    clear_existing: bool = False,
    persist_runtime_artifacts: bool = True,
) -> FeatureDatasetBuildResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for feature dataset generation.")

    if clear_existing:
        sqlite_store.clear_tables(["feature_model_inputs", "feature_labels"])

    if actual_only:
        scope = build_runtime_scope(sqlite_store, settings)
        minute_bar_rows = filter_actual_rows(
            "curated_minute_bars",
            [dict(row) for row in sqlite_store.fetch_minute_bars()],
            scope,
        )
        orderbook_rows = filter_actual_rows(
            "raw_orderbook_ticks",
            [dict(row) for row in sqlite_store.fetch_orderbook_snapshots()],
            scope,
        )
    else:
        minute_bar_rows = [dict(row) for row in sqlite_store.fetch_minute_bars()]
        orderbook_rows = [dict(row) for row in sqlite_store.fetch_orderbook_snapshots()]

    bars_by_symbol: dict[str, list[MinuteBar]] = defaultdict(list)
    for row in minute_bar_rows:
        bars_by_symbol[row["symbol"]].append(
            MinuteBar(
                symbol=row["symbol"],
                bar_time=_row_timestamp(row["bar_time"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                trade_count=int(row["trade_count"]),
            )
        )

    orderbooks_by_symbol: dict[str, dict[datetime, OrderbookSnapshot]] = defaultdict(dict)
    for row in orderbook_rows:
        event_time = _row_timestamp(row["event_time"])
        snapshot = OrderbookSnapshot(
            symbol=row["symbol"],
            event_time=event_time,
            bid_price=float(row["bid_price"]),
            ask_price=float(row["ask_price"]),
            bid_size=int(row["bid_size"]),
            ask_size=int(row["ask_size"]),
            source=row["source"],
        )
        orderbooks_by_symbol[row["symbol"]][_minute_floor(event_time)] = snapshot

    writer = _get_research_writer(settings) if persist_runtime_artifacts else None
    features_written = 0
    labels_written = 0
    feature_batch: list[FeatureSnapshot] = []
    label_batch: list[FeatureLabel] = []

    for symbol, bars in bars_by_symbol.items():
        bars.sort(key=lambda bar: bar.bar_time)
        bar_times = [bar.bar_time for bar in bars]
        latest_orderbook: OrderbookSnapshot | None = None
        for bar in bars:
            latest_orderbook = orderbooks_by_symbol[symbol].get(bar.bar_time, latest_orderbook)
            if latest_orderbook is None:
                continue
            feature_snapshot = build_feature_snapshot(bar, latest_orderbook, settings.feature_set_version)
            feature_batch.append(feature_snapshot)
            features_written += 1

            for horizon in horizons:
                target_time = bar.bar_time + timedelta(minutes=horizon)
                future_bar = _find_first_same_day_future_bar(bars, bar_times, target_time)
                if future_bar is None:
                    continue
                future_return_pct = ((future_bar.close - bar.close) / bar.close) * 100
                threshold = settings.strategy.label_threshold_15 if horizon == 15 else settings.strategy.label_threshold_60
                label = FeatureLabel(
                    symbol=symbol,
                    event_time=bar.bar_time,
                    horizon_min=horizon,
                    label=classify_return(future_return_pct, threshold),
                    threshold_pct=threshold,
                    future_return_pct=future_return_pct,
                )
                label_batch.append(label)
                labels_written += 1

    if writer is not None:
        writer.write_feature_snapshots_batch(feature_batch)
        writer.write_feature_labels_batch(label_batch)
    else:
        sqlite_store.upsert_feature_snapshots_many(feature_batch)
        sqlite_store.upsert_feature_labels_many(label_batch)

    return FeatureDatasetBuildResult(
        features_written=features_written,
        labels_written=labels_written,
        horizons=list(horizons),
        runtime_root=settings.runtime_data_dir,
    )


def _purge_runtime_paths(paths: list[Path]) -> list[str]:
    deleted: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            path.unlink()
            deleted.append(str(path))
            continue
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
                deleted.append(str(child))
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_dir():
                try:
                    child.rmdir()
                except OSError:
                    continue
    return deleted


def rebuild_actual_runtime_ml_state(project_root: Path, horizon_min: int = 15) -> ActualMlRebuildResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for actual ML rebuild.")

    cleanup_result = cleanup_non_actual_runtime_rows(project_root=project_root)

    table_counts = {
        "feature_model_inputs": sqlite_store.count_rows("feature_model_inputs"),
        "feature_labels": sqlite_store.count_rows("feature_labels"),
        "ml_training_runs": sqlite_store.count_rows("ml_training_runs"),
        "ml_model_evaluations": sqlite_store.count_rows("ml_model_evaluations"),
    }

    deleted_files = _purge_runtime_paths(
        [
            settings.runtime_data_dir / "reports" / "backtests",
            settings.runtime_data_dir / "reports" / "challengers",
            settings.runtime_data_dir / "ml" / "models",
        ]
    )
    sqlite_store.clear_tables(["feature_model_inputs", "feature_labels", "ml_training_runs", "ml_model_evaluations"])

    feature_result = build_feature_dataset_from_sqlite(
        project_root=project_root,
        horizons=(15, 60),
        actual_only=True,
        clear_existing=False,
        persist_runtime_artifacts=False,
    )
    active_result = set_builtin_model_active(
        project_root=project_root,
        horizon_min=horizon_min,
        builtin_name="baseline",
    )

    training_result: BaselineTrainingResult | None = None
    backtest_result: BacktestResult | None = None
    walk_forward_result: WalkForwardBacktestResult | None = None
    challenger_result: ChallengerRunResult | None = None
    errors: dict[str, str] = {}

    try:
        training_result = train_lightgbm_from_sqlite(
            project_root=project_root,
            horizon_min=horizon_min,
            set_active=False,
        )
    except ValueError as exc:
        errors["lightgbm_training"] = str(exc)

    try:
        backtest_result = run_signal_backtest_from_sqlite(project_root=project_root, horizon_min=horizon_min)
    except ValueError as exc:
        errors["backtest"] = str(exc)

    try:
        walk_forward_result = run_walk_forward_backtest_from_sqlite(
            project_root=project_root,
            horizon_min=horizon_min,
            min_train_rows=30,
            test_window_rows=10,
            step_rows=10,
            gap_rows=15,
            max_train_rows=40,
        )
    except ValueError as exc:
        errors["walk_forward"] = str(exc)

    try:
        challenger_result = run_model_challenger_review_from_sqlite(
            project_root=project_root,
            horizon_min=horizon_min,
            promote_best=False,
        )
    except ValueError as exc:
        errors["challenger"] = str(exc)

    return ActualMlRebuildResult(
        feature_build=feature_result.to_dict(),
        active_model=active_result.to_dict(),
        lightgbm_training=training_result.to_dict() if training_result else None,
        backtest=backtest_result.to_dict() if backtest_result else None,
        walk_forward=walk_forward_result.to_dict() if walk_forward_result else None,
        challenger=challenger_result.to_dict() if challenger_result else None,
        deleted_files=deleted_files,
        deleted_tables=table_counts,
        deleted_runtime_rows=cleanup_result.deleted_rows,
        errors=errors,
        runtime_root=settings.runtime_data_dir,
    )


def train_centroid_baseline_from_sqlite(
    project_root: Path,
    horizon_min: int = 15,
    set_active: bool = True,
) -> BaselineTrainingResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for training.")

    feature_names, dataset = _load_labeled_feature_dataset(sqlite_store, horizon_min=horizon_min)
    train_rows, validation_rows = _split_dataset(dataset, horizon_min=horizon_min)

    model_version = f"centroid-h{horizon_min}-v1"
    model = _fit_centroid_model(
        train_rows=train_rows,
        feature_names=feature_names,
        feature_set_version=settings.feature_set_version,
        horizon_min=horizon_min,
        model_version=model_version,
    )
    validation_metrics = _evaluate_rows_with_model(
        rows=validation_rows,
        model=model,
        settings=settings,
        horizon_min=horizon_min,
        prediction_prefix="train-validation",
    )
    accuracy = float(validation_metrics["overall_accuracy"])
    started_at = now_local(settings.timezone)
    completed_at = now_local(settings.timezone)
    timestamp_token = started_at.strftime("%Y%m%d%H%M%S%f")
    training_run_id = f"train-centroid-h{horizon_min}-{timestamp_token}"
    evaluation_id = f"eval-centroid-h{horizon_min}-{timestamp_token}"

    artifact_path = _write_centroid_artifact(runtime_root=settings.runtime_data_dir, model=model)
    if set_active:
        ModelRegistry(settings.runtime_data_dir).set_active_model(
            ModelRegistryEntry(
                horizon_min=horizon_min,
                model_version=model_version,
                artifact_path=str(artifact_path),
                feature_set_version=settings.feature_set_version,
                model_kind="centroid_artifact",
            )
        )

    writer = _get_research_writer(settings)
    writer.write_training_run(
        TrainingRun(
            training_run_id=training_run_id,
            started_at=started_at,
            completed_at=completed_at,
            model_version=model_version,
            feature_set_version=settings.feature_set_version,
            horizon_min=horizon_min,
            train_rows=len(train_rows),
            validation_rows=len(validation_rows),
            training_summary={
                "labels_seen": sorted({str(row["label"]) for row in dataset}),
                "feature_names": feature_names,
                "activation_applied": set_active,
            },
        )
    )
    writer.write_model_evaluation(
        ModelEvaluation(
            evaluation_id=evaluation_id,
            training_run_id=training_run_id,
            evaluated_at=completed_at,
            split_name="validation",
            accuracy=accuracy,
            total_rows=len(validation_rows),
            metrics={
                "correct": validation_metrics["overall_correct"],
                "predicted_label_counts": validation_metrics["predicted_label_counts"],
                "actual_label_counts": validation_metrics["actual_label_counts"],
                "trade_hit_rate": validation_metrics["trade_hit_rate"],
                "win_rate": validation_metrics["win_rate"],
                "activation_applied": set_active,
            },
        )
    )

    return BaselineTrainingResult(
        training_run_id=training_run_id,
        evaluation_id=evaluation_id,
        model_version=model_version,
        horizon_min=horizon_min,
        train_rows=len(train_rows),
        validation_rows=len(validation_rows),
        validation_accuracy=accuracy,
        artifact_path=artifact_path,
        activation_applied=set_active,
    )


def train_lightgbm_from_sqlite(
    project_root: Path,
    horizon_min: int = 15,
    set_active: bool = False,
) -> BaselineTrainingResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for training.")

    feature_names, dataset = _load_labeled_feature_dataset(sqlite_store, horizon_min=horizon_min)
    train_rows, validation_rows = _split_dataset(dataset, horizon_min=horizon_min)

    model_version = f"lightgbm-h{horizon_min}-v1"
    model = _fit_lightgbm_model(
        train_rows=train_rows,
        feature_names=feature_names,
        feature_set_version=settings.feature_set_version,
        horizon_min=horizon_min,
        model_version=model_version,
    )
    validation_metrics = _evaluate_rows_with_model(
        rows=validation_rows,
        model=model,
        settings=settings,
        horizon_min=horizon_min,
        prediction_prefix="train-lightgbm-validation",
    )
    accuracy = float(validation_metrics["overall_accuracy"])
    started_at = now_local(settings.timezone)
    completed_at = now_local(settings.timezone)
    timestamp_token = started_at.strftime("%Y%m%d%H%M%S%f")
    training_run_id = f"train-lightgbm-h{horizon_min}-{timestamp_token}"
    evaluation_id = f"eval-lightgbm-h{horizon_min}-{timestamp_token}"

    artifact_path = _write_lightgbm_artifact(runtime_root=settings.runtime_data_dir, model=model)
    if set_active:
        ModelRegistry(settings.runtime_data_dir).set_active_model(
            ModelRegistryEntry(
                horizon_min=horizon_min,
                model_version=model_version,
                artifact_path=str(artifact_path),
                feature_set_version=settings.feature_set_version,
                model_kind="lightgbm_artifact",
                metadata={
                    "framework": "lightgbm",
                    "class_labels": model.artifact.class_labels,
                },
            ),
        )

    writer = _get_research_writer(settings)
    writer.write_training_run(
        TrainingRun(
            training_run_id=training_run_id,
            started_at=started_at,
            completed_at=completed_at,
            model_version=model_version,
            feature_set_version=settings.feature_set_version,
            horizon_min=horizon_min,
            train_rows=len(train_rows),
            validation_rows=len(validation_rows),
            training_summary={
                "framework": "lightgbm",
                "class_weight": "balanced",
                "labels_seen": sorted({str(row["label"]) for row in dataset}),
                "label_counts": dict(Counter(str(row["label"]) for row in dataset)),
                "class_labels": model.artifact.class_labels,
                "feature_names": feature_names,
                "feature_selection": {
                    "proxy_source": PYKRX_DAILY_PROXY_SOURCE,
                    "proxy_excluded_features": sorted(PROXY_EXCLUDED_TRAINING_FEATURES),
                    "proxy_rows": sum(1 for row in dataset if row.get("feature_source") == PYKRX_DAILY_PROXY_SOURCE),
                    "source_counts": dict(Counter(str(row.get("feature_source", "unknown")) for row in dataset)),
                },
                "validation_split": _split_window_summary(train_rows, validation_rows),
                "validation_purge": {
                    "horizon_min": horizon_min,
                    "split": "trade_date_tail_20pct",
                    "purge_rule": "drop train rows where event_time + horizon reaches validation_start_time",
                },
                "training_window": "recent_60_trading_days_plus_today",
                "activation_applied": set_active,
            },
        )
    )
    writer.write_model_evaluation(
        ModelEvaluation(
            evaluation_id=evaluation_id,
            training_run_id=training_run_id,
            evaluated_at=completed_at,
            split_name="validation",
            accuracy=accuracy,
            total_rows=len(validation_rows),
            metrics={
                "framework": "lightgbm",
                "correct": validation_metrics["overall_correct"],
                "predicted_label_counts": validation_metrics["predicted_label_counts"],
                "actual_label_counts": validation_metrics["actual_label_counts"],
                "trade_hit_rate": validation_metrics["trade_hit_rate"],
                "win_rate": validation_metrics["win_rate"],
                "class_labels": model.artifact.class_labels,
                "activation_applied": set_active,
            },
        )
    )

    return BaselineTrainingResult(
        training_run_id=training_run_id,
        evaluation_id=evaluation_id,
        model_version=model_version,
        horizon_min=horizon_min,
        train_rows=len(train_rows),
        validation_rows=len(validation_rows),
        validation_accuracy=accuracy,
        artifact_path=artifact_path,
        activation_applied=set_active,
    )


def set_builtin_model_active(
    project_root: Path,
    horizon_min: int = 15,
    builtin_name: str = "baseline",
) -> ActiveModelSetResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    registry = ModelRegistry(settings.runtime_data_dir)
    model_version = _resolve_builtin_model_version(settings, horizon_min=horizon_min, builtin_name=builtin_name)
    registry.set_active_model(
        ModelRegistryEntry(
            horizon_min=horizon_min,
            model_version=model_version,
            artifact_path="",
            feature_set_version=settings.feature_set_version,
            model_kind="builtin",
            builtin_name=builtin_name,
        )
    )
    return ActiveModelSetResult(
        horizon_min=horizon_min,
        model_version=model_version,
        model_kind="builtin",
        builtin_name=builtin_name,
        artifact_path=None,
        registry_path=registry.registry_path,
    )


def run_signal_backtest_from_sqlite(project_root: Path, horizon_min: int = 15) -> BacktestResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for backtesting.")

    _, dataset = _load_labeled_feature_dataset(sqlite_store, horizon_min=horizon_min)
    _, validation_rows = _split_dataset(dataset, horizon_min=horizon_min)
    if not validation_rows:
        raise ValueError("Not enough validation rows are available for backtesting.")

    model = load_prediction_model(settings, horizon_min=horizon_min)
    evaluation_time = now_local(settings.timezone)
    evaluation_id = f"backtest-h{horizon_min}-{evaluation_time.strftime('%Y%m%d%H%M%S%f')}"
    metrics = _evaluate_rows_with_model(
        rows=validation_rows,
        model=model,
        settings=settings,
        horizon_min=horizon_min,
        prediction_prefix="backtest-pred",
    )
    rows_evaluated = int(metrics["rows_evaluated"])
    trades_taken = int(metrics["trades_taken"])
    overall_accuracy = float(metrics["overall_accuracy"])
    trade_hit_rate = float(metrics["trade_hit_rate"])
    win_rate = float(metrics["win_rate"])
    average_net_return_pct = float(metrics["average_net_return_pct"])
    average_gross_return_pct = float(metrics["average_gross_return_pct"])
    net_return_sum = float(metrics["cumulative_net_return_pct"])
    model_version = str(metrics["model_version"])
    training_run_id = _resolve_training_run_id(sqlite_store, model_version, horizon_min)

    evaluation_metrics = {
        "dataset_scope": "validation_tail_20pct",
        "model_version": model_version,
        "horizon_min": horizon_min,
        **metrics,
    }

    writer = _get_research_writer(settings)
    writer.write_model_evaluation(
        ModelEvaluation(
            evaluation_id=evaluation_id,
            training_run_id=training_run_id,
            evaluated_at=evaluation_time,
            split_name=f"backtest_validation_h{horizon_min}",
            accuracy=overall_accuracy,
            total_rows=rows_evaluated,
            metrics=evaluation_metrics,
        )
    )

    report_dir = settings.runtime_data_dir / "reports" / "backtests"
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = report_dir / f"latest-backtest-h{horizon_min}.md"
    json_path = report_dir / f"latest-backtest-h{horizon_min}.json"
    report_payload = {
        "evaluation_id": evaluation_id,
        "training_run_id": training_run_id,
        "evaluated_at": evaluation_time.isoformat(),
        **evaluation_metrics,
    }
    markdown_lines = [
        f"# Backtest H{horizon_min}",
        "",
        "## Summary",
        "",
        f"- `model_version`: {model_version}",
        f"- `dataset_scope`: validation_tail_20pct",
        f"- `rows_evaluated`: {rows_evaluated}",
        f"- `trades_taken`: {trades_taken}",
        f"- `overall_accuracy`: {overall_accuracy:.4f}",
        f"- `trade_hit_rate`: {trade_hit_rate:.4f}",
        f"- `win_rate`: {win_rate:.4f}",
        f"- `average_net_return_pct`: {average_net_return_pct:.4f}",
        f"- `cumulative_net_return_pct`: {net_return_sum:.4f}",
        f"- `trade_cost_pct`: {float(metrics['trade_cost_pct']):.4f}",
        "",
        "## Label Counts",
        "",
        f"- `actual`: {metrics['actual_label_counts']}",
        f"- `predicted`: {metrics['predicted_label_counts']}",
    ]
    markdown_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return BacktestResult(
        evaluation_id=evaluation_id,
        training_run_id=training_run_id,
        model_version=model_version,
        horizon_min=horizon_min,
        dataset_scope="validation_tail_20pct",
        rows_evaluated=rows_evaluated,
        trades_taken=trades_taken,
        overall_accuracy=overall_accuracy,
        trade_hit_rate=trade_hit_rate,
        win_rate=win_rate,
        average_net_return_pct=average_net_return_pct,
        cumulative_net_return_pct=net_return_sum,
        report_markdown_path=markdown_path,
        report_json_path=json_path,
    )


def run_walk_forward_backtest_from_sqlite(
    project_root: Path,
    horizon_min: int = 15,
    min_train_rows: int = 30,
    test_window_rows: int = 10,
    step_rows: int | None = None,
    gap_rows: int | None = None,
    max_train_rows: int | None = None,
) -> WalkForwardBacktestResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for walk-forward backtesting.")

    feature_names, dataset = _load_labeled_feature_dataset(sqlite_store, horizon_min=horizon_min)
    if step_rows is None:
        step_rows = test_window_rows
    if gap_rows is None:
        gap_rows = horizon_min
    if min_train_rows <= 0 or test_window_rows <= 0 or step_rows <= 0 or gap_rows < 0:
        raise ValueError("Walk-forward parameters must be positive integers.")
    if max_train_rows is not None and max_train_rows < min_train_rows:
        raise ValueError("max_train_rows must be greater than or equal to min_train_rows.")
    if len(dataset) < min_train_rows + gap_rows + test_window_rows:
        raise ValueError("Not enough labeled feature rows are available for walk-forward backtesting.")

    evaluation_time = now_local(settings.timezone)
    evaluation_id = f"walk-forward-h{horizon_min}-{evaluation_time.strftime('%Y%m%d%H%M%S%f')}"
    model_version = f"walk-forward-centroid-h{horizon_min}-v1"
    fold_summaries: list[dict[str, object]] = []
    aggregate_rows = 0
    aggregate_trades = 0
    aggregate_correct = 0
    aggregate_trade_hits = 0.0
    aggregate_wins = 0.0
    aggregate_confidence_weighted = 0.0
    aggregate_gross = 0.0
    aggregate_net = 0.0
    aggregate_actual: Counter[str] = Counter()
    aggregate_predicted: Counter[str] = Counter()

    fold_count = 0
    max_train_end = len(dataset) - gap_rows - test_window_rows
    for fold_index, train_end in enumerate(range(min_train_rows, max_train_end + 1, step_rows), start=1):
        train_start = 0
        if max_train_rows is not None:
            train_start = max(0, train_end - max_train_rows)
        train_rows = dataset[train_start:train_end]
        test_start = train_end + gap_rows
        test_rows = dataset[test_start : test_start + test_window_rows]
        if len(train_rows) < min_train_rows:
            continue
        if not test_rows:
            continue
        model = _fit_centroid_model(
            train_rows=train_rows,
            feature_names=feature_names,
            feature_set_version=settings.feature_set_version,
            horizon_min=horizon_min,
            model_version=model_version,
        )
        fold_metrics = _evaluate_rows_with_model(
            rows=test_rows,
            model=model,
            settings=settings,
            horizon_min=horizon_min,
            prediction_prefix=f"walk-forward-{fold_index}",
        )
        rows_evaluated = int(fold_metrics["rows_evaluated"])
        trades_taken = int(fold_metrics["trades_taken"])
        overall_accuracy = float(fold_metrics["overall_accuracy"])
        trade_hit_rate = float(fold_metrics["trade_hit_rate"])
        win_rate = float(fold_metrics["win_rate"])
        aggregate_rows += rows_evaluated
        aggregate_trades += trades_taken
        aggregate_correct += int(round(overall_accuracy * rows_evaluated))
        aggregate_trade_hits += trade_hit_rate * trades_taken
        aggregate_wins += win_rate * trades_taken
        aggregate_confidence_weighted += float(fold_metrics["average_confidence"]) * rows_evaluated
        aggregate_gross += float(fold_metrics["cumulative_gross_return_pct"])
        aggregate_net += float(fold_metrics["cumulative_net_return_pct"])
        aggregate_actual.update(fold_metrics["actual_label_counts"])
        aggregate_predicted.update(fold_metrics["predicted_label_counts"])
        fold_summaries.append(
            {
                "fold": fold_index,
                "train_start_row": train_start,
                "train_end_row": train_end - 1,
                "test_start_row": test_start,
                "test_end_row": (test_start + rows_evaluated - 1),
                "train_rows": len(train_rows),
                "test_rows": rows_evaluated,
                "gap_rows": gap_rows,
                "train_end_event_time": train_rows[-1]["event_time"].isoformat(),
                "test_start_event_time": test_rows[0]["event_time"].isoformat(),
                "test_end_event_time": test_rows[-1]["event_time"].isoformat(),
                "overall_accuracy": overall_accuracy,
                "trades_taken": trades_taken,
                "trade_hit_rate": trade_hit_rate,
                "win_rate": win_rate,
                "average_net_return_pct": float(fold_metrics["average_net_return_pct"]),
                "cumulative_net_return_pct": float(fold_metrics["cumulative_net_return_pct"]),
            }
        )
        fold_count += 1

    if fold_count == 0 or aggregate_rows == 0:
        raise ValueError("Walk-forward backtest did not produce any evaluation folds.")

    overall_accuracy = aggregate_correct / aggregate_rows
    trade_hit_rate = aggregate_trade_hits / aggregate_trades if aggregate_trades else 0.0
    win_rate = aggregate_wins / aggregate_trades if aggregate_trades else 0.0
    average_net_return_pct = aggregate_net / aggregate_trades if aggregate_trades else 0.0
    training_run_id = _resolve_training_run_id(sqlite_store, f"centroid-h{horizon_min}-v1", horizon_min)

    metrics = {
        "dataset_scope": "walk_forward_windowed_gap",
        "model_version": model_version,
        "horizon_min": horizon_min,
        "folds": fold_count,
        "rows_evaluated": aggregate_rows,
        "trades_taken": aggregate_trades,
        "overall_correct": aggregate_correct,
        "overall_accuracy": overall_accuracy,
        "trade_hit_rate": trade_hit_rate,
        "win_rate": win_rate,
        "average_confidence": (aggregate_confidence_weighted / aggregate_rows) if aggregate_rows else 0.0,
        "average_gross_return_pct": (aggregate_gross / aggregate_trades) if aggregate_trades else 0.0,
        "average_net_return_pct": average_net_return_pct,
        "cumulative_gross_return_pct": aggregate_gross,
        "cumulative_net_return_pct": aggregate_net,
        "trade_cost_pct": _estimate_trade_cost_pct(settings),
        "actual_label_counts": dict(aggregate_actual),
        "predicted_label_counts": dict(aggregate_predicted),
        "min_train_rows": min_train_rows,
        "test_window_rows": test_window_rows,
        "step_rows": step_rows,
        "gap_rows": gap_rows,
        "max_train_rows": max_train_rows,
        "fold_summaries": fold_summaries,
    }

    writer = _get_research_writer(settings)
    writer.write_model_evaluation(
        ModelEvaluation(
            evaluation_id=evaluation_id,
            training_run_id=training_run_id,
            evaluated_at=evaluation_time,
            split_name=f"walk_forward_h{horizon_min}",
            accuracy=overall_accuracy,
            total_rows=aggregate_rows,
            metrics=metrics,
        )
    )

    report_dir = settings.runtime_data_dir / "reports" / "backtests"
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = report_dir / f"latest-walk-forward-h{horizon_min}.md"
    json_path = report_dir / f"latest-walk-forward-h{horizon_min}.json"
    report_payload = {
        "evaluation_id": evaluation_id,
        "training_run_id": training_run_id,
        "evaluated_at": evaluation_time.isoformat(),
        **metrics,
    }
    markdown_lines = [
        f"# Walk-Forward Backtest H{horizon_min}",
        "",
        "## Summary",
        "",
        f"- `model_version`: {model_version}",
        f"- `folds`: {fold_count}",
        f"- `rows_evaluated`: {aggregate_rows}",
        f"- `trades_taken`: {aggregate_trades}",
        f"- `overall_accuracy`: {overall_accuracy:.4f}",
        f"- `trade_hit_rate`: {trade_hit_rate:.4f}",
        f"- `win_rate`: {win_rate:.4f}",
        f"- `average_net_return_pct`: {average_net_return_pct:.4f}",
        f"- `cumulative_net_return_pct`: {aggregate_net:.4f}",
        f"- `gap_rows`: {gap_rows}",
        f"- `max_train_rows`: {max_train_rows if max_train_rows is not None else 'full-history'}",
        "",
        "## Fold Summary",
        "",
    ]
    for fold in fold_summaries:
        markdown_lines.append(
            f"- `fold {fold['fold']}` train={fold['train_rows']} test={fold['test_rows']} "
            f"gap={fold['gap_rows']} accuracy={float(fold['overall_accuracy']):.4f} trades={fold['trades_taken']} "
            f"net={float(fold['cumulative_net_return_pct']):.4f}"
        )

    markdown_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return WalkForwardBacktestResult(
        evaluation_id=evaluation_id,
        training_run_id=training_run_id,
        model_version=model_version,
        horizon_min=horizon_min,
        folds=fold_count,
        rows_evaluated=aggregate_rows,
        trades_taken=aggregate_trades,
        overall_accuracy=overall_accuracy,
        trade_hit_rate=trade_hit_rate,
        win_rate=win_rate,
        average_net_return_pct=average_net_return_pct,
        cumulative_net_return_pct=aggregate_net,
        gap_rows=gap_rows,
        max_train_rows=max_train_rows,
        report_markdown_path=markdown_path,
        report_json_path=json_path,
    )


def run_model_challenger_review_from_sqlite(
    project_root: Path,
    horizon_min: int = 15,
    promote_best: bool = False,
) -> ChallengerRunResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = _get_research_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for challenger evaluation.")

    feature_names, dataset = _load_labeled_feature_dataset(sqlite_store, horizon_min=horizon_min)
    train_rows, validation_rows = _split_dataset(dataset, horizon_min=horizon_min)
    if not validation_rows:
        raise ValueError("Not enough validation rows are available for challenger evaluation.")

    review_time = now_local(settings.timezone)
    challenger_run_id = f"challenger-h{horizon_min}-{review_time.strftime('%Y%m%d%H%M%S%f')}"
    writer = _get_research_writer(settings)
    registry = ModelRegistry(settings.runtime_data_dir)

    candidates: list[dict[str, object]] = []
    active_model = load_prediction_model(settings, horizon_min=horizon_min)
    active_model_version = getattr(getattr(active_model, "artifact", None), "model_version", None)
    if active_model_version is None:
        prediction = active_model.predict(
            feature_snapshot=FeatureSnapshot(
                symbol=str(validation_rows[0]["symbol"]),
                event_time=validation_rows[0]["event_time"],
                feature_set_version=settings.feature_set_version,
                values=dict(validation_rows[0]["values"]),
            ),
            horizon_min=horizon_min,
            prediction_id="candidate-version-probe",
        )
        active_model_version = prediction.model_version
    active_metrics = _evaluate_rows_with_model(
        rows=validation_rows,
        model=active_model,
        settings=settings,
        horizon_min=horizon_min,
        prediction_prefix="challenger-active",
    )
    active_candidate = {
        "candidate_name": "active_model",
        "model_version": str(active_model_version),
        "model_kind": "active_runtime",
        "training_run_id": _resolve_training_run_id(sqlite_store, str(active_model_version), horizon_min),
        "promotable": False,
        "promotion_entry": None,
        **active_metrics,
    }
    candidates.append(active_candidate)

    baseline_model = BaselineDirectionModel(
        model_version_h15=settings.model_version_h15,
        model_version_h60=settings.model_version_h60,
    )
    baseline_metrics = _evaluate_rows_with_model(
        rows=validation_rows,
        model=baseline_model,
        settings=settings,
        horizon_min=horizon_min,
        prediction_prefix="challenger-baseline",
    )
    baseline_version = settings.model_version_h60 if horizon_min >= 60 else settings.model_version_h15
    candidates.append(
        {
            "candidate_name": "baseline_builtin",
            "model_version": baseline_version,
            "model_kind": "builtin",
            "training_run_id": f"builtin-{baseline_version}",
            "promotable": True,
            "promotion_entry": ModelRegistryEntry(
                horizon_min=horizon_min,
                model_version=baseline_version,
                artifact_path="",
                feature_set_version=settings.feature_set_version,
                model_kind="builtin",
                builtin_name="baseline",
            ),
            **baseline_metrics,
        }
    )

    linear_model = load_named_builtin_model(settings, horizon_min=horizon_min, builtin_name="linear_score")
    linear_metrics = _evaluate_rows_with_model(
        rows=validation_rows,
        model=linear_model,
        settings=settings,
        horizon_min=horizon_min,
        prediction_prefix="challenger-linear",
    )
    linear_version = linear_model.config.model_version
    candidates.append(
        {
            "candidate_name": "linear_score_builtin",
            "model_version": linear_version,
            "model_kind": "builtin",
            "training_run_id": f"builtin-{linear_version}",
            "promotable": True,
            "promotion_entry": ModelRegistryEntry(
                horizon_min=horizon_min,
                model_version=linear_version,
                artifact_path="",
                feature_set_version=settings.feature_set_version,
                model_kind="builtin",
                builtin_name="linear_score",
            ),
            **linear_metrics,
        }
    )

    latest_lightgbm_artifact = find_latest_lightgbm_artifact(settings.runtime_data_dir, horizon_min=horizon_min)
    if latest_lightgbm_artifact is not None:
        latest_lightgbm_model = LightGbmDirectionModel.from_path(latest_lightgbm_artifact)
        latest_lightgbm_version = latest_lightgbm_model.artifact.model_version
        if latest_lightgbm_version != str(active_candidate["model_version"]):
            lightgbm_metrics = _evaluate_rows_with_model(
                rows=validation_rows,
                model=latest_lightgbm_model,
                settings=settings,
                horizon_min=horizon_min,
                prediction_prefix="challenger-lightgbm",
            )
            candidates.append(
                {
                    "candidate_name": "latest_lightgbm",
                    "model_version": latest_lightgbm_version,
                    "model_kind": "lightgbm_artifact",
                    "training_run_id": _resolve_training_run_id(sqlite_store, latest_lightgbm_version, horizon_min),
                    "promotable": True,
                    "promotion_entry": ModelRegistryEntry(
                        horizon_min=horizon_min,
                        model_version=latest_lightgbm_version,
                        artifact_path=str(latest_lightgbm_artifact),
                        feature_set_version=settings.feature_set_version,
                        model_kind="lightgbm_artifact",
                        metadata={
                            "framework": "lightgbm",
                            "class_labels": latest_lightgbm_model.artifact.class_labels,
                        },
                    ),
                    **lightgbm_metrics,
                }
            )

    fresh_centroid_version = f"centroid-challenger-h{horizon_min}-v1"
    fresh_centroid_model = _fit_centroid_model(
        train_rows=train_rows,
        feature_names=feature_names,
        feature_set_version=settings.feature_set_version,
        horizon_min=horizon_min,
        model_version=fresh_centroid_version,
    )
    centroid_metrics = _evaluate_rows_with_model(
        rows=validation_rows,
        model=fresh_centroid_model,
        settings=settings,
        horizon_min=horizon_min,
        prediction_prefix="challenger-centroid",
    )
    centroid_artifact_path = _write_centroid_artifact(
        runtime_root=settings.runtime_data_dir,
        model=fresh_centroid_model,
    )
    candidates.append(
        {
            "candidate_name": "fresh_centroid",
            "model_version": fresh_centroid_version,
            "model_kind": "centroid_artifact",
            "training_run_id": _resolve_training_run_id(sqlite_store, f"centroid-h{horizon_min}-v1", horizon_min),
            "promotable": True,
            "promotion_entry": ModelRegistryEntry(
                horizon_min=horizon_min,
                model_version=fresh_centroid_version,
                artifact_path=str(centroid_artifact_path),
                feature_set_version=settings.feature_set_version,
                model_kind="centroid_artifact",
            ),
            **centroid_metrics,
        }
    )

    for candidate in candidates:
        split_name = f"challenger_validation_h{horizon_min}_{candidate['candidate_name']}"
        writer.write_model_evaluation(
            ModelEvaluation(
                evaluation_id=f"{challenger_run_id}-{candidate['candidate_name']}",
                training_run_id=str(candidate["training_run_id"]),
                evaluated_at=review_time,
                split_name=split_name,
                accuracy=float(candidate["overall_accuracy"]),
                total_rows=int(candidate["rows_evaluated"]),
                metrics={
                    "candidate_name": candidate["candidate_name"],
                    "model_version": candidate["model_version"],
                    "model_kind": candidate["model_kind"],
                    "dataset_scope": "validation_tail_20pct",
                    "horizon_min": horizon_min,
                    "promotable": bool(candidate["promotable"]),
                    "trade_cost_pct": float(candidate["trade_cost_pct"]),
                    "trade_hit_rate": float(candidate["trade_hit_rate"]),
                    "win_rate": float(candidate["win_rate"]),
                    "average_confidence": float(candidate["average_confidence"]),
                    "average_net_return_pct": float(candidate["average_net_return_pct"]),
                    "cumulative_net_return_pct": float(candidate["cumulative_net_return_pct"]),
                    "trades_taken": int(candidate["trades_taken"]),
                    "rows_evaluated": int(candidate["rows_evaluated"]),
                    "actual_label_counts": dict(candidate["actual_label_counts"]),
                    "predicted_label_counts": dict(candidate["predicted_label_counts"]),
                },
            )
        )

    ranked = sorted(candidates, key=_challenger_sort_key, reverse=True)
    candidate_results: list[ChallengerCandidateResult] = []
    for index, candidate in enumerate(ranked, start=1):
        candidate_results.append(
            ChallengerCandidateResult(
                rank=index,
                candidate_name=str(candidate["candidate_name"]),
                model_version=str(candidate["model_version"]),
                model_kind=str(candidate["model_kind"]),
                training_run_id=str(candidate["training_run_id"]),
                promotable=bool(candidate["promotable"]),
                overall_accuracy=float(candidate["overall_accuracy"]),
                trade_hit_rate=float(candidate["trade_hit_rate"]),
                win_rate=float(candidate["win_rate"]),
                average_net_return_pct=float(candidate["average_net_return_pct"]),
                cumulative_net_return_pct=float(candidate["cumulative_net_return_pct"]),
                trades_taken=int(candidate["trades_taken"]),
                rows_evaluated=int(candidate["rows_evaluated"]),
                ranking_score=_challenger_ranking_score(candidate),
            )
        )

    best_candidate = ranked[0]
    walk_forward_reference = _load_latest_walk_forward_report(settings.runtime_data_dir, horizon_min)
    walk_forward_gate = _build_walk_forward_gate(walk_forward_reference)
    recommended_action, recommended_model_version, decision_reason = _recommend_challenger_action(
        active_candidate=active_candidate,
        ranked_candidates=ranked,
        walk_forward_gate=walk_forward_gate,
    )
    promoted_model_version: str | None = None
    promotion_applied = False
    if promote_best:
        if recommended_action == "promote":
            promotion_candidate = next(
                candidate for candidate in ranked if str(candidate["model_version"]) == recommended_model_version
            )
            promotion_entry = promotion_candidate.get("promotion_entry")
            if isinstance(promotion_entry, ModelRegistryEntry):
                registry.set_active_model(promotion_entry)
                promoted_model_version = promotion_entry.model_version
                promotion_applied = True
    active_model_version_after_run = promoted_model_version or str(active_candidate["model_version"])

    report_dir = settings.runtime_data_dir / "reports" / "challengers"
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = report_dir / f"latest-challengers-h{horizon_min}.md"
    json_path = report_dir / f"latest-challengers-h{horizon_min}.json"
    leaderboard_path = report_dir / f"leaderboard-h{horizon_min}.json"
    leaderboard_payload = []
    if leaderboard_path.exists():
        try:
            existing = json.loads(leaderboard_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                leaderboard_payload = existing
        except json.JSONDecodeError:
            leaderboard_payload = []
    payload = {
        "challenger_run_id": challenger_run_id,
        "evaluated_at": review_time.isoformat(),
        "horizon_min": horizon_min,
        "active_model_version": str(active_candidate["model_version"]),
        "best_candidate_name": best_candidate["candidate_name"],
        "best_model_version": best_candidate["model_version"],
        "recommended_action": recommended_action,
        "recommended_model_version": recommended_model_version,
        "decision_reason": decision_reason,
        "walk_forward_gate_status": walk_forward_gate["status"],
        "walk_forward_gate_reason": walk_forward_gate["reason"],
        "walk_forward_gate_reference": (
            f"runtime-data/reports/backtests/latest-walk-forward-h{horizon_min}.json"
            if walk_forward_reference
            else None
        ),
        "promotion_requested": promote_best,
        "promotion_applied": promotion_applied,
        "promoted_model_version": promoted_model_version,
        "active_model_version_after_run": active_model_version_after_run,
        "candidates": [candidate.to_dict() for candidate in candidate_results],
    }
    leaderboard_payload.append(
        {
            "challenger_run_id": challenger_run_id,
            "evaluated_at": review_time.isoformat(),
            "active_model_version": str(active_candidate["model_version"]),
            "best_candidate_name": str(best_candidate["candidate_name"]),
            "best_model_version": str(best_candidate["model_version"]),
            "recommended_action": recommended_action,
            "recommended_model_version": recommended_model_version,
            "decision_reason": decision_reason,
            "walk_forward_gate_status": walk_forward_gate["status"],
            "walk_forward_gate_reason": walk_forward_gate["reason"],
            "promotion_requested": promote_best,
            "promotion_applied": promotion_applied,
            "promoted_model_version": promoted_model_version,
            "active_model_version_after_run": active_model_version_after_run,
        }
    )
    leaderboard_payload = leaderboard_payload[-20:]
    markdown_lines = [
        f"# Challenger Review H{horizon_min}",
        "",
        "## Summary",
        "",
        f"- `active_model_version`: {active_candidate['model_version']}",
        f"- `best_candidate_name`: {best_candidate['candidate_name']}",
        f"- `best_model_version`: {best_candidate['model_version']}",
        f"- `recommended_action`: {recommended_action}",
        f"- `recommended_model_version`: {recommended_model_version}",
        f"- `decision_reason`: {decision_reason}",
        f"- `walk_forward_gate_status`: {walk_forward_gate['status']}",
        f"- `walk_forward_gate_reason`: {walk_forward_gate['reason']}",
        f"- `promotion_requested`: {promote_best}",
        f"- `promotion_applied`: {promotion_applied}",
        f"- `promoted_model_version`: {promoted_model_version or 'none'}",
        f"- `active_model_version_after_run`: {active_model_version_after_run}",
        "",
        "## Candidates",
        "",
    ]
    for candidate in candidate_results:
        markdown_lines.append(
            f"- `rank {candidate.rank}` {candidate.candidate_name} "
            f"model={candidate.model_version} kind={candidate.model_kind} "
            f"trades={candidate.trades_taken} accuracy={candidate.overall_accuracy:.4f} "
            f"net={candidate.cumulative_net_return_pct:.4f} score={candidate.ranking_score:.4f}"
        )
    markdown_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    leaderboard_path.write_text(json.dumps(leaderboard_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return ChallengerRunResult(
        challenger_run_id=challenger_run_id,
        horizon_min=horizon_min,
        active_model_version=str(active_candidate["model_version"]),
        best_model_version=str(best_candidate["model_version"]),
        best_candidate_name=str(best_candidate["candidate_name"]),
        recommended_action=recommended_action,
        recommended_model_version=recommended_model_version,
        decision_reason=decision_reason,
        walk_forward_gate_status=str(walk_forward_gate["status"]),
        walk_forward_gate_reason=str(walk_forward_gate["reason"]),
        promotion_requested=promote_best,
        promotion_applied=promotion_applied,
        promoted_model_version=promoted_model_version,
        active_model_version_after_run=active_model_version_after_run,
        report_markdown_path=markdown_path,
        report_json_path=json_path,
        leaderboard_json_path=leaderboard_path,
        candidates=candidate_results,
    )
