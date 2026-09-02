#!/usr/bin/env python3
"""Build or backfill the sanitized ten-day paper reconciliation history."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.services.paper_reconciliation_history import (
    load_paper_reconciliation_history,
    record_paper_reconciliation_history,
)
from app.utils.time import get_market_session_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--record-latest", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    settings = load_settings(project_root=project_root)
    latest_path = (
        settings.runtime_data_dir
        / "reports"
        / "reconciliation"
        / "latest-paper-account-sync.json"
    )
    if args.record_latest:
        if not latest_path.is_file():
            raise SystemExit(f"latest reconciliation report not found: {latest_path}")
        payload = json.loads(latest_path.read_text(encoding="utf-8"))
        as_of = datetime.fromisoformat(str(payload["as_of"]))
        session_status = str(payload.get("market_session_status") or "").strip()
        if not session_status:
            session_status = get_market_session_status(settings.market_calendar, as_of)
        result = record_paper_reconciliation_history(
            settings.runtime_data_dir,
            payload,
            market_session_status=session_status,
            account_epoch_id=settings.kis_paper_account_lifecycle.account_epoch_id,
            account_activated_on=settings.kis_paper_account_lifecycle.activated_on,
        )
        summary = result["summary"]
        output = {
            "status": summary.get("status"),
            "recorded": True,
            "entry_path": result["entry_path"],
            "summary_json_path": result["summary_json_path"],
            "days_available": summary.get("days_available"),
            "required_days": summary.get("required_days"),
        }
    else:
        summary = load_paper_reconciliation_history(
            settings.runtime_data_dir,
            account_epoch_id=settings.kis_paper_account_lifecycle.account_epoch_id,
            account_activated_on=settings.kis_paper_account_lifecycle.activated_on,
        )
        output = {
            "status": summary.get("status"),
            "recorded": False,
            "days_available": summary.get("days_available"),
            "required_days": summary.get("required_days"),
        }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
