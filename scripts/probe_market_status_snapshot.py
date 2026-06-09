#!/usr/bin/env python3
"""Generate a readiness market_status check from a manual snapshot file."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.market_status_probe import (
    build_market_status_check,
    compute_symbol_set_hash,
    failed_market_status_check,
    market_status_snapshot_from_payload,
)


DEFAULT_SNAPSHOT_PATH = Path("runtime-data/reports/live-readiness/market-status-snapshot.json")
DEFAULT_OUTPUT_PATH = Path("runtime-data/reports/live-readiness/market-status-check.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--snapshot-path", default=str(DEFAULT_SNAPSHOT_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--symbols", default="")
    parser.add_argument("--symbols-file", default="")
    parser.add_argument("--checked-at", default="")
    parser.add_argument("--print-symbol-set-hash", action="store_true")
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    snapshot_path = _resolve_inside_repo(args.snapshot_path, project_root, "snapshot_path")
    output_path = _resolve_inside_repo(args.output_path, project_root, "output_path")
    checked_at: datetime | None = None
    try:
        checked_at = _parse_optional_datetime(args.checked_at, "--checked-at")
        snapshot_payload = _load_json(snapshot_path)
        symbols = _resolve_symbols(
            explicit_symbols=args.symbols,
            symbols_file=args.symbols_file,
            snapshot_payload=snapshot_payload,
            project_root=project_root,
        )
        if args.print_symbol_set_hash:
            print(compute_symbol_set_hash(symbols))
            return 0
        snapshot = market_status_snapshot_from_payload(snapshot_payload)
        payload = build_market_status_check(snapshot, symbols=symbols, checked_at=checked_at)
    except Exception as exc:
        payload = failed_market_status_check(
            summary="market status snapshot check failed",
            checked_at=checked_at,
            error_type=type(exc).__name__,
        )
    payload["probe_context"] = {
        "access": "local-file",
        "request": "manual_market_status_snapshot",
        "snapshot_path": _display_path(snapshot_path, project_root),
        "output_path": _display_path(output_path, project_root),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_blocked and not bool(payload.get("passed", False)):
        return 1
    return 0


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("snapshot payload must be an object")
    return payload


def _resolve_symbols(
    *,
    explicit_symbols: str,
    symbols_file: str,
    snapshot_payload: dict[str, Any],
    project_root: Path,
) -> list[str]:
    if explicit_symbols.strip():
        return _split_symbols(explicit_symbols)
    if symbols_file.strip():
        path = _resolve_inside_repo(symbols_file, project_root, "symbols_file")
        return _symbols_from_file(path)
    status_json = snapshot_payload.get("status_json", {})
    if isinstance(status_json, dict) and isinstance(status_json.get("symbols"), dict):
        return sorted(str(symbol) for symbol in status_json["symbols"])
    return []


def _split_symbols(value: str) -> list[str]:
    return [symbol.strip() for symbol in value.replace(";", ",").split(",") if symbol.strip()]


def _symbols_from_file(path: Path) -> list[str]:
    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        symbols.append(stripped.split()[0].strip())
    return symbols


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


def _parse_optional_datetime(value: str, label: str) -> datetime | None:
    stripped = value.strip()
    if not stripped:
        return None
    normalized = stripped[:-1] + "+00:00" if stripped.endswith("Z") else stripped
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include timezone")
    return parsed


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
