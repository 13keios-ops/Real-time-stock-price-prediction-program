#!/usr/bin/env python3
"""Probe KIS paper domestic-stock orderability with zero order calls."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.brokers.kis_auth import get_kis_profile
from app.brokers.kis_readonly import get_kis_readonly_client
from app.config.settings import load_settings
from app.services.kis_orderability_probe import (
    build_orderability_dry_run,
    probe_kis_paper_orderability,
)
from app.utils.time import get_market_session_status, now_local


DEFAULT_DB_PATH = Path("runtime-data/dev.db")
DEFAULT_WATCHLIST_PATH = Path("config/watchlist.txt")
DEFAULT_REPORT_PATH = Path(
    "runtime-data/reports/broker-paper/latest-kis-paper-orderability.json"
)
DEFAULT_ATTEMPT_PATH = Path(
    "runtime-data/reports/broker-paper/latest-kis-paper-orderability-attempt.json"
)


def _read_watchlist(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def select_probe_input(
    *,
    db_path: Path,
    watchlist_path: Path,
    symbol: str | None = None,
    order_price: float | None = None,
) -> tuple[str, float | None, str]:
    selected_symbol = str(symbol or "").strip()
    source = "explicit"
    if not selected_symbol:
        watchlist = _read_watchlist(watchlist_path)
        selected_symbol = watchlist[0] if watchlist else ""
        source = "watchlist"
    if order_price is not None and order_price > 0:
        return selected_symbol, float(order_price), source
    if not db_path.exists() or not selected_symbol:
        return selected_symbol, None, source
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            """
            SELECT close
            FROM curated_minute_bars
            WHERE symbol = ? AND close > 0
            ORDER BY bar_time DESC
            LIMIT 1
            """,
            (selected_symbol,),
        ).fetchone()
    finally:
        connection.close()
    return (
        selected_symbol,
        float(row[0]) if row is not None else None,
        "latest_curated_minute_close",
    )


def _resolve_inside_repo(value: str, root: Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"{label} must stay inside repository root: {resolved}") from exc
    return resolved


def _runtime_running(root: Path) -> bool:
    state_path = root / "runtime-data/reports/live-runtime/state/listener-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    pid = state.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    cmdline_path = Path(f"/proc/{pid}/cmdline")
    try:
        return "--kis-ws-listen" in cmdline_path.read_text(
            encoding="utf-8", errors="ignore"
        )
    except OSError:
        return False


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--database-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--watchlist-path", default=str(DEFAULT_WATCHLIST_PATH))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--attempt-path", default=str(DEFAULT_ATTEMPT_PATH))
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--order-price", type=float, default=None)
    parser.add_argument("--order-type", default="01")
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).expanduser().resolve()
    db_path = _resolve_inside_repo(args.database_path, root, "database_path")
    watchlist_path = _resolve_inside_repo(
        args.watchlist_path, root, "watchlist_path"
    )
    report_path = _resolve_inside_repo(args.report_path, root, "report_path")
    attempt_path = _resolve_inside_repo(args.attempt_path, root, "attempt_path")
    settings = load_settings(project_root=root)
    profile = get_kis_profile(settings, "paper")
    checked_at = datetime.now(timezone.utc)
    symbol, order_price, input_source = select_probe_input(
        db_path=db_path,
        watchlist_path=watchlist_path,
        symbol=args.symbol,
        order_price=args.order_price,
    )
    product_shape = {
        "product_code_present": bool(profile.product_code),
        "product_code_length": len(profile.product_code),
        "product_code_is_domestic_stock_default": profile.product_code == "01",
    }

    if not args.execute:
        payload = build_orderability_dry_run(
            symbol=symbol,
            order_price=order_price,
            order_type=args.order_type,
            checked_at=checked_at,
            **product_shape,
        )
        payload["input_source"] = input_source
        _write(attempt_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    local_now = now_local(settings.timezone)
    session = get_market_session_status(settings.market_calendar, local_now)
    blockers = []
    if session in {"pre-open", "regular-session"}:
        blockers.append("protected_market_session")
    if _runtime_running(root):
        blockers.append("live_runtime_running")
    if not profile.is_configured:
        blockers.append("paper_profile_not_configured")
    if not symbol:
        blockers.append("symbol_unavailable")
    if order_price is None or order_price <= 0:
        blockers.append("recent_reference_price_unavailable")
    if blockers:
        payload = build_orderability_dry_run(
            symbol=symbol,
            order_price=order_price,
            order_type=args.order_type,
            checked_at=checked_at,
            **product_shape,
        )
        payload.update(
            {
                "status": "blocked",
                "blocking_reasons": blockers,
                "market_session": session,
                "input_source": input_source,
            }
        )
        _write(attempt_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    client = get_kis_readonly_client(
        settings,
        mode="paper",
        timeout_seconds=args.timeout_seconds,
    )
    payload = probe_kis_paper_orderability(
        client,
        symbol=symbol,
        order_price=float(order_price),
        order_type=args.order_type,
        checked_at=checked_at,
        **product_shape,
    )
    payload.update(
        {
            "market_session": session,
            "input_source": input_source,
            "paper_profile_mode": profile.mode,
        }
    )
    _write(attempt_path, payload)
    _write(report_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] in {"orderability_ok", "orderability_zero"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
