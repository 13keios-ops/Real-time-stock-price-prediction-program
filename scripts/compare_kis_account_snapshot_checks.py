#!/usr/bin/env python3
"""Compare sanitized KIS paper/live account snapshot check files."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.kis_account_shape_comparison import compare_kis_account_snapshot_checks


DEFAULT_PAPER_CHECK_PATH = Path("runtime-data/reports/live-readiness/account-snapshot-check-paper.json")
DEFAULT_LIVE_CHECK_PATH = Path("runtime-data/reports/live-readiness/account-snapshot-check-live.json")
DEFAULT_OUTPUT_PATH = Path("runtime-data/reports/live-readiness/account-shape-paper-live-comparison.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--paper-check-path", default=str(DEFAULT_PAPER_CHECK_PATH))
    parser.add_argument("--live-check-path", default=str(DEFAULT_LIVE_CHECK_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    paper_path = _resolve_inside_repo(args.paper_check_path, project_root, "paper_check_path")
    live_path = _resolve_inside_repo(args.live_check_path, project_root, "live_check_path")
    output_path = _resolve_inside_repo(args.output_path, project_root, "output_path")

    paper_check = _load_object(paper_path, "paper_check_path")
    live_check = _load_object(live_path, "live_check_path")
    payload = compare_kis_account_snapshot_checks(
        paper_check,
        live_check,
        checked_at=datetime.now(timezone.utc),
    )
    payload["probe_context"] = {
        "access": "offline-sanitized-comparison",
        "paper_check_path": _display_path(paper_path, project_root),
        "live_check_path": _display_path(live_path, project_root),
        "output_path": _display_path(output_path, project_root),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_blocked and not payload["passed"]:
        return 1
    return 0


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"{label} does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{label} must contain a JSON object: {path}")
    return payload


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


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
