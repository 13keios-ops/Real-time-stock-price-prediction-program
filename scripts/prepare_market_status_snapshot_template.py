#!/usr/bin/env python3
"""Prepare a fail-closed manual market-status snapshot template."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.market_status_probe import (
    ALLOWED_MANUAL_MARKET_STATUS_SOURCES,
    compute_symbol_set_hash,
)

DEFAULT_WATCHLIST_PATH = Path("config/watchlist.txt")
DEFAULT_OUTPUT_PATH = Path("runtime-data/reports/live-readiness/market-status-snapshot.json")
KST = ZoneInfo("Asia/Seoul")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--watchlist-file", default=str(DEFAULT_WATCHLIST_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--source", default="manual_operator_snapshot", choices=ALLOWED_MANUAL_MARKET_STATUS_SOURCES)
    parser.add_argument("--trading-day", default="")
    parser.add_argument("--snapshot-id", default="")
    parser.add_argument("--stale-after", default="")
    parser.add_argument("--stale-after-minutes", type=int, default=600)
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    watchlist_file = _resolve_inside_repo(args.watchlist_file, project_root, "watchlist_file")
    output_path = _resolve_inside_repo(args.output_path, project_root, "output_path")
    now = datetime.now(KST)
    trading_day = args.trading_day.strip() or now.date().isoformat()
    stale_after = _parse_optional_datetime(args.stale_after) or (now + timedelta(minutes=args.stale_after_minutes))
    symbols = _read_symbols(watchlist_file)
    if not symbols:
        raise SystemExit(f"watchlist_file has no symbols: {watchlist_file}")
    symbol_set_hash = compute_symbol_set_hash(symbols)
    snapshot_id = args.snapshot_id.strip() or f"market-status-{trading_day.replace('-', '')}-manual-template"
    payload = {
        "snapshot_id": snapshot_id,
        "trading_day": trading_day,
        "created_at": now.isoformat(),
        "source": args.source,
        "symbol_set_hash": symbol_set_hash,
        "stale_after": stale_after.astimezone(KST).isoformat(),
        "status_json": {
            "market_session": "regular",
            "source_generated_at": now.isoformat(),
            "template_fail_closed": True,
            "operator_confirmation_required": True,
            "symbols": {symbol: _fail_closed_symbol_status() for symbol in symbols},
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _read_symbols(path: Path) -> list[str]:
    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        symbols.append(stripped.split()[0].strip())
    return symbols


def _fail_closed_symbol_status() -> dict[str, object]:
    return {
        "tradable": None,
        "vi_active": None,
        "halted": None,
        "managed": None,
        "caution": None,
        "limit_up": None,
        "limit_down": None,
        "single_price_auction": None,
        "corporate_action": None,
        "operator_checked": False,
        "note": "Fill every field from manual market-status evidence before Phase 1 readiness.",
    }


def _resolve_inside_repo(value: str, repo_root: Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise SystemExit(f"{label} must stay inside repository root: {resolved}") from exc
    return resolved


def _parse_optional_datetime(value: str) -> datetime | None:
    stripped = value.strip()
    if not stripped:
        return None
    normalized = stripped[:-1] + "+00:00" if stripped.endswith("Z") else stripped
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--stale-after must include timezone")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())