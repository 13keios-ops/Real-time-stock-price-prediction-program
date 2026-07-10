"""Model registry helpers for selecting active runtime artifacts."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any
import uuid


@dataclass(slots=True)
class ModelRegistryEntry:
    horizon_min: int
    model_version: str
    artifact_path: str
    feature_set_version: str
    model_kind: str = "centroid_artifact"
    builtin_name: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class ActiveModelSelection:
    horizon_min: int
    model_version: str
    artifact_path: str | None
    feature_set_version: str
    model_kind: str
    builtin_name: str | None = None
    metadata: dict[str, Any] | None = None


class ModelRegistry:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.registry_path = runtime_root / "ml" / "registry.json"
        self.history_dir = runtime_root / "ml" / "registry-history"
        self.lock_path = runtime_root / "ml" / ".registry.lock"

    def load(self) -> dict[str, object]:
        if not self.registry_path.exists():
            return {"active_models": {}}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def save(self, payload: dict[str, object]) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self._atomic_write(self.registry_path, serialized)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        history_path = self.history_dir / f"{timestamp}-{uuid.uuid4().hex}.json"
        self._atomic_write(history_path, serialized)
        self._prune_history(max_files=100)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary_path.open("x", encoding="utf-8") as destination:
                destination.write(content)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _prune_history(self, max_files: int) -> None:
        history_files = sorted(self.history_dir.glob("*.json"), key=lambda path: path.name, reverse=True)
        for path in history_files[max_files:]:
            path.unlink(missing_ok=True)

    @contextmanager
    def _exclusive_lock(self, timeout_seconds: float = 5.0):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(descriptor, str(os.getpid()).encode("ascii"))
            except FileExistsError:
                owner_pid: int | None = None
                try:
                    owner_pid = int(self.lock_path.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    pass
                owner_alive = False
                if owner_pid is not None:
                    try:
                        os.kill(owner_pid, 0)
                        owner_alive = True
                    except ProcessLookupError:
                        owner_alive = False
                    except PermissionError:
                        owner_alive = True
                try:
                    stale = time.time() - self.lock_path.stat().st_mtime > 30.0
                except FileNotFoundError:
                    continue
                if stale and not owner_alive:
                    self.lock_path.unlink(missing_ok=True)
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for model registry lock: {self.lock_path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            os.close(descriptor)
            self.lock_path.unlink(missing_ok=True)

    def set_active_model(self, entry: ModelRegistryEntry) -> None:
        with self._exclusive_lock():
            payload = self.load()
            active_models = dict(payload.get("active_models", {}))
            active_models[str(entry.horizon_min)] = {
                "model_version": entry.model_version,
                "artifact_path": entry.artifact_path,
                "feature_set_version": entry.feature_set_version,
                "model_kind": entry.model_kind,
                "builtin_name": entry.builtin_name,
                "metadata": entry.metadata or {},
            }
            payload["active_models"] = active_models
            self.save(payload)

    def get_active_model_entry(self, horizon_min: int) -> ActiveModelSelection | None:
        payload = self.load()
        active_models = payload.get("active_models", {})
        if not isinstance(active_models, dict):
            return None
        entry = active_models.get(str(horizon_min))
        if not isinstance(entry, dict):
            return None
        model_version = entry.get("model_version")
        feature_set_version = entry.get("feature_set_version")
        if not model_version or not feature_set_version:
            return None
        artifact_path = entry.get("artifact_path")
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        return ActiveModelSelection(
            horizon_min=horizon_min,
            model_version=str(model_version),
            artifact_path=str(artifact_path) if artifact_path else None,
            feature_set_version=str(feature_set_version),
            model_kind=str(entry.get("model_kind") or "centroid_artifact"),
            builtin_name=str(entry.get("builtin_name")) if entry.get("builtin_name") else None,
            metadata=metadata,
        )

    def get_active_model_path(self, horizon_min: int) -> Path | None:
        entry = self.get_active_model_entry(horizon_min)
        if entry is None or not entry.artifact_path:
            return None
        return Path(entry.artifact_path)
