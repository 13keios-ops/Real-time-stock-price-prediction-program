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
from app.services.collector import collect_kis_watchlist_snapshots
from app.services.runtime import run_demo_pipeline, run_kis_snapshot_pipeline
from app.universe.watchlist import parse_symbol_list


def main() -> int:
    parser = argparse.ArgumentParser(description="Realtime stock prediction program foundation runner.")
    parser.add_argument("--demo", action="store_true", help="Run the local demo pipeline.")
    parser.add_argument("--kis-snapshot", action="store_true", help="Fetch and store a single KIS REST market snapshot.")
    parser.add_argument("--kis-watchlist-snapshot", action="store_true", help="Fetch and store KIS REST snapshots for a watchlist.")
    parser.add_argument("--kis-current-price", action="store_true", help="Fetch domestic stock current price via KIS REST.")
    parser.add_argument("--kis-orderbook", action="store_true", help="Fetch domestic stock orderbook via KIS REST.")
    parser.add_argument("--kis-approval-key", action="store_true", help="Issue a KIS WebSocket approval key.")
    parser.add_argument("--symbol", default="005930", help="Target symbol for the demo run.")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols for watchlist snapshot runs.")
    parser.add_argument("--watchlist-file", default="config/watchlist.txt", help="Watchlist file path for batch snapshot runs.")
    parser.add_argument("--project-root", default=".", help="Project root for config and runtime paths.")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    if args.demo:
        result = run_demo_pipeline(project_root=project_root, symbol=args.symbol)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.kis_snapshot or args.kis_watchlist_snapshot or args.kis_current_price or args.kis_orderbook or args.kis_approval_key:
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

    parser.error(
        "Choose one of --demo, --kis-snapshot, --kis-watchlist-snapshot, --kis-current-price, --kis-orderbook, or --kis-approval-key."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
