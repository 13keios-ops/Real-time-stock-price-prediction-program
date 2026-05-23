#!/usr/bin/env python3
"""Generate a readiness token_refresh check from a KIS paper/live token request."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.brokers.kis_auth import KisTokenManager, get_kis_profile
from app.config.settings import load_settings
from app.services.kis_token_probe import probe_kis_token_refresh_check


DEFAULT_OUTPUT_PATH = Path("runtime-data/reports/live-readiness/token-refresh-check.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--mode", choices=("paper", "live"), default="paper")
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--use-cache", action="store_true", help="Do not force token refresh; accept a valid cached token.")
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    output_path = _resolve_inside_repo(args.output_path, project_root, "output_path")
    settings = load_settings(project_root=project_root)
    profile = get_kis_profile(settings, args.mode)
    token_manager = KisTokenManager(profile)
    payload = probe_kis_token_refresh_check(
        token_manager,
        mode=args.mode,
        force_refresh=not args.use_cache,
    )
    payload["probe_context"] = {
        "mode": args.mode,
        "access": "auth-only",
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
