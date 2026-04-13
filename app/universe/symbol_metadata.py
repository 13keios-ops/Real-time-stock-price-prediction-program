"""Symbol name helpers for dashboard and local reports."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_SYMBOL_NAMES_PATH = Path("config") / "symbol_names.json"


def load_symbol_names(project_root: Path, path: str | Path | None = None) -> dict[str, str]:
    target = Path(path) if path is not None else DEFAULT_SYMBOL_NAMES_PATH
    if not target.is_absolute():
        target = project_root / target
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key).strip(): str(value).strip() for key, value in payload.items() if str(key).strip()}


def resolve_symbol_name(symbol: str, symbol_names: dict[str, str]) -> str:
    name = symbol_names.get(str(symbol), "").strip()
    if not name:
        return str(symbol)
    return name


def resolve_symbol_label(symbol: str, symbol_names: dict[str, str]) -> str:
    name = resolve_symbol_name(symbol, symbol_names)
    if name == str(symbol):
        return str(symbol)
    return f"{name} ({symbol})"
