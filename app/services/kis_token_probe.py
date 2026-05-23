"""Sanitized KIS token refresh checks for live readiness."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def probe_kis_token_refresh_check(
    token_manager: Any,
    *,
    mode: str,
    force_refresh: bool = True,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a readiness-compatible token_refresh check without exposing tokens."""

    observed_at = checked_at or datetime.now(timezone.utc)
    try:
        token = token_manager.get_access_token(force_refresh=force_refresh)
    except Exception as exc:  # pragma: no cover - network/client failures vary.
        return {
            "key": "token_refresh",
            "status": "failed",
            "passed": False,
            "summary": "KIS token refresh failed",
            "details": {
                "mode": mode,
                "force_refresh": force_refresh,
                "checked_at": observed_at.isoformat(),
                "error_type": type(exc).__name__,
            },
        }
    expires_at = token.expires_at.astimezone(timezone.utc) if token.expires_at.tzinfo else token.expires_at.replace(tzinfo=timezone.utc)
    seconds_to_expiry = round((expires_at - observed_at.astimezone(timezone.utc)).total_seconds(), 3)
    passed = seconds_to_expiry > 0
    return {
        "key": "token_refresh",
        "status": "ok" if passed else "failed",
        "passed": passed,
        "summary": "KIS token refresh succeeded" if force_refresh else "KIS cached token check succeeded",
        "details": {
            "mode": mode,
            "force_refresh": force_refresh,
            "checked_at": observed_at.isoformat(),
            "token_type": token.token_type,
            "expires_at": expires_at.isoformat(),
            "seconds_to_expiry": seconds_to_expiry,
        },
    }
