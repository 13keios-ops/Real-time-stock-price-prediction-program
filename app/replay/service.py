"""Placeholder replay services."""

from __future__ import annotations

from datetime import datetime

from app.storage.contracts import ReplayRun


def build_placeholder_replay_run(as_of: datetime, replay_id: str) -> ReplayRun:
    return ReplayRun(
        replay_id=replay_id,
        as_of=as_of,
        status="completed",
        drift_count=0,
    )
