"""Local JSONL artifact storage used for initial runtime validation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class JsonlArtifactStore:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root

    def append(self, category: str, stream_name: str, record: dict[str, Any], event_time: datetime) -> Path:
        day_folder = self.runtime_root / category / event_time.strftime("%Y-%m-%d")
        day_folder.mkdir(parents=True, exist_ok=True)
        destination = day_folder / f"{stream_name}.jsonl"
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
        return destination
