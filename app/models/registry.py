"""Model registry helpers for selecting active runtime artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ModelRegistryEntry:
    horizon_min: int
    model_version: str
    artifact_path: str
    feature_set_version: str


class ModelRegistry:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.registry_path = runtime_root / "ml" / "registry.json"

    def load(self) -> dict[str, object]:
        if not self.registry_path.exists():
            return {"active_models": {}}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def save(self, payload: dict[str, object]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_active_model(self, entry: ModelRegistryEntry) -> None:
        payload = self.load()
        active_models = dict(payload.get("active_models", {}))
        active_models[str(entry.horizon_min)] = {
            "model_version": entry.model_version,
            "artifact_path": entry.artifact_path,
            "feature_set_version": entry.feature_set_version,
        }
        payload["active_models"] = active_models
        self.save(payload)

    def get_active_model_path(self, horizon_min: int) -> Path | None:
        payload = self.load()
        active_models = payload.get("active_models", {})
        if not isinstance(active_models, dict):
            return None
        entry = active_models.get(str(horizon_min))
        if not isinstance(entry, dict):
            return None
        artifact_path = entry.get("artifact_path")
        if not artifact_path:
            return None
        return Path(str(artifact_path))
