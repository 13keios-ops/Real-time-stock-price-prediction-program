"""Command line entrypoint for local demos."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from app.brokers.kis_auth import KisApiError, KisTokenManager, get_active_kis_profile
from app.brokers.kis_readonly import get_kis_readonly_client
from app.brokers.kis_quote_ws import KisWebSocketQuoteClient
from app.config.settings import load_settings
from app.collectors.historical import (
    DEFAULT_START_DATE,
    collect_kis_rest_historical_minutes,
    collect_pykrx_daily_proxy_history,
    parse_date_text,
)
from app.services.broker_paper_sync import sync_broker_paper_orders
from app.services.collector import collect_kis_watchlist_snapshots, poll_kis_watchlist_snapshots
from app.services.dashboard import build_dashboard_snapshot, prepare_dashboard_server
from app.services.kis_account import refresh_kis_account_report
from app.services.kis_verification import verify_kis_websocket_runtime
from app.services.orchestrator import run_kis_dev_cycle, run_synthetic_dev_cycle
from app.services.paper_alignment import align_local_paper_to_broker
from app.services.paper_reconciliation import reconcile_paper_accounts
from app.services.reporting import build_runtime_report
from app.services.research import (
    build_feature_dataset_from_sqlite,
    build_minute_bars_from_sqlite,
    rebuild_actual_runtime_ml_state,
    run_lightgbm_buy_signal_diagnostics_from_sqlite,
    run_lightgbm_feature_profile_experiment_from_sqlite,
    run_lightgbm_feature_source_experiment_from_sqlite,
    run_lightgbm_label_band_experiment_from_sqlite,
    run_lightgbm_label_band_reproducibility_review_from_sqlite,
    run_lightgbm_performance_diagnostics_from_sqlite,
    run_lightgbm_probability_calibration_experiment_from_sqlite,
    run_model_challenger_review_from_sqlite,
    run_cybos_bar_only_experiment_from_sqlite,
    run_cybos_expected_value_review_from_sqlite,
    run_cybos_label_sensitivity_review_from_sqlite,
    run_cybos_label_reproducibility_review_from_sqlite,
    run_cybos_profitability_review_from_sqlite,
    run_cybos_rule_challenger_review_from_sqlite,
    run_signal_backtest_from_sqlite,
    run_walk_forward_backtest_from_sqlite,
    set_builtin_model_active,
    train_centroid_baseline_from_sqlite,
    train_lightgbm_from_sqlite,
)
from app.services.runtime import run_demo_pipeline, run_kis_snapshot_pipeline
from app.services.runtime_cleanup import cleanup_non_actual_runtime_rows
from app.services.streaming import build_sample_ws_frames, replay_ws_frames, run_kis_ws_listener_sync
from app.services.synthetic import seed_synthetic_intraday_data
from app.universe.watchlist import parse_symbol_list
from app.utils.time import now_local


def _safe_print_json(payload: dict[str, object]) -> None:
    try:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Realtime stock prediction program foundation runner.")
    parser.add_argument("--demo", action="store_true", help="Run the local demo pipeline.")
    parser.add_argument("--kis-snapshot", action="store_true", help="Fetch and store a single KIS REST market snapshot.")
    parser.add_argument("--kis-watchlist-snapshot", action="store_true", help="Fetch and store KIS REST snapshots for a watchlist.")
    parser.add_argument("--kis-watchlist-poll", action="store_true", help="Run repeated KIS REST snapshot polling for a watchlist.")
    parser.add_argument("--collect-historical-data", action="store_true", help="Collect historical watchlist data into the existing SQLite schema.")
    parser.add_argument("--collect-kis-historical", action="store_true", help="Collect KIS REST minute bars into the existing SQLite schema.")
    parser.add_argument("--build-minute-bars", action="store_true", help="Build minute bars from raw ticks stored in SQLite.")
    parser.add_argument("--build-feature-dataset", action="store_true", help="Build feature snapshots and labels from SQLite minute bars.")
    parser.add_argument("--feature-dataset-recent-days", type=int, default=0, help="Limit feature dataset generation to bars from the last N calendar days. Use 0 for full history.")
    parser.add_argument("--rebuild-actual-ml", action="store_true", help="Delete offline ML artifacts and rebuild actual-runtime-only features, labels, training, and reports.")
    parser.add_argument("--train-baseline", action="store_true", help="Train the local centroid baseline using SQLite feature rows.")
    parser.add_argument("--train-lightgbm", action="store_true", help="Train the LightGBM model using SQLite feature rows.")
    parser.add_argument("--train-lightgbm-max-rows", type=int, default=250000, help="Maximum recent labeled rows loaded for LightGBM training. Use 0 for full history.")
    parser.add_argument("--train-lightgbm-feature-market-source", default="", help="Optional raw market source filter for LightGBM training feature rows.")
    parser.add_argument("--set-active-builtin", action="store_true", help="Set a builtin model as the active runtime model.")
    parser.add_argument("--run-backtest", action="store_true", help="Run the validation-tail backtest using the active prediction model.")
    parser.add_argument("--run-walk-forward", action="store_true", help="Run an expanding-window walk-forward backtest.")
    parser.add_argument("--run-gate-walk-forward", action="store_true", help="Run the fixed gate-reference walk-forward profile.")
    parser.add_argument("--run-challengers", action="store_true", help="Run multi-model challenger evaluation on the validation split.")
    parser.add_argument("--challenger-max-rows", type=int, default=250000, help="Maximum recent labeled rows loaded for challenger evaluation. Use 0 for full history.")
    parser.add_argument("--challenger-feature-market-source", default="", help="Optional raw market source filter for challenger feature rows.")
    parser.add_argument("--run-lightgbm-buy-signal-diagnostics", action="store_true", help="Run LightGBM buy-signal threshold diagnostics without adopting thresholds.")
    parser.add_argument("--lightgbm-buy-signal-thresholds", default="0.40,0.45,0.50,0.55,0.57,0.58,0.60,0.62,0.66,0.70,0.75,0.80", help="Comma-separated probability_up thresholds for LightGBM buy-signal diagnostics.")
    parser.add_argument("--run-lightgbm-performance-diagnostics", action="store_true", help="Run LightGBM classification, probability, and direction-EV diagnostics without adopting thresholds.")
    parser.add_argument("--lightgbm-performance-thresholds", default="0.34,0.38,0.42,0.46,0.50,0.54,0.58,0.62,0.66,0.70", help="Comma-separated confidence thresholds for LightGBM direction diagnostics.")
    parser.add_argument("--run-lightgbm-feature-source-experiment", action="store_true", help="Compare mixed, KIS-only, and historical LightGBM feature-source candidates without writing artifacts.")
    parser.add_argument("--lightgbm-feature-source-candidates", default="mixed_recent,kis-ws,cybos-historical", help="Comma-separated feature market sources for LightGBM source experiment. Use mixed_recent for no source filter.")
    parser.add_argument("--lightgbm-feature-source-max-rows", type=int, default=100000, help="Maximum recent labeled rows per source candidate. Use 0 for full history.")
    parser.add_argument("--run-lightgbm-feature-profile-experiment", action="store_true", help="Run KIS live feature-profile candidates without writing artifacts.")
    parser.add_argument("--lightgbm-feature-profile-candidates", default="base,time,momentum,volatility,time_momentum_volatility", help="Comma-separated feature profiles for LightGBM feature-profile experiment.")
    parser.add_argument("--lightgbm-feature-profile-source", default="kis-ws", help="Market source for feature-profile experiment. Default is kis-ws.")
    parser.add_argument("--run-lightgbm-label-band-experiment", action="store_true", help="Review LightGBM label threshold bands without changing configured thresholds.")
    parser.add_argument("--lightgbm-label-band-thresholds", default="0.10,0.15,0.20,0.25,0.30,0.35,0.40,0.50", help="Comma-separated label threshold pct candidates for label-band experiment.")
    parser.add_argument("--run-lightgbm-label-band-reproducibility-review", action="store_true", help="Review LightGBM label threshold candidates across walk-forward and period splits without adopting thresholds.")
    parser.add_argument("--lightgbm-label-band-repro-thresholds", default="0.35,0.40,0.50", help="Comma-separated label threshold pct candidates for reproducibility review.")
    parser.add_argument("--lightgbm-label-band-repro-max-rows", type=int, default=60000, help="Maximum recent labeled rows for label-band reproducibility review. Use 0 for full history.")
    parser.add_argument("--lightgbm-label-band-repro-train-rows", type=int, default=20000, help="Train rows per full walk-forward fold for label-band reproducibility review.")
    parser.add_argument("--lightgbm-label-band-repro-test-rows", type=int, default=3000, help="Test rows per full walk-forward fold for label-band reproducibility review.")
    parser.add_argument("--lightgbm-label-band-repro-step-rows", type=int, default=10000, help="Step rows for full walk-forward label-band reproducibility review.")
    parser.add_argument("--lightgbm-label-band-repro-max-folds", type=int, default=4, help="Maximum full walk-forward folds for label-band reproducibility review.")
    parser.add_argument("--run-lightgbm-calibration-experiment", action="store_true", help="Run LightGBM probability calibration diagnostics without adopting calibration.")
    parser.add_argument("--lightgbm-calibration-temperatures", default="0.75,1.00,1.25,1.50,2.00", help="Comma-separated temperature candidates for probability calibration.")
    parser.add_argument("--lightgbm-calibration-prior-alphas", default="0.00,0.10,0.20,0.35", help="Comma-separated prior blend alpha candidates for probability calibration.")
    parser.add_argument("--run-cybos-bar-only-experiment", action="store_true", help="Run the Cybos historical bar-only LightGBM experiment.")
    parser.add_argument("--run-cybos-expected-value-review", action="store_true", help="Run train-only expected-value threshold review for Cybos LightGBM.")
    parser.add_argument("--run-cybos-profitability-review", action="store_true", help="Run Cybos F-5 profitability diagnostics, cost baseline, threshold, and H60 review.")
    parser.add_argument("--run-cybos-label-sensitivity-review", action="store_true", help="Run Cybos F-6 label threshold sensitivity diagnostics.")
    parser.add_argument("--run-cybos-label-reproducibility-review", action="store_true", help="Run Cybos F-6b threshold reproducibility diagnostics.")
    parser.add_argument("--run-cybos-rule-challengers", action="store_true", help="Run fixed Cybos rule-based challenger diagnostics.")
    parser.add_argument("--promote-best-challenger", action="store_true", help="Promote the best challenger to the active registry entry.")
    parser.add_argument("--seed-synthetic-data", action="store_true", help="Seed synthetic intraday market data into JSONL and SQLite.")
    parser.add_argument("--replay-sample-ws", action="store_true", help="Replay sample WebSocket frames through the online pipeline.")
    parser.add_argument("--kis-ws-listen", action="store_true", help="Listen to KIS WebSocket frames and run the online pipeline.")
    parser.add_argument("--verify-kis-ws", action="store_true", help="Verify KIS WebSocket readiness and optionally attempt live listening.")
    parser.add_argument("--run-synthetic-dev-cycle", action="store_true", help="Run seed -> bars -> features -> training in one command.")
    parser.add_argument("--run-kis-dev-cycle", action="store_true", help="Run KIS polling -> bars -> features -> optional training in one command.")
    parser.add_argument("--build-runtime-report", action="store_true", help="Build a Markdown and JSON runtime report from SQLite.")
    parser.add_argument("--build-dashboard", action="store_true", help="Build the latest dashboard HTML and JSON snapshot.")
    parser.add_argument("--serve-dashboard", action="store_true", help="Serve the local monitoring dashboard over HTTP.")
    parser.add_argument("--cleanup-runtime-test-data", action="store_true", help="Delete non-actual serving and paper rows from SQLite.")
    parser.add_argument("--kis-current-price", action="store_true", help="Fetch domestic stock current price via KIS REST.")
    parser.add_argument("--kis-orderbook", action="store_true", help="Fetch domestic stock orderbook via KIS REST.")
    parser.add_argument("--kis-account-balance", action="store_true", help="Fetch KIS broker account balance and write a cached report.")
    parser.add_argument("--reconcile-paper-accounts", action="store_true", help="Compare the local virtual paper book against the broker paper account.")
    parser.add_argument("--sync-broker-paper-orders", action="store_true", help="Sync broker paper-order status and fills back into the local virtual paper book.")
    parser.add_argument("--align-local-paper-to-broker", action="store_true", help="Reset the local virtual paper book to the current broker paper-account baseline.")
    parser.add_argument("--kis-approval-key", action="store_true", help="Issue a KIS WebSocket approval key.")
    parser.add_argument("--symbol", default="005930", help="Target symbol for the demo run.")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols for watchlist snapshot runs.")
    parser.add_argument("--watchlist-file", default="config/watchlist.txt", help="Watchlist file path for batch snapshot runs.")
    parser.add_argument("--iterations", type=int, default=1, help="Iteration count for polling commands.")
    parser.add_argument("--interval-seconds", type=float, default=0.0, help="Sleep interval between polling iterations.")
    parser.add_argument("--horizon-min", type=int, default=15, help="Prediction horizon in minutes for training commands.")
    parser.add_argument("--builtin-model", default="baseline", choices=("baseline", "linear_score"), help="Builtin model name for active-registry commands.")
    parser.add_argument("--walk-forward-min-train-rows", type=int, default=30, help="Initial training rows for walk-forward backtests.")
    parser.add_argument("--walk-forward-test-rows", type=int, default=10, help="Per-fold test rows for walk-forward backtests.")
    parser.add_argument("--walk-forward-step-rows", type=int, default=10, help="Fold step size for walk-forward backtests.")
    parser.add_argument("--walk-forward-gap-rows", type=int, default=None, help="Gap rows between train and test windows for walk-forward backtests.")
    parser.add_argument("--walk-forward-max-train-rows", type=int, default=None, help="Maximum rolling training rows for walk-forward backtests.")
    parser.add_argument("--walk-forward-parameter-profile", default="ad_hoc_cli", help="Provenance label written into walk-forward reports.")
    parser.add_argument("--walk-forward-feature-market-source", default="", help="Optional raw market source filter for walk-forward feature rows.")
    parser.add_argument("--cybos-experiment-train-max-rows", type=int, default=2000, help="Training rows for Cybos bar-only experiment.")
    parser.add_argument("--cybos-experiment-walk-test-rows", type=int, default=2000, help="Per-fold test rows for Cybos bar-only experiment.")
    parser.add_argument("--cybos-experiment-walk-step-rows", type=int, default=10000, help="Fold step rows for Cybos bar-only experiment.")
    parser.add_argument("--cybos-experiment-walk-gap-rows", type=int, default=15, help="Gap rows for Cybos bar-only experiment.")
    parser.add_argument("--cybos-experiment-walk-max-folds", type=int, default=120, help="Maximum sampled folds for Cybos bar-only experiment.")
    parser.add_argument("--cybos-experiment-feature-set", default="bar_only", help="Feature set for Cybos experiment: bar_only, bar_context, or bar_context_momentum.")
    parser.add_argument("--cybos-expected-value-thresholds", default="0.58,0.62,0.66,0.70,0.75,0.80,0.85,0.90", help="Comma-separated probability_up thresholds for expected-value review.")
    parser.add_argument("--cybos-expected-value-calibration-rows", type=int, default=20000, help="Train-tail calibration rows per fold for expected-value review.")
    parser.add_argument("--cybos-expected-value-min-calibration-trades", type=int, default=30, help="Minimum calibration trades required for expected-value threshold eligibility.")
    parser.add_argument("--cybos-profitability-cost-pct", type=float, default=0.13, help="Round-trip cost pct for Cybos profitability review.")
    parser.add_argument("--cybos-rule-train-max-rows", type=int, default=100000, help="Training-window rows used to position Cybos rule challenger walk-forward folds.")
    parser.add_argument("--cybos-rule-walk-test-rows", type=int, default=2000, help="Per-fold test rows for Cybos rule challenger review.")
    parser.add_argument("--cybos-rule-walk-step-rows", type=int, default=30000, help="Fold step rows for Cybos rule challenger review.")
    parser.add_argument("--cybos-rule-walk-gap-rows", type=int, default=15, help="Gap rows for Cybos rule challenger review.")
    parser.add_argument("--cybos-rule-walk-max-folds", type=int, default=50, help="Maximum sampled folds for Cybos rule challenger review.")
    parser.add_argument("--minutes", type=int, default=80, help="Minute count for synthetic data seeding.")
    parser.add_argument("--max-frames", type=int, default=50, help="Maximum number of WebSocket frames to consume. Use 0 for unlimited listening.")
    parser.add_argument("--max-reconnects", type=int, default=2, help="Maximum reconnect attempts for KIS WebSocket listening.")
    parser.add_argument("--no-trade-channel", action="store_true", help="Disable trade-channel subscriptions for WebSocket listening.")
    parser.add_argument("--no-orderbook-channel", action="store_true", help="Disable orderbook-channel subscriptions for WebSocket listening.")
    parser.add_argument("--dashboard-host", default="127.0.0.1", help="Host for the local dashboard server.")
    parser.add_argument("--dashboard-port", type=int, default=8765, help="Port for the local dashboard server.")
    parser.add_argument("--dashboard-refresh-seconds", type=int, default=600, help="Browser auto-refresh interval for the dashboard. Default is 600 seconds (10 minutes).")
    parser.add_argument("--dashboard-recent-limit", type=int, default=100, help="Recent item count shown in the dashboard.")
    parser.add_argument("--project-root", default=".", help="Project root for config and runtime paths.")
    parser.add_argument("--start-date", default="2021-01-01", help="Historical collection start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", default="", help="Historical collection end date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--start", default="", help="KIS historical collection start date in YYYY-MM-DD format.")
    parser.add_argument("--end", default="", help="KIS historical collection end date in YYYY-MM-DD format.")
    parser.add_argument("--bars-per-day", type=int, default=26, help="Proxy intraday bars per daily pykrx row.")
    parser.add_argument("--no-build-historical-features", action="store_true", help="Collect historical bars without rebuilding features and labels.")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    if args.collect_historical_data:
        result = collect_pykrx_daily_proxy_history(
            project_root=project_root,
            symbols=parse_symbol_list(args.symbols) or None,
            start_date=parse_date_text(args.start_date, default=DEFAULT_START_DATE),
            end_date=parse_date_text(args.end_date, default=DEFAULT_START_DATE) if args.end_date else None,
            bars_per_day=args.bars_per_day,
            build_features=not args.no_build_historical_features,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.collect_kis_historical:
        settings_for_date = load_settings(project_root=project_root)
        result = collect_kis_rest_historical_minutes(
            project_root=project_root,
            symbols=parse_symbol_list(args.symbols) or None,
            start_date=parse_date_text(args.start, default=DEFAULT_START_DATE),
            end_date=parse_date_text(args.end, default=now_local(settings_for_date.timezone).date()),
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.demo:
        result = run_demo_pipeline(project_root=project_root, symbol=args.symbol)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.build_minute_bars:
        result = build_minute_bars_from_sqlite(project_root=project_root)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.build_feature_dataset:
        result = build_feature_dataset_from_sqlite(
            project_root=project_root,
            recent_days=args.feature_dataset_recent_days if args.feature_dataset_recent_days > 0 else None,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.rebuild_actual_ml:
        result = rebuild_actual_runtime_ml_state(project_root=project_root, horizon_min=args.horizon_min)
        payload = result.to_dict()
        report_dir = project_root / "runtime-data" / "reports" / "actual-ml"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "latest-rebuild.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.train_baseline:
        result = train_centroid_baseline_from_sqlite(project_root=project_root, horizon_min=args.horizon_min)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.train_lightgbm:
        result = train_lightgbm_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            set_active=False,
            max_rows=args.train_lightgbm_max_rows if args.train_lightgbm_max_rows > 0 else None,
            feature_market_source=args.train_lightgbm_feature_market_source or None,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.set_active_builtin:
        result = set_builtin_model_active(
            project_root=project_root,
            horizon_min=args.horizon_min,
            builtin_name=args.builtin_model,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.run_backtest:
        result = run_signal_backtest_from_sqlite(project_root=project_root, horizon_min=args.horizon_min)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.run_gate_walk_forward:
        result = run_walk_forward_backtest_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            min_train_rows=100000,
            test_window_rows=50000,
            step_rows=50000,
            gap_rows=args.horizon_min,
            max_train_rows=200000,
            parameter_profile="gate_reference_v1",
            command_source="cli_run_gate_walk_forward",
            feature_market_source="cybos-historical",
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.run_walk_forward:
        result = run_walk_forward_backtest_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            min_train_rows=args.walk_forward_min_train_rows,
            test_window_rows=args.walk_forward_test_rows,
            step_rows=args.walk_forward_step_rows,
            gap_rows=args.walk_forward_gap_rows,
            max_train_rows=args.walk_forward_max_train_rows,
            parameter_profile=args.walk_forward_parameter_profile,
            command_source="cli_run_walk_forward",
            feature_market_source=args.walk_forward_feature_market_source or None,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.run_challengers:
        result = run_model_challenger_review_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            promote_best=args.promote_best_challenger,
            max_rows=args.challenger_max_rows if args.challenger_max_rows > 0 else None,
            feature_market_source=args.challenger_feature_market_source or None,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.run_lightgbm_buy_signal_diagnostics:
        thresholds = tuple(
            float(item.strip())
            for item in args.lightgbm_buy_signal_thresholds.split(",")
            if item.strip()
        )
        result = run_lightgbm_buy_signal_diagnostics_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            thresholds=thresholds,
            max_rows=args.challenger_max_rows if args.challenger_max_rows > 0 else None,
            feature_market_source=args.challenger_feature_market_source or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_lightgbm_performance_diagnostics:
        thresholds = tuple(
            float(item.strip())
            for item in args.lightgbm_performance_thresholds.split(",")
            if item.strip()
        )
        result = run_lightgbm_performance_diagnostics_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            thresholds=thresholds,
            max_rows=args.challenger_max_rows if args.challenger_max_rows > 0 else None,
            feature_market_source=args.challenger_feature_market_source or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_lightgbm_feature_source_experiment:
        thresholds = tuple(
            float(item.strip())
            for item in args.lightgbm_performance_thresholds.split(",")
            if item.strip()
        )
        source_candidates = tuple(
            item.strip()
            for item in args.lightgbm_feature_source_candidates.split(",")
            if item.strip()
        )
        result = run_lightgbm_feature_source_experiment_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            source_candidates=source_candidates,
            max_rows=args.lightgbm_feature_source_max_rows
            if args.lightgbm_feature_source_max_rows > 0
            else None,
            thresholds=thresholds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_lightgbm_feature_profile_experiment:
        thresholds = tuple(
            float(item.strip())
            for item in args.lightgbm_performance_thresholds.split(",")
            if item.strip()
        )
        profile_candidates = tuple(
            item.strip()
            for item in args.lightgbm_feature_profile_candidates.split(",")
            if item.strip()
        )
        result = run_lightgbm_feature_profile_experiment_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            profile_candidates=profile_candidates,
            feature_market_source=args.lightgbm_feature_profile_source or None,
            max_rows=args.lightgbm_feature_source_max_rows
            if args.lightgbm_feature_source_max_rows > 0
            else None,
            thresholds=thresholds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_lightgbm_label_band_experiment:
        thresholds = tuple(
            float(item.strip())
            for item in args.lightgbm_performance_thresholds.split(",")
            if item.strip()
        )
        label_thresholds = tuple(
            float(item.strip())
            for item in args.lightgbm_label_band_thresholds.split(",")
            if item.strip()
        )
        result = run_lightgbm_label_band_experiment_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            label_thresholds=label_thresholds,
            feature_market_source=args.lightgbm_feature_profile_source or None,
            max_rows=args.lightgbm_feature_source_max_rows
            if args.lightgbm_feature_source_max_rows > 0
            else None,
            thresholds=thresholds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_lightgbm_label_band_reproducibility_review:
        label_thresholds = tuple(
            float(item.strip())
            for item in args.lightgbm_label_band_repro_thresholds.split(",")
            if item.strip()
        )
        result = run_lightgbm_label_band_reproducibility_review_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            label_thresholds=label_thresholds,
            feature_market_source=args.lightgbm_feature_profile_source or None,
            max_rows=args.lightgbm_label_band_repro_max_rows
            if args.lightgbm_label_band_repro_max_rows > 0
            else None,
            train_rows=args.lightgbm_label_band_repro_train_rows,
            test_rows=args.lightgbm_label_band_repro_test_rows,
            step_rows=args.lightgbm_label_band_repro_step_rows,
            max_folds=args.lightgbm_label_band_repro_max_folds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_lightgbm_calibration_experiment:
        thresholds = tuple(
            float(item.strip())
            for item in args.lightgbm_performance_thresholds.split(",")
            if item.strip()
        )
        temperatures = tuple(
            float(item.strip())
            for item in args.lightgbm_calibration_temperatures.split(",")
            if item.strip()
        )
        prior_alphas = tuple(
            float(item.strip())
            for item in args.lightgbm_calibration_prior_alphas.split(",")
            if item.strip()
        )
        result = run_lightgbm_probability_calibration_experiment_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            temperatures=temperatures,
            prior_blend_alphas=prior_alphas,
            max_rows=args.challenger_max_rows if args.challenger_max_rows > 0 else None,
            feature_market_source=args.challenger_feature_market_source or None,
            thresholds=thresholds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_cybos_bar_only_experiment:
        result = run_cybos_bar_only_experiment_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            train_max_rows=args.cybos_experiment_train_max_rows,
            walk_forward_test_rows=args.cybos_experiment_walk_test_rows,
            walk_forward_step_rows=args.cybos_experiment_walk_step_rows,
            walk_forward_gap_rows=args.cybos_experiment_walk_gap_rows,
            walk_forward_max_folds=args.cybos_experiment_walk_max_folds,
            feature_set_name=args.cybos_experiment_feature_set,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_cybos_expected_value_review:
        threshold_grid = tuple(
            float(item.strip())
            for item in args.cybos_expected_value_thresholds.split(",")
            if item.strip()
        )
        result = run_cybos_expected_value_review_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            train_max_rows=args.cybos_experiment_train_max_rows,
            walk_forward_test_rows=args.cybos_experiment_walk_test_rows,
            walk_forward_step_rows=args.cybos_experiment_walk_step_rows,
            walk_forward_gap_rows=args.cybos_experiment_walk_gap_rows,
            walk_forward_max_folds=args.cybos_experiment_walk_max_folds,
            feature_set_name=args.cybos_experiment_feature_set,
            trade_cost_pct=args.cybos_profitability_cost_pct,
            threshold_grid=threshold_grid,
            calibration_rows=args.cybos_expected_value_calibration_rows,
            min_calibration_trades=args.cybos_expected_value_min_calibration_trades,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_cybos_profitability_review:
        result = run_cybos_profitability_review_from_sqlite(
            project_root=project_root,
            trade_cost_pct=args.cybos_profitability_cost_pct,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_cybos_label_sensitivity_review:
        result = run_cybos_label_sensitivity_review_from_sqlite(
            project_root=project_root,
            trade_cost_pct=args.cybos_profitability_cost_pct,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_cybos_label_reproducibility_review:
        result = run_cybos_label_reproducibility_review_from_sqlite(
            project_root=project_root,
            trade_cost_pct=args.cybos_profitability_cost_pct,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.run_cybos_rule_challengers:
        result = run_cybos_rule_challenger_review_from_sqlite(
            project_root=project_root,
            train_max_rows=args.cybos_rule_train_max_rows,
            walk_forward_test_rows=args.cybos_rule_walk_test_rows,
            walk_forward_step_rows=args.cybos_rule_walk_step_rows,
            walk_forward_gap_rows=args.cybos_rule_walk_gap_rows,
            walk_forward_max_folds=args.cybos_rule_walk_max_folds,
            trade_cost_pct=args.cybos_profitability_cost_pct,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.seed_synthetic_data:
        result = seed_synthetic_intraday_data(project_root=project_root, symbol=args.symbol, minutes=args.minutes)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.run_synthetic_dev_cycle:
        result = run_synthetic_dev_cycle(
            project_root=project_root,
            symbol=args.symbol,
            minutes=args.minutes,
            train_horizon_min=args.horizon_min,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.run_kis_dev_cycle:
        resolved_symbols = parse_symbol_list(args.symbols)
        result = run_kis_dev_cycle(
            project_root=project_root,
            iterations=args.iterations,
            interval_seconds=args.interval_seconds,
            train_horizon_min=args.horizon_min,
            symbols=resolved_symbols or None,
            watchlist_path=args.watchlist_file,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.build_runtime_report:
        result = build_runtime_report(project_root=project_root)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.cleanup_runtime_test_data:
        result = cleanup_non_actual_runtime_rows(project_root=project_root)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.build_dashboard:
        result = build_dashboard_snapshot(
            project_root=project_root,
            refresh_seconds=args.dashboard_refresh_seconds,
            recent_limit=args.dashboard_recent_limit,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.serve_dashboard:
        server, info = prepare_dashboard_server(
            project_root=project_root,
            host=args.dashboard_host,
            port=args.dashboard_port,
            refresh_seconds=args.dashboard_refresh_seconds,
            recent_limit=args.dashboard_recent_limit,
        )
        _safe_print_json(info.to_dict())
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0

    if args.replay_sample_ws:
        result = replay_ws_frames(project_root=project_root, frames=build_sample_ws_frames(symbol=args.symbol))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if (
        args.kis_snapshot
        or args.kis_watchlist_snapshot
        or args.kis_watchlist_poll
        or args.kis_ws_listen
        or args.verify_kis_ws
        or args.kis_current_price
        or args.kis_orderbook
        or args.kis_account_balance
        or args.reconcile_paper_accounts
        or args.sync_broker_paper_orders
        or args.align_local_paper_to_broker
        or args.kis_approval_key
    ):
        settings = load_settings(project_root=project_root)
        profile = get_active_kis_profile(settings)
        token_manager = KisTokenManager(profile)

        if not profile.is_ready_for_quotes and not args.verify_kis_ws:
            parser.error("KIS credentials are not configured. Fill .env values before using KIS commands.")

        try:
            if args.kis_snapshot:
                result = run_kis_snapshot_pipeline(project_root=project_root, symbol=args.symbol)
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
                return 0

            if args.kis_watchlist_snapshot:
                resolved_symbols = parse_symbol_list(args.symbols)
                result = collect_kis_watchlist_snapshots(
                    project_root=project_root,
                    symbols=resolved_symbols or None,
                    watchlist_path=args.watchlist_file,
                )
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
                return 0

            if args.kis_watchlist_poll:
                resolved_symbols = parse_symbol_list(args.symbols)
                result = poll_kis_watchlist_snapshots(
                    project_root=project_root,
                    symbols=resolved_symbols or None,
                    watchlist_path=args.watchlist_file,
                    iterations=args.iterations,
                    interval_seconds=args.interval_seconds,
                )
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
                return 0

            if args.kis_ws_listen:
                resolved_symbols = parse_symbol_list(args.symbols)
                result = run_kis_ws_listener_sync(
                    project_root=project_root,
                    symbols=resolved_symbols or None,
                    watchlist_path=args.watchlist_file,
                    include_trade=not args.no_trade_channel,
                    include_orderbook=not args.no_orderbook_channel,
                    max_frames=args.max_frames,
                    max_reconnects=args.max_reconnects,
                )
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
                return 0

            if args.verify_kis_ws:
                resolved_symbols = parse_symbol_list(args.symbols)
                result = verify_kis_websocket_runtime(
                    project_root=project_root,
                    symbols=resolved_symbols or None,
                    watchlist_path=args.watchlist_file,
                    max_frames=args.max_frames,
                    max_reconnects=args.max_reconnects,
                )
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
                return 0

            if args.kis_current_price:
                client = get_kis_readonly_client(settings, mode=profile.mode)
                quote = client.get_current_price(symbol=args.symbol)
                print(json.dumps(asdict(quote), ensure_ascii=False, indent=2))
                return 0

            if args.kis_orderbook:
                client = get_kis_readonly_client(settings, mode=profile.mode)
                quote = client.get_orderbook(symbol=args.symbol)
                print(json.dumps(asdict(quote), ensure_ascii=False, indent=2))
                return 0

            if args.kis_account_balance:
                result = refresh_kis_account_report(project_root=project_root, force_refresh=True)
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
                return 0

            if args.reconcile_paper_accounts:
                result = reconcile_paper_accounts(project_root=project_root, force_account_refresh=True)
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
                return 0

            if args.sync_broker_paper_orders:
                result = sync_broker_paper_orders(project_root=project_root)
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
                return 0

            if args.align_local_paper_to_broker:
                result = align_local_paper_to_broker(project_root=project_root)
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
                return 0

            if args.kis_approval_key:
                ws_client = KisWebSocketQuoteClient(profile=profile, token_manager=token_manager)
                payload = {
                    "approval_key": ws_client.issue_approval_key(),
                    "endpoint": ws_client.profile.websocket_tryitout_url,
                    "trade_tr_id": ws_client.build_domestic_trade_subscription(args.symbol).tr_id,
                    "orderbook_tr_id": ws_client.build_domestic_orderbook_subscription(args.symbol).tr_id,
                }
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0
        except KisApiError as exc:
            parser.error(str(exc))
        except ValueError as exc:
            parser.error(str(exc))

    parser.error(
        "Choose one of --demo, --seed-synthetic-data, --run-synthetic-dev-cycle, --run-kis-dev-cycle, --collect-historical-data, --collect-kis-historical, --build-runtime-report, --cleanup-runtime-test-data, --build-dashboard, --serve-dashboard, --replay-sample-ws, --build-minute-bars, --build-feature-dataset, --rebuild-actual-ml, --train-baseline, --train-lightgbm, --set-active-builtin, --run-backtest, --run-walk-forward, --run-challengers, --run-lightgbm-buy-signal-diagnostics, --run-cybos-bar-only-experiment, --run-cybos-expected-value-review, --run-cybos-profitability-review, --run-cybos-label-sensitivity-review, --run-cybos-label-reproducibility-review, --run-cybos-rule-challengers, --kis-snapshot, --kis-watchlist-snapshot, --kis-watchlist-poll, --kis-ws-listen, --verify-kis-ws, --kis-current-price, --kis-orderbook, --kis-account-balance, --reconcile-paper-accounts, --sync-broker-paper-orders, --align-local-paper-to-broker, or --kis-approval-key."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
