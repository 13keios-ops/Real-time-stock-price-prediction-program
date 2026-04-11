"""Helpers for label threshold decisions."""

from __future__ import annotations


def classify_return(move_pct: float, threshold_pct: float) -> str:
    if move_pct >= threshold_pct:
        return "up"
    if move_pct <= -threshold_pct:
        return "down"
    return "flat"
