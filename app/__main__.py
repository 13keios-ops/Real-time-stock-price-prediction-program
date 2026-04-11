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
from app.services.collector import collect_kis_watchlist_snapshots, poll_kis_watchlist_snapshots
from app.services.orchestrator import run_kis_dev_cycle, run_synthetic_dev_cycle
from app.services.reporting import build_runtime_report
from app.services.research import (
    build_feature_dataset_from_sqlite,
    build_minute_bars_from_sqlite,
    run_signal_backtest_from_sqlite,
    run_walk_forward_backtest_from_sqlite,
    train_centroid_baseline_from_sqlite,
)
from app.services.streaming import build_sample_ws_frames, replay_ws_frames, run_kis_ws_listener_sync
from app.services.synthetic import seed_synthetic_intraday_data
from app.services.runtime import run_demo_pipeline, run_kis_snapshot_pipeline
from app.universe.watchlist import parse_symbol_list


def main() -> int:
    parser = argparse.ArgumentParser(description="Realtime stock prediction program foundation runner.")
    parser.add_argument("--demo", action="store_true", help="Run the local demo pipeline.")
    parser.add_argument("--kis-snapshot", action="store_true", help="Fetch and store a single KIS REST market snapshot.")
    parser.add_argument("--kis-watchlist-snapshot", action="store_true", help="Fetch and store KIS REST snapshots for a watchlist.")
    parser.add_argument("--kis-watchlist-poll", action="store_true", help="Run repeated KIS REST snapshot polling for a watchlist.")
    parser.add_argument("--build-minute-bars", action="store_true", help="Build minute bars from raw ticks stored in SQLite.")
    parser.add_argument("--build-feature-dataset", action="store_true", help="Build feature snapshots and labels from SQLite minute bars.")
    parser.add_argument("--train-baseline", action="store_true", help="Train the local centroid baseline using SQLite feature rows.")
    parser.add_argument("--run-backtest", action="store_true", help="Run the validation-tail backtest using the active prediction model.")
    parser.add_argument("--run-walk-forward", action="store_true", help="Run an expanding-window walk-forward backtest.")
    parser.add_argument("--seed-synthetic-data", action="store_true", help="Seed synthetic intraday market data into JSONL and SQLite.")
    parser.add_argument("--replay-sample-ws", action="store_true", help="Replay sample WebSocket frames through the online pipeline.")
    parser.add_argument("--kis-ws-listen", action="store_true", help="Listen to KIS WebSocket frames and run the online pipeline.")
    parser.add_argument("--run-synthetic-dev-cycle", action="store_true", help="Run seed -> bars -> features -> training in one command.")
    parser.add_argument("--run-kis-dev-cycle", action="store_true", help="Run KIS polling -> bars -> features -> optional training in one command.")
    parser.add_argument("--build-runtime-report", action="store_true", help="Build a Markdown and JSON runtime report from SQLite.")
    parser.add_argument("--kis-current-price", action="store_true", help="Fetch domestic stock current price via KIS REST.")
    parser.add_argument("--kis-orderbook", action="store_true", help="Fetch domestic stock orderbook via KIS REST.")
    parser.add_argument("--kis-approval-key", action="store_true", help="Issue a KIS WebSocket approval key.")
    parser.add_argument("--symbol", default="005930", help="Target symbol for the demo run.")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols for watchlist snapshot runs.")
    parser.add_argument("--watchlist-file", default="config/watchlist.txt", help="Watchlist file path for batch snapshot runs.")
    parser.add_argument("--iterations", type=int, default=1, help="Iteration count for polling commands.")
    parser.add_argument("--interval-seconds", type=float, default=0.0, help="Sleep interval between polling iterations.")
    parser.add_argument("--horizon-min", type=int, default=15, help="Prediction horizon in minutes for training commands.")
    parser.add_argument("--walk-forward-min-train-rows", type=int, default=30, help="Initial training rows for walk-forward backtests.")
    parser.add_argument("--walk-forward-test-rows", type=int, default=10, help="Per-fold test rows for walk-forward backtests.")
    parser.add_argument("--walk-forward-step-rows", type=int, default=10, help="Fold step size for walk-forward backtests.")
    parser.add_argument("--minutes", type=int, default=80, help="Minute count for synthetic data seeding.")
    parser.add_argument("--max-frames", type=int, default=50, help="Maximum number of WebSocket frames to consume.")
    parser.add_argument("--max-reconnects", type=int, default=2, help="Maximum reconnect attempts for KIS WebSocket listening.")
    parser.add_argument("--no-trade-channel", action="store_true", help="Disable trade-channel subscriptions for WebSocket listening.")
    parser.add_argument("--no-orderbook-channel", action="store_true", help="Disable orderbook-channel subscriptions for WebSocket listening.")
    parser.add_argument("--project-root", default=".", help="Project root for config and runtime paths.")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

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

    if args.train_baseline:
        result = train_centroid_baseline_from_sqlite(project_root=project_root, horizon_min=args.horizon_min)
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

    if args.replay_sample_ws:
        result = replay_ws_frames(project_root=project_root, frames=build_sample_ws_frames(symbol=args.symbol))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if (
        args.kis_snapshot
        or args.kis_watchlist_snapshot
        or args.kis_watchlist_poll
        or args.kis_ws_listen
        or args.kis_current_price
        or args.kis_orderbook
        or args.kis_approval_key
    ):
        settings = load_settings(project_root=project_root)
        profile = get_active_kis_profile(settings)
        token_manager = KisTokenManager(profile)

        if not profile.is_ready_for_quotes:
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
        "Choose one of --demo, --seed-synthetic-data, --run-synthetic-dev-cycle, --run-kis-dev-cycle, --build-runtime-report, --replay-sample-ws, --build-minute-bars, --build-feature-dataset, --train-baseline, --run-backtest, --run-walk-forward, --kis-snapshot, --kis-watchlist-snapshot, --kis-watchlist-poll, --kis-ws-listen, --kis-current-price, --kis-orderbook, or --kis-approval-key."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
