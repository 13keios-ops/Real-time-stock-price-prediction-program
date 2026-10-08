#!/usr/bin/env python3
"""Observe the pinned post-recovery contract without activating official evaluation."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.services.e7_interval_evidence import (
    build_post_recovery_progress, load_post_recovery_contract, write_post_recovery_progress,
)
from app.utils.time import get_market_session_status, now_local
from scripts.generate_e7_daily_evidence import _runtime_running, _resolve_inside_repo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--database-path", default="runtime-data/dev.db")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    settings = load_settings(project_root=root)
    now = now_local(settings.timezone)
    session = get_market_session_status(settings.market_calendar, now)
    reasons = []
    if session in ("pre-open", "regular-session"):
        reasons.append("protected_market_session")
    if _runtime_running(root):
        reasons.append("live_runtime_running")
    if reasons:
        print(json.dumps({"status": "blocked", "blocking_reasons": reasons,
                          "database_access_started": False, "report_written": False}))
        return 2
    try:
        database = _resolve_inside_repo(args.database_path, root, "database_path")
        contract = load_post_recovery_contract(root / "docs/e7-post-recovery-acceptance-20261009.json")
        if (contract.future_intervals[0].start.date() <= now.date()
                < contract.future_intervals[-1].end.date()
                and now.weekday() < 5
                and now.date().isoformat() not in settings.market_calendar.holidays
                and session != "post-close"):
            print(json.dumps({"status": "blocked", "blocking_reasons": ["post_close_required"],
                              "database_access_started": False, "report_written": False}))
            return 2
        report = build_post_recovery_progress(
            database, acceptance_contract=contract, generated_at=now,
            holidays=settings.market_calendar.holidays,
        )
        path, written = write_post_recovery_progress(
            report, report_root=root / "runtime-data/reports/research/e7/post-recovery",
        )
        stored = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps({**stored, "report_written": written, "report_path": str(path)},
                         indent=2, sort_keys=True))
        return 1 if stored["status"] == "invalid_evidence" else 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
        # Do not echo raw DB/path errors or credential-bearing configuration.
        print(json.dumps({"status": "blocked", "blocking_reasons": ["post_recovery_evidence_unavailable"],
                          "report_written": False, "official_evaluation_permitted": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
