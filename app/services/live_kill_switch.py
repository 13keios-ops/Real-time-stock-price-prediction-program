"""Fail-closed live kill switch state for live-order guards."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.storage.contracts import LIVE_ORDER_EVENT_ACTORS


KILL_SWITCH_SCOPES = {"global", "symbol"}


@dataclass(frozen=True, slots=True)
class LiveKillSwitchState:
    enabled: bool
    reason: str
    actor: str
    scope: str
    symbol: str | None
    updated_at: datetime | None
    stale_after: datetime | None
    status: str
    path: str
    raw: dict[str, Any]

    @property
    def healthy(self) -> bool:
        return self.status == "ok"

    @property
    def submit_blocking_reason(self) -> str | None:
        if self.status != "ok":
            return f"kill_switch_state_{self.status}"
        if self.enabled:
            return "kill_switch_enabled"
        return None

    @property
    def blocks_submit(self) -> bool:
        return self.submit_blocking_reason is not None

    @property
    def cancel_only_allowed(self) -> bool:
        return True


class LiveKillSwitch:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def from_runtime_data_dir(cls, runtime_data_dir: Path) -> "LiveKillSwitch":
        return cls(runtime_data_dir / "reports" / "live-risk" / "kill-switch.json")

    def read_state(self, *, now: datetime | None = None) -> LiveKillSwitchState:
        current_time = _as_aware(now or datetime.now(timezone.utc))
        if not self.path.exists():
            return self._fail_closed("missing", "kill switch state file is missing")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return self._fail_closed("broken", "kill switch state payload must be an object")
            state = self._state_from_payload(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._fail_closed("broken", str(exc))
        if state.stale_after is not None and current_time > state.stale_after:
            return LiveKillSwitchState(
                enabled=state.enabled,
                reason=state.reason,
                actor=state.actor,
                scope=state.scope,
                symbol=state.symbol,
                updated_at=state.updated_at,
                stale_after=state.stale_after,
                status="stale",
                path=str(self.path),
                raw=state.raw,
            )
        return state

    def write_state(
        self,
        *,
        enabled: bool,
        reason: str,
        actor: str,
        scope: str = "global",
        symbol: str | None = None,
        now: datetime | None = None,
        stale_after: datetime | None = None,
    ) -> LiveKillSwitchState:
        """Atomically write state; explicit stale_after is preferred, otherwise 24h."""
        current_time = _as_aware(now or datetime.now(timezone.utc))
        resolved_stale_after = _as_aware(stale_after or (current_time + timedelta(days=1)))
        if actor not in LIVE_ORDER_EVENT_ACTORS:
            allowed = ", ".join(sorted(LIVE_ORDER_EVENT_ACTORS))
            raise ValueError(f"actor must be one of: {allowed}")
        if not reason.strip():
            raise ValueError("reason must not be empty")
        if scope not in KILL_SWITCH_SCOPES:
            allowed = ", ".join(sorted(KILL_SWITCH_SCOPES))
            raise ValueError(f"scope must be one of: {allowed}")
        if scope == "symbol" and not (symbol or "").strip():
            raise ValueError("symbol must not be empty for symbol scope")

        payload = {
            "enabled": bool(enabled),
            "reason": reason.strip(),
            "actor": actor,
            "scope": scope,
            "symbol": symbol.strip() if symbol else None,
            "updated_at": current_time.isoformat(),
            "stale_after": resolved_stale_after.isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, self.path)
        return self._state_from_payload(payload)

    def assert_not_stale(self, state: LiveKillSwitchState, *, now: datetime | None = None) -> None:
        current_time = _as_aware(now or datetime.now(timezone.utc))
        if state.stale_after is not None and current_time > state.stale_after:
            raise ValueError("kill switch state is stale")

    def allow_cancel_only(self, state: LiveKillSwitchState) -> bool:
        return state.cancel_only_allowed

    def _state_from_payload(self, payload: dict[str, Any]) -> LiveKillSwitchState:
        required = {"enabled", "reason", "actor", "scope", "updated_at", "stale_after"}
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"kill switch state missing required keys: {', '.join(missing)}")
        actor = str(payload["actor"])
        if actor not in LIVE_ORDER_EVENT_ACTORS:
            allowed = ", ".join(sorted(LIVE_ORDER_EVENT_ACTORS))
            raise ValueError(f"actor must be one of: {allowed}")
        scope = str(payload["scope"])
        if scope not in KILL_SWITCH_SCOPES:
            allowed = ", ".join(sorted(KILL_SWITCH_SCOPES))
            raise ValueError(f"scope must be one of: {allowed}")
        reason = str(payload["reason"]).strip()
        if not reason:
            raise ValueError("reason must not be empty")
        updated_at = _parse_datetime(str(payload["updated_at"]))
        stale_after = _parse_datetime(str(payload["stale_after"]))
        symbol = payload.get("symbol")
        if symbol is not None:
            symbol = str(symbol).strip() or None
        return LiveKillSwitchState(
            enabled=bool(payload["enabled"]),
            reason=reason,
            actor=actor,
            scope=scope,
            symbol=symbol,
            updated_at=updated_at,
            stale_after=stale_after,
            status="ok",
            path=str(self.path),
            raw=dict(payload),
        )

    def _fail_closed(self, status: str, reason: str) -> LiveKillSwitchState:
        return LiveKillSwitchState(
            enabled=True,
            reason=reason,
            actor="system",
            scope="global",
            symbol=None,
            updated_at=None,
            stale_after=None,
            status=status,
            path=str(self.path),
            raw={},
        )


def _parse_datetime(value: str) -> datetime:
    return _as_aware(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
