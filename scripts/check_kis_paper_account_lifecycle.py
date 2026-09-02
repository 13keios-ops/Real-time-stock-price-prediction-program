#!/usr/bin/env python3
"""Report the tracked KIS paper-account expiry and Phase 0 baseline compatibility."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.services.kis_paper_account_lifecycle import (
    build_kis_paper_account_lifecycle,
    render_kis_paper_account_lifecycle_markdown,
)
from app.services.paper_reconciliation_history import load_paper_reconciliation_history


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--as-of", help="Optional YYYY-MM-DD evaluation date.")
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write sanitized latest JSON/Markdown under runtime-data/reports/broker-paper.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    settings = load_settings(project_root=project_root)
    lifecycle = settings.kis_paper_account_lifecycle
    history = load_paper_reconciliation_history(
        settings.runtime_data_dir,
        account_epoch_id=lifecycle.account_epoch_id,
        account_activated_on=lifecycle.activated_on,
    )
    payload = build_kis_paper_account_lifecycle(
        settings,
        phase0_history=history,
        as_of=args.as_of,
    )
    payload["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    if args.write_report:
        report_dir = settings.runtime_data_dir / "reports" / "broker-paper"
        json_path = report_dir / "latest-kis-paper-account-lifecycle.json"
        markdown_path = report_dir / "latest-kis-paper-account-lifecycle.md"
        _write_text_atomic(
            json_path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        _write_text_atomic(
            markdown_path,
            render_kis_paper_account_lifecycle_markdown(payload),
        )
        payload["report_paths"] = {
            "json": str(json_path),
            "markdown": str(markdown_path),
        }

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
