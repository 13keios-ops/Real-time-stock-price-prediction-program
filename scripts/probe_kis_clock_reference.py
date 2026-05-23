#!/usr/bin/env python3
"""Generate a readiness system_clock check from a read-only KIS quote response.

The script calls one KIS current-price read for paper or live mode, reads only
the response HTTP Date header, and writes a sanitized readiness check JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.brokers.kis_readonly import get_kis_readonly_client
from app.config.settings import load_settings
from app.services.system_clock import DEFAULT_MAX_CLOCK_SKEW_SECONDS
from app.services.system_clock_probe import (
    DEFAULT_CLOCK_PROBE_MARKET_CODE,
    DEFAULT_CLOCK_PROBE_SYMBOL,
    build_system_clock_reference_comparison,
    probe_kis_system_clock_check,
)


DEFAULT_OUTPUT_PATH = Path("runtime-data/reports/live-readiness/system-clock-check.json")
DEFAULT_COMPARISON_OUTPUT_PATH = Path("runtime-data/reports/live-readiness/system-clock-paper-live-comparison.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--mode", choices=("paper", "live"), default="paper")
    parser.add_argument(
        "--compare-paper-live",
        action="store_true",
        help="Run read-only quote probes against paper and live KIS endpoints and compare only sanitized HTTP Date references.",
    )
    parser.add_argument("--symbol", default=DEFAULT_CLOCK_PROBE_SYMBOL)
    parser.add_argument("--market-code", default=DEFAULT_CLOCK_PROBE_MARKET_CODE)
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument("--max-skew-seconds", type=float, default=DEFAULT_MAX_CLOCK_SKEW_SECONDS)
    parser.add_argument("--max-reference-delta-seconds", type=float, default=1.0)
    parser.add_argument(
        "--fail-on-blocked",
        action="store_true",
        help="Exit non-zero when the generated system_clock check does not pass.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    default_output_path = DEFAULT_COMPARISON_OUTPUT_PATH if args.compare_paper_live else DEFAULT_OUTPUT_PATH
    output_path = _resolve_inside_repo(args.output_path or str(default_output_path), project_root, "output_path")
    settings = load_settings(project_root=project_root)
    if args.compare_paper_live:
        paper_client = get_kis_readonly_client(settings, mode="paper", timeout_seconds=args.timeout_seconds)
        live_client = get_kis_readonly_client(settings, mode="live", timeout_seconds=args.timeout_seconds)
        paper_check = probe_kis_system_clock_check(
            paper_client,
            symbol=args.symbol,
            market_code=args.market_code,
            max_skew_seconds=args.max_skew_seconds,
            reference_source="kis_rest_http_date_paper",
        )
        live_check = probe_kis_system_clock_check(
            live_client,
            symbol=args.symbol,
            market_code=args.market_code,
            max_skew_seconds=args.max_skew_seconds,
            reference_source="kis_rest_http_date_live",
        )
        payload = build_system_clock_reference_comparison(
            paper_check,
            live_check,
            max_reference_delta_seconds=args.max_reference_delta_seconds,
        )
        payload["probe_context"] = {
            "mode": "paper_live_comparison",
            "access": "read-only",
            "request": "get_current_price",
            "output_path": _display_path(output_path, project_root),
        }
    else:
        readonly_client = get_kis_readonly_client(settings, mode=args.mode, timeout_seconds=args.timeout_seconds)
        check = probe_kis_system_clock_check(
            readonly_client,
            symbol=args.symbol,
            market_code=args.market_code,
            max_skew_seconds=args.max_skew_seconds,
        )
        payload = dict(check)
        payload["probe_context"] = {
            "mode": args.mode,
            "access": "read-only",
            "request": "get_current_price",
            "output_path": _display_path(output_path, project_root),
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_blocked and not bool(payload.get("passed", False)):
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
