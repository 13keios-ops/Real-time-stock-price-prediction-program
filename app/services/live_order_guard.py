"""Pure preflight guards for live-order operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.live_kill_switch import LiveKillSwitchState
from app.services.market_status import MarketStatusDecision
from app.services.market_data_freshness import MarketDataFreshnessDecision
from app.services.system_clock import ClockSkewDecision
from app.services.ws_recovery_evidence import is_real_ws_recovery_evidence_type


READONLY_PHASES = {"phase0", "phase0_paper", "phase1", "phase1_readonly", "read_only"}
LIVE_SUBMIT_PHASES = {"phase2", "phase2_conservative", "phase3", "phase3_daily_limits"}
KNOWN_PHASES = READONLY_PHASES | LIVE_SUBMIT_PHASES
PHASE_ALIASES = {
    "phase1_read_only": "phase1_readonly",
    "readonly": "read_only",
}
DEFAULT_ALLOWED_ORDER_TYPES = {"limit"}


@dataclass(frozen=True, slots=True)
class LiveOrderGuardDecision:
    action: str
    allowed: bool
    blocking_reasons: tuple[str, ...]


class LiveOrderGuardError(RuntimeError):
    def __init__(self, action: str, blocking_reasons: tuple[str, ...]) -> None:
        self.action = action
        self.blocking_reasons = blocking_reasons
        super().__init__(f"{action} blocked: {', '.join(blocking_reasons)}")


class LiveOrderGuard:
    @classmethod
    def assert_readonly(cls, settings: Any, phase: str) -> LiveOrderGuardDecision:
        _, reasons = _phase_reasons(phase)
        decision = LiveOrderGuardDecision(
            action="readonly",
            allowed=not reasons,
            blocking_reasons=tuple(reasons),
        )
        return _raise_if_blocked(decision)

    @classmethod
    def assert_can_submit(
        cls,
        settings: Any,
        phase: str,
        profile_mode: str,
        kill_switch_state: LiveKillSwitchState | None,
        *,
        market_status_decision: MarketStatusDecision | None,
        phase_approved: bool,
        order_type: str = "limit",
        allowed_order_types: set[str] | None = None,
        clock_skew_decision: ClockSkewDecision | None = None,
        require_clock_skew_check: bool = False,
        market_data_freshness_decision: MarketDataFreshnessDecision | None = None,
        require_market_data_freshness_check: bool = False,
        ws_recovery_evidence_type: str | None = None,
        require_real_ws_recovery_evidence: bool | None = None,
    ) -> LiveOrderGuardDecision:
        normalized_phase, phase_reasons = _phase_reasons(phase)
        reasons = _live_profile_reasons(settings, profile_mode)
        reasons.extend(phase_reasons)
        if normalized_phase in READONLY_PHASES:
            reasons.append("phase_readonly")
        if not phase_approved:
            reasons.append("phase_not_approved")
        if not bool(getattr(settings, "allow_live_orders", False)):
            reasons.append("live_orders_disabled")

        allowed_types = DEFAULT_ALLOWED_ORDER_TYPES if allowed_order_types is None else allowed_order_types
        if order_type.strip().lower() not in allowed_types:
            reasons.append("order_type_not_allowed")

        if kill_switch_state is None:
            reasons.append("kill_switch_state_missing")
        else:
            blocking_reason = kill_switch_state.submit_blocking_reason
            if blocking_reason:
                reasons.append(blocking_reason)

        if market_status_decision is None:
            reasons.append("market_status_decision_missing")
        elif not market_status_decision.allowed:
            reasons.extend(market_status_decision.blocking_reasons)

        if clock_skew_decision is None:
            if require_clock_skew_check:
                reasons.append("system_clock_check_missing")
        elif not clock_skew_decision.allowed:
            reasons.extend(clock_skew_decision.blocking_reasons or ("system_clock_skew_exceeded",))

        if market_data_freshness_decision is None:
            if require_market_data_freshness_check:
                reasons.append("market_data_freshness_check_missing")
        elif not market_data_freshness_decision.allowed:
            reasons.extend(
                market_data_freshness_decision.blocking_reasons or ("market_data_freshness_stale",)
            )
        if require_real_ws_recovery_evidence is None:
            require_real_ws_recovery_evidence = normalized_phase in LIVE_SUBMIT_PHASES
        if require_real_ws_recovery_evidence:
            if not is_real_ws_recovery_evidence_type(ws_recovery_evidence_type):
                reasons.append("ws_recovery_real_evidence_required")

        decision = LiveOrderGuardDecision(
            action="submit",
            allowed=not reasons,
            blocking_reasons=tuple(_dedupe(reasons)),
        )
        return _raise_if_blocked(decision)

    @classmethod
    def assert_can_cancel(
        cls,
        settings: Any,
        phase: str,
        profile_mode: str,
        kill_switch_state: LiveKillSwitchState | None,
    ) -> LiveOrderGuardDecision:
        _, phase_reasons = _phase_reasons(phase)
        reasons = _live_profile_reasons(settings, profile_mode)
        reasons.extend(phase_reasons)
        if kill_switch_state is not None and not kill_switch_state.cancel_only_allowed:
            reasons.append("cancel_only_not_allowed")
        decision = LiveOrderGuardDecision(
            action="cancel",
            allowed=not reasons,
            blocking_reasons=tuple(_dedupe(reasons)),
        )
        return _raise_if_blocked(decision)


def _live_profile_reasons(settings: Any, profile_mode: str) -> list[str]:
    reasons: list[str] = []
    if str(getattr(settings, "trading_mode", "")).strip().lower() != "live":
        reasons.append("trading_mode_not_live")
    if profile_mode.strip().lower() != "live":
        reasons.append("profile_mode_not_live")
    return reasons


def _normalize_phase(phase: str) -> str:
    normalized = re.sub(r"[\s-]+", "_", phase.strip().lower())
    normalized = re.sub(r"_+", "_", normalized)
    return PHASE_ALIASES.get(normalized, normalized)


def _phase_reasons(phase: str) -> tuple[str, list[str]]:
    normalized_phase = _normalize_phase(phase)
    if not normalized_phase:
        return normalized_phase, ["phase_missing"]
    if normalized_phase not in KNOWN_PHASES:
        return normalized_phase, ["phase_unknown"]
    return normalized_phase, []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _raise_if_blocked(decision: LiveOrderGuardDecision) -> LiveOrderGuardDecision:
    if not decision.allowed:
        raise LiveOrderGuardError(decision.action, decision.blocking_reasons)
    return decision
