"""High-level orchestration for collection and research cycles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.collector import WatchlistPollingResult, poll_kis_watchlist_snapshots
from app.services.research import (
    BacktestResult,
    BaselineTrainingResult,
    ChallengerRunResult,
    FeatureDatasetBuildResult,
    MinuteBarBuildResult,
    WalkForwardBacktestResult,
    build_feature_dataset_from_sqlite,
    build_minute_bars_from_sqlite,
    run_model_challenger_review_from_sqlite,
    run_signal_backtest_from_sqlite,
    run_walk_forward_backtest_from_sqlite,
    train_centroid_baseline_from_sqlite,
    train_lightgbm_from_sqlite,
)
from app.services.synthetic import SyntheticSeedResult, seed_synthetic_intraday_data


@dataclass(slots=True)
class DevCycleResult:
    mode: str
    runtime_root: Path
    collection: dict[str, object] | None
    minute_bars: dict[str, object]
    feature_dataset: dict[str, object]
    training: dict[str, object] | None
    backtest: dict[str, object] | None
    walk_forward: dict[str, object] | None
    challengers: dict[str, object] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "runtime_root": str(self.runtime_root),
            "collection": self.collection,
            "minute_bars": self.minute_bars,
            "feature_dataset": self.feature_dataset,
            "training": self.training,
            "backtest": self.backtest,
            "walk_forward": self.walk_forward,
            "challengers": self.challengers,
        }


def run_synthetic_dev_cycle(
    project_root: Path,
    symbol: str = "005930",
    minutes: int = 90,
    train_horizon_min: int = 15,
) -> DevCycleResult:
    seed_result: SyntheticSeedResult = seed_synthetic_intraday_data(
        project_root=project_root,
        symbol=symbol,
        minutes=minutes,
    )
    minute_result: MinuteBarBuildResult = build_minute_bars_from_sqlite(project_root=project_root)
    feature_result: FeatureDatasetBuildResult = build_feature_dataset_from_sqlite(project_root=project_root)
    try:
        training_result = train_lightgbm_from_sqlite(
            project_root=project_root,
            horizon_min=train_horizon_min,
            set_active=False,
        )
    except ValueError:
        training_result = train_centroid_baseline_from_sqlite(
            project_root=project_root,
            horizon_min=train_horizon_min,
        )
    backtest_result: BacktestResult = run_signal_backtest_from_sqlite(
        project_root=project_root,
        horizon_min=train_horizon_min,
    )
    walk_forward_result: WalkForwardBacktestResult = run_walk_forward_backtest_from_sqlite(
        project_root=project_root,
        horizon_min=train_horizon_min,
    )
    challenger_result: ChallengerRunResult = run_model_challenger_review_from_sqlite(
        project_root=project_root,
        horizon_min=train_horizon_min,
        promote_best=False,
    )
    return DevCycleResult(
        mode="synthetic",
        runtime_root=seed_result.runtime_root,
        collection=seed_result.to_dict(),
        minute_bars=minute_result.to_dict(),
        feature_dataset=feature_result.to_dict(),
        training=training_result.to_dict(),
        backtest=backtest_result.to_dict(),
        walk_forward=walk_forward_result.to_dict(),
        challengers=challenger_result.to_dict(),
    )


def run_kis_dev_cycle(
    project_root: Path,
    iterations: int = 5,
    interval_seconds: float = 5.0,
    train_horizon_min: int = 15,
    symbols: list[str] | None = None,
    watchlist_path: str | Path | None = None,
) -> DevCycleResult:
    collection_result: WatchlistPollingResult = poll_kis_watchlist_snapshots(
        project_root=project_root,
        symbols=symbols,
        watchlist_path=watchlist_path,
        iterations=iterations,
        interval_seconds=interval_seconds,
    )
    minute_result: MinuteBarBuildResult = build_minute_bars_from_sqlite(project_root=project_root)
    feature_result: FeatureDatasetBuildResult = build_feature_dataset_from_sqlite(project_root=project_root)
    training_result: BaselineTrainingResult | None = None
    backtest_result: BacktestResult | None = None
    walk_forward_result: WalkForwardBacktestResult | None = None
    challenger_result: ChallengerRunResult | None = None
    try:
        try:
            training_result = train_lightgbm_from_sqlite(
                project_root=project_root,
                horizon_min=train_horizon_min,
                set_active=False,
            )
        except ValueError:
            training_result = train_centroid_baseline_from_sqlite(
                project_root=project_root,
                horizon_min=train_horizon_min,
            )
        backtest_result = run_signal_backtest_from_sqlite(
            project_root=project_root,
            horizon_min=train_horizon_min,
        )
        walk_forward_result = run_walk_forward_backtest_from_sqlite(
            project_root=project_root,
            horizon_min=train_horizon_min,
        )
        challenger_result = run_model_challenger_review_from_sqlite(
            project_root=project_root,
            horizon_min=train_horizon_min,
            promote_best=False,
        )
    except ValueError:
        training_result = None
        backtest_result = None
        walk_forward_result = None
        challenger_result = None

    return DevCycleResult(
        mode="kis",
        runtime_root=collection_result.runtime_root,
        collection=collection_result.to_dict(),
        minute_bars=minute_result.to_dict(),
        feature_dataset=feature_result.to_dict(),
        training=training_result.to_dict() if training_result else None,
        backtest=backtest_result.to_dict() if backtest_result else None,
        walk_forward=walk_forward_result.to_dict() if walk_forward_result else None,
        challengers=challenger_result.to_dict() if challenger_result else None,
    )
