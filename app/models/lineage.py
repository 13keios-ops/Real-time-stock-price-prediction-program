"""Deterministic prediction lineage helpers for built-in and JSON models."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def deterministic_model_lineage(
    *,
    model_kind: str,
    model_version: str,
    payload: dict[str, Any],
) -> tuple[str, str, str]:
    artifact_sha256 = canonical_payload_sha256(
        {
            "model_kind": model_kind,
            "model_version": model_version,
            "payload": payload,
        }
    )
    suffix = artifact_sha256[:16]
    return (
        f"builtin:{model_version}:{suffix}",
        f"{model_kind}:{model_version}:{suffix}",
        artifact_sha256,
    )