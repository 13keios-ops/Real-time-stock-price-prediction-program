#!/usr/bin/env python3
"""Generate a readiness account_snapshot check from a read-only KIS account query."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.brokers.kis_readonly import get_kis_readonly_client
from app.config.settings import load_settings
from app.services.kis_account_probe import (
    build_system_clock_check_from_account_snapshot_headers,
    probe_kis_account_snapshot_check,
)
from app.services.system_clock import DEFAULT_MAX_CLOCK_SKEW_SECONDS


DEFAULT_OUTPUT_PATH = Path("runtime-data/reports/live-readiness/account-snapshot-check.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--mode", choices=("paper", "live"), default="paper")
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument(
        "--system-clock-output-path",
        default=None,
        help="Also write a system_clock check from the same account response HTTP Date header.",
    )
    parser.add_argument("--max-skew-seconds", type=float, default=DEFAULT_MAX_CLOCK_SKEW_SECONDS)
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    output_path = _resolve_inside_repo(args.output_path, project_root, "output_path")
    settings = load_settings(project_root=project_root)
    readonly_client = get_kis_readonly_client(settings, mode=args.mode, timeout_seconds=args.timeout_seconds)
    checked_at = datetime.now(timezone.utc)
    payload = probe_kis_account_snapshot_check(readonly_client, mode=args.mode, checked_at=checked_at)
    payload["probe_context"] = {
        "mode": args.mode,
        "access": "read-only",
        "request": "get_account_balance",
        "output_path": _display_path(output_path, project_root),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    system_clock_payload = None
    if args.system_clock_output_path:
        system_clock_output_path = _resolve_inside_repo(
            args.system_clock_output_path,
            project_root,
            "system_clock_output_path",
        )
        system_clock_payload = build_system_clock_check_from_account_snapshot_headers(
            readonly_client,
            mode=args.mode,
            checked_at=checked_at,
            max_skew_seconds=args.max_skew_seconds,
        )
        system_clock_payload["probe_context"] = {
            "mode": args.mode,
            "access": "read-only",
            "request": "get_account_balance",
            "derived_from": "account_snapshot",
            "output_path": _display_path(system_clock_output_path, project_root),
        }
        system_clock_output_path.parent.mkdir(parents=True, exist_ok=True)
        system_clock_output_path.write_text(
            json.dumps(system_clock_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if system_clock_payload is not None:
        print(json.dumps(system_clock_payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_blocked and (
        not bool(payload.get("passed", False))
        or (system_clock_payload is not None and not bool(system_clock_payload.get("passed", False)))
    ):
        return 1
    return 0


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
