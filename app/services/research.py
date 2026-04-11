"""Research and training services built on the local SQLite runtime store."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.collectors.market_data import orderbook_from_kis_ws_record
from app.config.settings import load_settings
from app.features.minute_bars import build_feature_snapshot
from app.labels.thresholds import classify_return
from app.models.baseline import BaselineDirectionModel
from app.models.centroid import CentroidArtifact, CentroidDirectionModel
from app.models.loader import load_named_builtin_model, load_prediction_model
from app.models.registry import ModelRegistry, ModelRegistryEntry
from app.observability.logging import configure_logging
from app.storage.contracts import FeatureLabel, FeatureSnapshot, MinuteBar, ModelEvaluation, OrderbookSnapshot, TrainingRun
from app.storage.runtime_writer import RuntimeWriter, get_sqlite_store
from app.utils.time import now_local


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
    decision_reason: str
    promoted_model_version: str | None
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
            "decision_reason": self.decision_reason,
            "promoted_model_version": self.promoted_model_version,
            "report_markdown_path": str(self.report_markdown_path),
            "report_json_path": str(self.report_json_path),
            "leaderboard_json_path": str(self.leaderboard_json_path),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _minute_floor(timestamp: datetime) -> datetime:
    return timestamp.replace(second=0, microsecond=0)


def _row_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _load_labeled_feature_dataset(sqlite_store, horizon_min: int) -> tuple[list[str], list[dict[str, object]]]:
    rows = sqlite_store.fetch_feature_rows(horizon_min=horizon_min)
    if len(rows) < 5:
        raise ValueError("Not enough labeled feature rows are available for training.")

    dataset: list[dict[str, object]] = []
    feature_names: list[str] = []
    for row in rows:
        values = json.loads(row["values_json"])
        if not feature_names:
            feature_names = sorted(values.keys())
        dataset.append(
            {
                "symbol": row["symbol"],
                "event_time": _row_timestamp(str(row["event_time"])),
                "label": str(row["label"]),
                "future_return_pct": float(row["future_return_pct"]),
                "values": {name: float(values[name]) for name in feature_names},
                "features": [float(values[name]) for name in feature_names],
            }
        )
    dataset.sort(key=lambda item: (str(item["event_time"]), str(item["symbol"])))
    return feature_names, dataset


def _split_dataset(dataset: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    split_index = max(1, math.floor(len(dataset) * 0.8))
    split_index = min(split_index, len(dataset) - 1)
    return dataset[:split_index], dataset[split_index:]


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

    return "promote", str(best_promotable["model_version"]), "Promote the challenger based on return and trade coverage."


def _evaluate_rows_with_model(
    *,
    rows: list[dict[str, object]],
    model,
    settings,
    horizon_min: int,
    prediction_prefix: str,
) -> dict[str, object]:
    trade_cost_pct = _estimate_trade_cost_pct(settings)
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
        actual_label = str(row["label"])
        confidence = max(prediction.probability_up, prediction.probability_flat, prediction.probability_down)
        actual_counter[actual_label] += 1
        predicted_counter[predicted_label] += 1
        confidence_sum += confidence

        if predicted_label == actual_label:
            overall_correct += 1

        if predicted_label != "up" or prediction.probability_up < settings.strategy.min_signal_confidence:
            continue

        trades_taken += 1
        future_return_pct = float(row["future_return_pct"])
        gross_return_sum += future_return_pct
        net_return_pct = future_return_pct - trade_cost_pct
        net_return_sum += net_return_pct
        if actual_label == "up":
            trade_correct += 1
        if net_return_pct > 0:
            wins += 1

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
        "actual_label_counts": dict(actual_counter),
        "predicted_label_counts": dict(predicted_counter),
    }


def build_minute_bars_from_sqlite(project_root: Path) -> MinuteBarBuildResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(settings)
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

    writer = RuntimeWriter.from_settings(settings)
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


def build_feature_dataset_from_sqlite(project_root: Path, horizons: tuple[int, ...] = (15, 60)) -> FeatureDatasetBuildResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for feature dataset generation.")

    bars_by_symbol: dict[str, list[MinuteBar]] = defaultdict(list)
    for row in sqlite_store.fetch_minute_bars():
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

    orderbook_rows = sqlite_store.fetch_orderbook_snapshots()
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

    writer = RuntimeWriter.from_settings(settings)
    features_written = 0
    labels_written = 0

    for symbol, bars in bars_by_symbol.items():
        bars.sort(key=lambda bar: bar.bar_time)
        by_time = {bar.bar_time: bar for bar in bars}
        latest_orderbook: OrderbookSnapshot | None = None
        for bar in bars:
            latest_orderbook = orderbooks_by_symbol[symbol].get(bar.bar_time, latest_orderbook)
            if latest_orderbook is None:
                continue
            feature_snapshot = build_feature_snapshot(bar, latest_orderbook, settings.feature_set_version)
            writer.write_feature_snapshot(feature_snapshot)
            features_written += 1

            for horizon in horizons:
                future_bar = by_time.get(bar.bar_time + timedelta(minutes=horizon))
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
                writer.write_feature_label(label)
                labels_written += 1

    return FeatureDatasetBuildResult(
        features_written=features_written,
        labels_written=labels_written,
        horizons=list(horizons),
        runtime_root=settings.runtime_data_dir,
    )


def train_centroid_baseline_from_sqlite(project_root: Path, horizon_min: int = 15) -> BaselineTrainingResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for training.")

    feature_names, dataset = _load_labeled_feature_dataset(sqlite_store, horizon_min=horizon_min)
    train_rows, validation_rows = _split_dataset(dataset)

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
    training_run_id = f"train-centroid-h{horizon_min}-{started_at.strftime('%Y%m%d%H%M%S')}"
    evaluation_id = f"eval-centroid-h{horizon_min}-{started_at.strftime('%Y%m%d%H%M%S')}"

    artifact_path = _write_centroid_artifact(runtime_root=settings.runtime_data_dir, model=model)
    ModelRegistry(settings.runtime_data_dir).set_active_model(
        ModelRegistryEntry(
            horizon_min=horizon_min,
            model_version=model_version,
            artifact_path=str(artifact_path),
            feature_set_version=settings.feature_set_version,
            model_kind="centroid_artifact",
        )
    )

    writer = RuntimeWriter.from_settings(settings)
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
    )


def run_signal_backtest_from_sqlite(project_root: Path, horizon_min: int = 15) -> BacktestResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for backtesting.")

    _, dataset = _load_labeled_feature_dataset(sqlite_store, horizon_min=horizon_min)
    _, validation_rows = _split_dataset(dataset)
    if not validation_rows:
        raise ValueError("Not enough validation rows are available for backtesting.")

    model = load_prediction_model(settings, horizon_min=horizon_min)
    evaluation_time = now_local(settings.timezone)
    evaluation_id = f"backtest-h{horizon_min}-{evaluation_time.strftime('%Y%m%d%H%M%S')}"
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

    writer = RuntimeWriter.from_settings(settings)
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
) -> WalkForwardBacktestResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for walk-forward backtesting.")

    feature_names, dataset = _load_labeled_feature_dataset(sqlite_store, horizon_min=horizon_min)
    if step_rows is None:
        step_rows = test_window_rows
    if min_train_rows <= 0 or test_window_rows <= 0 or step_rows <= 0:
        raise ValueError("Walk-forward parameters must be positive integers.")
    if len(dataset) < min_train_rows + test_window_rows:
        raise ValueError("Not enough labeled feature rows are available for walk-forward backtesting.")

    evaluation_time = now_local(settings.timezone)
    evaluation_id = f"walk-forward-h{horizon_min}-{evaluation_time.strftime('%Y%m%d%H%M%S')}"
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
    for fold_index, train_end in enumerate(range(min_train_rows, len(dataset) - test_window_rows + 1, step_rows), start=1):
        train_rows = dataset[:train_end]
        test_rows = dataset[train_end : train_end + test_window_rows]
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
                "train_rows": len(train_rows),
                "test_rows": rows_evaluated,
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
        "dataset_scope": "walk_forward_expanding_window",
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
        "fold_summaries": fold_summaries,
    }

    writer = RuntimeWriter.from_settings(settings)
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
        "",
        "## Fold Summary",
        "",
    ]
    for fold in fold_summaries:
        markdown_lines.append(
            f"- `fold {fold['fold']}` train={fold['train_rows']} test={fold['test_rows']} "
            f"accuracy={float(fold['overall_accuracy']):.4f} trades={fold['trades_taken']} "
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
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for challenger evaluation.")

    feature_names, dataset = _load_labeled_feature_dataset(sqlite_store, horizon_min=horizon_min)
    train_rows, validation_rows = _split_dataset(dataset)
    if not validation_rows:
        raise ValueError("Not enough validation rows are available for challenger evaluation.")

    review_time = now_local(settings.timezone)
    challenger_run_id = f"challenger-h{horizon_min}-{review_time.strftime('%Y%m%d%H%M%S')}"
    writer = RuntimeWriter.from_settings(settings)
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
    recommended_action, recommended_model_version, decision_reason = _recommend_challenger_action(
        active_candidate=active_candidate,
        ranked_candidates=ranked,
    )
    promoted_model_version: str | None = None
    if promote_best:
        if recommended_action == "promote":
            promotion_candidate = next(
                candidate for candidate in ranked if str(candidate["model_version"]) == recommended_model_version
            )
            promotion_entry = promotion_candidate.get("promotion_entry")
            if isinstance(promotion_entry, ModelRegistryEntry):
                registry.set_active_model(promotion_entry)
                promoted_model_version = promotion_entry.model_version
        else:
            promoted_model_version = recommended_model_version

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
        "promoted_model_version": promoted_model_version,
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
        f"- `promoted_model_version`: {promoted_model_version or 'none'}",
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
        decision_reason=decision_reason,
        promoted_model_version=promoted_model_version,
        report_markdown_path=markdown_path,
        report_json_path=json_path,
        leaderboard_json_path=leaderboard_path,
        candidates=candidate_results,
    )
