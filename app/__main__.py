"""Command line entrypoint for local demos."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from app.brokers.kis_auth import KisApiError, KisTokenManager, get_active_kis_profile
from app.brokers.kis_quote_rest import KisRestQuoteClient
from app.brokers.kis_quote_ws import KisWebSocketQuoteClient
from app.config.settings import load_settings
from app.collectors.historical import DEFAULT_START_DATE, collect_pykrx_daily_proxy_history, parse_date_text
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
    run_model_challenger_review_from_sqlite,
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
    parser.add_argument("--build-minute-bars", action="store_true", help="Build minute bars from raw ticks stored in SQLite.")
    parser.add_argument("--build-feature-dataset", action="store_true", help="Build feature snapshots and labels from SQLite minute bars.")
    parser.add_argument("--rebuild-actual-ml", action="store_true", help="Delete offline ML artifacts and rebuild actual-runtime-only features, labels, training, and reports.")
    parser.add_argument("--train-baseline", action="store_true", help="Train the local centroid baseline using SQLite feature rows.")
    parser.add_argument("--train-lightgbm", action="store_true", help="Train the LightGBM model using SQLite feature rows.")
    parser.add_argument("--set-active-builtin", action="store_true", help="Set a builtin model as the active runtime model.")
    parser.add_argument("--run-backtest", action="store_true", help="Run the validation-tail backtest using the active prediction model.")
    parser.add_argument("--run-walk-forward", action="store_true", help="Run an expanding-window walk-forward backtest.")
    parser.add_argument("--run-challengers", action="store_true", help="Run multi-model challenger evaluation on the validation split.")
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

    if args.demo:
        result = run_demo_pipeline(project_root=project_root, symbol=args.symbol)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.build_minute_bars:
        result = build_minute_bars_from_sqlite(project_root=project_root)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.build_feature_dataset:
        result = build_feature_dataset_from_sqlite(project_root=project_root)
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
        result = train_lightgbm_from_sqlite(project_root=project_root, horizon_min=args.horizon_min, set_active=False)
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

    if args.run_walk_forward:
        result = run_walk_forward_backtest_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            min_train_rows=args.walk_forward_min_train_rows,
            test_window_rows=args.walk_forward_test_rows,
            step_rows=args.walk_forward_step_rows,
            gap_rows=args.walk_forward_gap_rows,
            max_train_rows=args.walk_forward_max_train_rows,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.run_challengers:
        result = run_model_challenger_review_from_sqlite(
            project_root=project_root,
            horizon_min=args.horizon_min,
            promote_best=args.promote_best_challenger,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
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
                client = KisRestQuoteClient(profile=profile, token_manager=token_manager)
                quote = client.get_current_price(symbol=args.symbol)
                print(json.dumps(asdict(quote), ensure_ascii=False, indent=2))
                return 0

            if args.kis_orderbook:
                client = KisRestQuoteClient(profile=profile, token_manager=token_manager)
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
        "Choose one of --demo, --seed-synthetic-data, --run-synthetic-dev-cycle, --run-kis-dev-cycle, --collect-historical-data, --build-runtime-report, --cleanup-runtime-test-data, --build-dashboard, --serve-dashboard, --replay-sample-ws, --build-minute-bars, --build-feature-dataset, --rebuild-actual-ml, --train-baseline, --train-lightgbm, --set-active-builtin, --run-backtest, --run-walk-forward, --run-challengers, --kis-snapshot, --kis-watchlist-snapshot, --kis-watchlist-poll, --kis-ws-listen, --verify-kis-ws, --kis-current-price, --kis-orderbook, --kis-account-balance, --reconcile-paper-accounts, --sync-broker-paper-orders, --align-local-paper-to-broker, or --kis-approval-key."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
