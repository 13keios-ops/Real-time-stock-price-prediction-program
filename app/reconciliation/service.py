"""Placeholder reconciliation services."""

from __future__ import annotations

from datetime import datetime

from app.storage.contracts import ReconciliationRun


def build_placeholder_reconciliation_run(as_of: datetime, has_order: bool, reconciliation_id: str) -> ReconciliationRun:
    return ReconciliationRun(
        reconciliation_id=reconciliation_id,
        as_of=as_of,
        status="completed",
        mismatch_count=0 if has_order else 1,
    )
