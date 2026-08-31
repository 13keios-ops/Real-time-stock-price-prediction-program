#!/usr/bin/env python3
"""Generate one post-close E7 future evidence artifact from SQLite read-only."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.services.e7_daily_evidence import (
    build_e7_daily_evidence,
    write_e7_daily_evidence_once,
)
from app.utils.time import (
    get_market_session_status,
    is_market_holiday,
    now_local,
)


DEFAULT_DB_PATH = Path("runtime-data/dev.db")
DEFAULT_REPORT_DIR = Path("runtime-data/reports/research/e7/daily")
DEFAULT_LATEST_PATH = Path(
    "runtime-data/reports/research/e7/latest-e7-daily-evidence.json"
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
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text(
            encoding="utf-8", errors="ignore"
        )
    except OSError:
        return False
    return "--kis-ws-listen" in cmdline


def _blocked_payload(
    *,
    session: str,
    through_day: date,
    reasons: list[str],
) -> dict[str, object]:
    return {
        "status": "blocked",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_session": session,
        "through_trading_day": through_day.isoformat(),
        "blocking_reasons": reasons,
        "database_access_started": False,
        "report_written": False,
        "order_calls": 0,
        "cancel_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--database-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--latest-path", default=str(DEFAULT_LATEST_PATH))
    parser.add_argument("--through-trading-day", default=None)
    args = parser.parse_args()

    root = Path(args.project_root).expanduser().resolve()
    database_path = _resolve_inside_repo(
        args.database_path, root, "database_path"
    )
    report_dir = _resolve_inside_repo(args.report_dir, root, "report_dir")
    latest_path = _resolve_inside_repo(args.latest_path, root, "latest_path")
    settings = load_settings(project_root=root)
    local_now = now_local(settings.timezone)
    through_day = (
        date.fromisoformat(args.through_trading_day)
        if args.through_trading_day
        else local_now.date()
    )
    session = get_market_session_status(settings.market_calendar, local_now)
    reasons = []
    if session != "post-close":
        reasons.append("post_close_required")
    if through_day != local_now.date():
        reasons.append("current_trading_day_only")
    if through_day.weekday() >= 5 or is_market_holiday(
        settings.market_calendar,
        datetime.combine(through_day, datetime.min.time(), tzinfo=local_now.tzinfo),
    ):
        reasons.append("real_trading_day_required")
    if _runtime_running(root):
        reasons.append("live_runtime_running")
    if not database_path.exists():
        reasons.append("runtime_database_missing")
    if reasons:
        payload = _blocked_payload(
            session=session,
            through_day=through_day,
            reasons=reasons,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    dated_path = report_dir / f"{through_day.isoformat()}.json"
    if dated_path.exists():
        payload = json.loads(dated_path.read_text(encoding="utf-8"))
        output = dict(payload)
        output["idempotent_reuse"] = True
        output["report_written"] = False
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    payload = build_e7_daily_evidence(
        database_path,
        through_trading_day=through_day,
    )
    payload["market_session"] = session
    payload["safety"] = {
        "database_access": "read-only",
        "database_mutation": False,
        "order_calls": 0,
        "cancel_calls": 0,
    }
    stored, written = write_e7_daily_evidence_once(
        payload,
        dated_path=dated_path,
        latest_path=latest_path,
    )
    output = dict(stored)
    output["idempotent_reuse"] = not written
    output["report_written"] = written
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if stored["evidence_health"]["status"] == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
