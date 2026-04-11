"""Watchlist loading helpers."""

from __future__ import annotations

from pathlib import Path


DEFAULT_WATCHLIST_PATH = Path("config") / "watchlist.txt"


def load_watchlist(project_root: Path, watchlist_path: str | Path | None = None) -> list[str]:
    path = Path(watchlist_path) if watchlist_path is not None else DEFAULT_WATCHLIST_PATH
    if not path.is_absolute():
        path = project_root / path
    if not path.exists():
        return []

    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        symbols.append(candidate)
    return symbols


def parse_symbol_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]
