"""Codex CLI ops job manifests and permission checks.

This module does not call Codex CLI. It only decides whether a future
Codex ops job is allowed to request a specific action in the current
market/runtime context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROTECTED_SESSION_STATUSES = {
    "pre-open",
    "pre_open",
    "regular",
    "regular-session",
    "regular_session",
}
CODEX_OPS_REPORT_ROOT = Path("runtime-data/reports/codex/ops")
CODEX_OPS_PATCH_DRAFT_ROOT = Path(".tmp-tests/codex-ops")
DEFAULT_DISK_WARN_FREE_BYTES = 10 * 1024 * 1024 * 1024
DEFAULT_DISK_BLOCK_FREE_BYTES = 5 * 1024 * 1024 * 1024


ACTION_READ_STATUS = "read_status"
ACTION_WRITE_REPORT = "write_report"
ACTION_CREATE_COWORK_REPORT = "create_cowork_report"
ACTION_RUN_DIFF_CHECK = "run_git_diff_check"
ACTION_RUN_BASH_PARSE_CHECK = "run_bash_parse_check"
ACTION_RUN_ISOLATED_UNIT_TEST = "run_isolated_unit_test"
ACTION_RUN_FULL_TEST = "run_full_test"
ACTION_RUN_APP_READONLY_REPORT = "run_python_app_readonly_report"
ACTION_RUN_SNAPSHOT_RESEARCH = "run_snapshot_research"
ACTION_RUN_STORAGE_MIGRATION_PLAN = "run_storage_migration_plan"
ACTION_RUN_STORAGE_MIGRATION_APPLY = "run_storage_migration_apply"
ACTION_CREATE_PATCH_DRAFT = "create_patch_draft"
ACTION_APPLY_PATCH_TO_ROOT = "apply_patch_to_root"
ACTION_RESTART_DASHBOARD = "restart_dashboard"
ACTION_RESTART_LIVE_RUNTIME = "restart_live_runtime"
ACTION_CHANGE_LIVE_FLAG = "change_live_flag"
ACTION_CHANGE_GATE_THRESHOLD = "change_gate_threshold"
ACTION_SEND_LIVE_ORDER = "send_live_order"


ALL_ACTIONS = {
    ACTION_READ_STATUS,
    ACTION_WRITE_REPORT,
    ACTION_CREATE_COWORK_REPORT,
    ACTION_RUN_DIFF_CHECK,
    ACTION_RUN_BASH_PARSE_CHECK,
    ACTION_RUN_ISOLATED_UNIT_TEST,
    ACTION_RUN_FULL_TEST,
    ACTION_RUN_APP_READONLY_REPORT,
    ACTION_RUN_SNAPSHOT_RESEARCH,
    ACTION_RUN_STORAGE_MIGRATION_PLAN,
    ACTION_RUN_STORAGE_MIGRATION_APPLY,
    ACTION_CREATE_PATCH_DRAFT,
    ACTION_APPLY_PATCH_TO_ROOT,
    ACTION_RESTART_DASHBOARD,
    ACTION_RESTART_LIVE_RUNTIME,
    ACTION_CHANGE_LIVE_FLAG,
    ACTION_CHANGE_GATE_THRESHOLD,
    ACTION_SEND_LIVE_ORDER,
}

NEVER_AUTOMATED_ACTIONS = {
    ACTION_RUN_STORAGE_MIGRATION_APPLY,
    ACTION_APPLY_PATCH_TO_ROOT,
    ACTION_RESTART_DASHBOARD,
    ACTION_RESTART_LIVE_RUNTIME,
    ACTION_CHANGE_LIVE_FLAG,
    ACTION_CHANGE_GATE_THRESHOLD,
    ACTION_SEND_LIVE_ORDER,
}

PROTECTED_SESSION_ALLOWED_ACTIONS = {
    ACTION_READ_STATUS,
    ACTION_WRITE_REPORT,
    ACTION_CREATE_COWORK_REPORT,
    ACTION_RUN_DIFF_CHECK,
    ACTION_RUN_BASH_PARSE_CHECK,
    ACTION_RUN_ISOLATED_UNIT_TEST,
    ACTION_CREATE_PATCH_DRAFT,
    ACTION_RUN_STORAGE_MIGRATION_PLAN,
}

JOB_PREMARKET_READINESS = "premarket-readiness"
JOB_POSTCLOSE_RESEARCH = "postclose-research"
JOB_INTRADAY_INCIDENT_TRIAGE = "intraday-incident-triage"
JOB_POSTCLOSE_MAINTENANCE_REVIEW = "postclose-maintenance-review"
JOB_COWORK_HANDOFF = "cowork-handoff"

PREMARKET_READINESS_CHECK_KEYS = (
    "live_runtime",
    "runtime_watchdog",
    "dashboard",
    "kis_credentials",
    "database",
    "storage_migration_state",
    "disk_space",
    "manifest_policy",
)


@dataclass(frozen=True, slots=True)
class CodexOpsManifest:
    job_type: str
    description: str
    allowed_actions: frozenset[str]
    report_subdir: str
    include_reports_in_backup: bool
    include_patch_drafts_in_backup: bool
    patch_drafts_allowed: bool = False


@dataclass(frozen=True, slots=True)
class CodexOpsContext:
    session_status: str
    live_runtime_should_run: bool = False
    live_runtime_running: bool = False


@dataclass(frozen=True, slots=True)
class CodexOpsDecision:
    allowed: bool
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CodexOpsCheck:
    key: str
    status: str
    severity: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


MANIFESTS: dict[str, CodexOpsManifest] = {
    JOB_PREMARKET_READINESS: CodexOpsManifest(
        job_type=JOB_PREMARKET_READINESS,
        description="Create a premarket readiness report from existing status files.",
        allowed_actions=frozenset(
            {
                ACTION_READ_STATUS,
                ACTION_WRITE_REPORT,
                ACTION_RUN_DIFF_CHECK,
                ACTION_RUN_BASH_PARSE_CHECK,
                ACTION_RUN_ISOLATED_UNIT_TEST,
                ACTION_RUN_STORAGE_MIGRATION_PLAN,
            }
        ),
        report_subdir=JOB_PREMARKET_READINESS,
        include_reports_in_backup=True,
        include_patch_drafts_in_backup=False,
    ),
    JOB_POSTCLOSE_RESEARCH: CodexOpsManifest(
        job_type=JOB_POSTCLOSE_RESEARCH,
        description="Run post-close research only against isolated research snapshots.",
        allowed_actions=frozenset(
            {
                ACTION_READ_STATUS,
                ACTION_WRITE_REPORT,
                ACTION_RUN_DIFF_CHECK,
                ACTION_RUN_BASH_PARSE_CHECK,
                ACTION_RUN_ISOLATED_UNIT_TEST,
                ACTION_RUN_FULL_TEST,
                ACTION_RUN_APP_READONLY_REPORT,
                ACTION_RUN_SNAPSHOT_RESEARCH,
                ACTION_RUN_STORAGE_MIGRATION_PLAN,
            }
        ),
        report_subdir=JOB_POSTCLOSE_RESEARCH,
        include_reports_in_backup=True,
        include_patch_drafts_in_backup=False,
    ),
    JOB_INTRADAY_INCIDENT_TRIAGE: CodexOpsManifest(
        job_type=JOB_INTRADAY_INCIDENT_TRIAGE,
        description="Analyze an intraday incident and optionally draft an isolated patch.",
        allowed_actions=frozenset(
            {
                ACTION_READ_STATUS,
                ACTION_WRITE_REPORT,
                ACTION_RUN_DIFF_CHECK,
                ACTION_RUN_BASH_PARSE_CHECK,
                ACTION_RUN_ISOLATED_UNIT_TEST,
                ACTION_CREATE_PATCH_DRAFT,
            }
        ),
        report_subdir=JOB_INTRADAY_INCIDENT_TRIAGE,
        include_reports_in_backup=True,
        include_patch_drafts_in_backup=False,
        patch_drafts_allowed=True,
    ),
    JOB_POSTCLOSE_MAINTENANCE_REVIEW: CodexOpsManifest(
        job_type=JOB_POSTCLOSE_MAINTENANCE_REVIEW,
        description="Summarize post-close maintenance status and stale reports.",
        allowed_actions=frozenset(
            {
                ACTION_READ_STATUS,
                ACTION_WRITE_REPORT,
                ACTION_RUN_DIFF_CHECK,
                ACTION_RUN_BASH_PARSE_CHECK,
                ACTION_RUN_ISOLATED_UNIT_TEST,
            }
        ),
        report_subdir=JOB_POSTCLOSE_MAINTENANCE_REVIEW,
        include_reports_in_backup=True,
        include_patch_drafts_in_backup=False,
    ),
    JOB_COWORK_HANDOFF: CodexOpsManifest(
        job_type=JOB_COWORK_HANDOFF,
        description="Create a concise handoff report for cowork review.",
        allowed_actions=frozenset(
            {
                ACTION_READ_STATUS,
                ACTION_WRITE_REPORT,
                ACTION_CREATE_COWORK_REPORT,
                ACTION_RUN_DIFF_CHECK,
                ACTION_RUN_BASH_PARSE_CHECK,
            }
        ),
        report_subdir=JOB_COWORK_HANDOFF,
        include_reports_in_backup=True,
        include_patch_drafts_in_backup=False,
    ),
}


def get_manifest(job_type: str) -> CodexOpsManifest:
    try:
        return MANIFESTS[job_type]
    except KeyError as exc:
        raise ValueError(f"unknown codex ops job type: {job_type}") from exc


def is_protected_session(context: CodexOpsContext) -> bool:
    normalized_status = context.session_status.strip().lower()
    return (
        normalized_status in PROTECTED_SESSION_STATUSES
        or context.live_runtime_should_run
        or context.live_runtime_running
    )


def evaluate_action(
    job_type: str,
    action: str,
    context: CodexOpsContext,
    *,
    target_path: Path | None = None,
) -> CodexOpsDecision:
    reasons: list[str] = []
    manifest = get_manifest(job_type)
    if action not in ALL_ACTIONS:
        reasons.append("action_unknown")
    if action not in manifest.allowed_actions:
        reasons.append("action_not_allowed_for_job")
    if action in NEVER_AUTOMATED_ACTIONS:
        reasons.append("action_requires_operator_approval")
    if is_protected_session(context) and action not in PROTECTED_SESSION_ALLOWED_ACTIONS:
        reasons.append("action_not_allowed_during_protected_session")
    if action == ACTION_CREATE_PATCH_DRAFT and not manifest.patch_drafts_allowed:
        reasons.append("patch_draft_not_allowed_for_job")
    if target_path is not None:
        reasons.extend(_path_reasons(action, manifest, target_path))
    return CodexOpsDecision(allowed=not reasons, blocking_reasons=tuple(_dedupe(reasons)))


def report_root_for_job(job_type: str) -> Path:
    manifest = get_manifest(job_type)
    return CODEX_OPS_REPORT_ROOT / manifest.report_subdir


def is_cleanup_protected_path(path: Path) -> bool:
    return _is_relative_to(path, CODEX_OPS_PATCH_DRAFT_ROOT)


def backup_policy_for_job(job_type: str) -> dict[str, object]:
    manifest = get_manifest(job_type)
    included: list[str] = []
    excluded: list[str] = []
    if manifest.include_reports_in_backup:
        included.append(str(report_root_for_job(job_type)))
    else:
        excluded.append(str(report_root_for_job(job_type)))
    if manifest.include_patch_drafts_in_backup:
        included.append(str(CODEX_OPS_PATCH_DRAFT_ROOT))
    else:
        excluded.append(str(CODEX_OPS_PATCH_DRAFT_ROOT))
    return {
        "job_type": job_type,
        "include": included,
        "exclude": excluded,
    }


def build_premarket_readiness_report(
    *,
    context: CodexOpsContext,
    live_runtime_status: dict[str, Any],
    watchdog_status: dict[str, Any],
    dashboard_status: dict[str, Any] | None = None,
    database_smoke: dict[str, Any] | None = None,
    storage_migration_state: dict[str, Any] | None = None,
    disk_free_bytes: int | None = None,
    generated_at: str,
    workspace_root: str,
    report_path: str | None = None,
) -> dict[str, Any]:
    checks = [
        _check_live_runtime(context, live_runtime_status),
        _check_runtime_watchdog(context, watchdog_status),
        _check_dashboard(dashboard_status or {}),
        _check_kis_credentials(live_runtime_status),
        _check_database_smoke(database_smoke or {}),
        _check_storage_migration_state(storage_migration_state or {}),
        _check_disk_space(disk_free_bytes),
        _check_manifest_policy(context),
    ]
    blockers = [check.key for check in checks if check.severity == "blocker"]
    warnings = [check.key for check in checks if check.severity == "warning"]
    status = "blocked" if blockers else "watch" if warnings else "ok"
    return {
        "job_type": JOB_PREMARKET_READINESS,
        "status": status,
        "generated_at": generated_at,
        "workspace_root": workspace_root,
        "report_path": report_path,
        "session_status": context.session_status,
        "protected_session": is_protected_session(context),
        "live_runtime_should_run": context.live_runtime_should_run,
        "live_runtime_running": context.live_runtime_running,
        "checks": [_check_to_dict(check) for check in checks],
        "blockers": blockers,
        "warnings": warnings,
        "backup_policy": backup_policy_for_job(JOB_PREMARKET_READINESS),
        "schema_version": 1,
    }


def _check_live_runtime(context: CodexOpsContext, payload: dict[str, Any]) -> CodexOpsCheck:
    status = str(payload.get("status", "unknown"))
    should_run = context.live_runtime_should_run
    running = context.live_runtime_running
    if should_run and not running:
        return CodexOpsCheck(
            key="live_runtime",
            status="blocked",
            severity="blocker",
            summary="live runtime should run but is not running",
            details={"status": status, "live_runtime_should_run": should_run, "running": running},
        )
    if not should_run and running:
        return CodexOpsCheck(
            key="live_runtime",
            status="watch",
            severity="warning",
            summary="live runtime is running outside the expected live window",
            details={"status": status, "live_runtime_should_run": should_run, "running": running},
        )
    return CodexOpsCheck(
        key="live_runtime",
        status="ok",
        severity="info",
        summary="live runtime state matches the expected session window",
        details={"status": status, "live_runtime_should_run": should_run, "running": running},
    )


def _check_runtime_watchdog(context: CodexOpsContext, payload: dict[str, Any]) -> CodexOpsCheck:
    status = str(payload.get("status", "unknown"))
    running = bool(payload.get("process_running")) or status == "running"
    stale = bool(payload.get("heartbeat_stale"))
    if context.live_runtime_should_run and (not running or stale):
        return CodexOpsCheck(
            key="runtime_watchdog",
            status="blocked",
            severity="blocker",
            summary="runtime watchdog is not healthy during the live window",
            details={"status": status, "running": running, "heartbeat_stale": stale},
        )
    if not running or stale:
        return CodexOpsCheck(
            key="runtime_watchdog",
            status="watch",
            severity="warning",
            summary="runtime watchdog needs attention before the next live window",
            details={"status": status, "running": running, "heartbeat_stale": stale},
        )
    return CodexOpsCheck(
        key="runtime_watchdog",
        status="ok",
        severity="info",
        summary="runtime watchdog is running",
        details={"status": status, "running": running, "heartbeat_stale": stale},
    )


def _check_dashboard(payload: dict[str, Any]) -> CodexOpsCheck:
    if not payload:
        return CodexOpsCheck(
            key="dashboard",
            status="unknown",
            severity="warning",
            summary="dashboard status was not provided",
        )
    status = str(payload.get("status", "unknown"))
    running = bool(payload.get("process_running")) or status in {"running", "ok"}
    severity = "info" if running else "warning"
    return CodexOpsCheck(
        key="dashboard",
        status="ok" if running else "watch",
        severity=severity,
        summary="dashboard is reachable" if running else "dashboard is not confirmed healthy",
        details={"status": status, "running": running},
    )


def _check_kis_credentials(payload: dict[str, Any]) -> CodexOpsCheck:
    env_ready = bool(payload.get("env_file_exists", True))
    quote_ready = bool(payload.get("credentials_ready_for_quotes"))
    if not env_ready or not quote_ready:
        return CodexOpsCheck(
            key="kis_credentials",
            status="blocked",
            severity="blocker",
            summary="KIS quote credentials are not ready",
            details={"env_file_exists": env_ready, "credentials_ready_for_quotes": quote_ready},
        )
    return CodexOpsCheck(
        key="kis_credentials",
        status="ok",
        severity="info",
        summary="KIS quote credentials are ready",
        details={"env_file_exists": env_ready, "credentials_ready_for_quotes": quote_ready},
    )


def _check_storage_migration_state(payload: dict[str, Any]) -> CodexOpsCheck:
    if not payload:
        return CodexOpsCheck(
            key="storage_migration_state",
            status="unknown",
            severity="warning",
            summary="storage migration state report was not found",
        )
    status = str(payload.get("status", "unknown"))
    if status in {"ok", "planned"}:
        return CodexOpsCheck(
            key="storage_migration_state",
            status="ok",
            severity="info",
            summary="storage migration state is acceptable",
            details={"status": status, "apply": payload.get("apply")},
        )
    return CodexOpsCheck(
        key="storage_migration_state",
        status="watch",
        severity="warning",
        summary="storage migration state needs review",
        details={"status": status, "apply": payload.get("apply")},
    )


def _check_database_smoke(payload: dict[str, Any]) -> CodexOpsCheck:
    if not payload:
        return CodexOpsCheck(
            key="database",
            status="unknown",
            severity="warning",
            summary="database smoke result was not provided",
        )
    status = str(payload.get("status", "unknown"))
    details = dict(payload)
    if status == "ok":
        return CodexOpsCheck(
            key="database",
            status="ok",
            severity="info",
            summary="SQLite read-only smoke check passed",
            details=details,
        )
    if status in {"missing", "unknown"}:
        return CodexOpsCheck(
            key="database",
            status="unknown",
            severity="warning",
            summary="SQLite database smoke check was not completed",
            details=details,
        )
    return CodexOpsCheck(
        key="database",
        status="blocked",
        severity="blocker",
        summary="SQLite read-only smoke check failed",
        details=details,
    )


def _check_disk_space(disk_free_bytes: int | None) -> CodexOpsCheck:
    if disk_free_bytes is None:
        return CodexOpsCheck(
            key="disk_space",
            status="unknown",
            severity="warning",
            summary="disk free space was not provided",
        )
    details = {
        "free_bytes": disk_free_bytes,
        "warn_below_bytes": DEFAULT_DISK_WARN_FREE_BYTES,
        "block_below_bytes": DEFAULT_DISK_BLOCK_FREE_BYTES,
    }
    if disk_free_bytes < DEFAULT_DISK_BLOCK_FREE_BYTES:
        return CodexOpsCheck(
            key="disk_space",
            status="blocked",
            severity="blocker",
            summary="disk free space is below the block threshold",
            details=details,
        )
    if disk_free_bytes < DEFAULT_DISK_WARN_FREE_BYTES:
        return CodexOpsCheck(
            key="disk_space",
            status="watch",
            severity="warning",
            summary="disk free space is below the warning threshold",
            details=details,
        )
    return CodexOpsCheck(
        key="disk_space",
        status="ok",
        severity="info",
        summary="disk free space is above the warning threshold",
        details=details,
    )


def _check_manifest_policy(context: CodexOpsContext) -> CodexOpsCheck:
    report_decision = evaluate_action(JOB_PREMARKET_READINESS, ACTION_WRITE_REPORT, context)
    apply_decision = evaluate_action(JOB_PREMARKET_READINESS, ACTION_RUN_STORAGE_MIGRATION_APPLY, context)
    dangerous_blocked = not apply_decision.allowed and "action_requires_operator_approval" in apply_decision.blocking_reasons
    if report_decision.allowed and dangerous_blocked:
        return CodexOpsCheck(
            key="manifest_policy",
            status="ok",
            severity="info",
            summary="premarket report is allowed and storage apply is blocked",
            details={
                "write_report_allowed": report_decision.allowed,
                "storage_apply_allowed": apply_decision.allowed,
                "storage_apply_blocking_reasons": list(apply_decision.blocking_reasons),
            },
        )
    return CodexOpsCheck(
        key="manifest_policy",
        status="blocked",
        severity="blocker",
        summary="codex ops manifest policy is not safe for premarket readiness",
        details={
            "write_report_allowed": report_decision.allowed,
            "write_report_blocking_reasons": list(report_decision.blocking_reasons),
            "storage_apply_allowed": apply_decision.allowed,
            "storage_apply_blocking_reasons": list(apply_decision.blocking_reasons),
        },
    )


def _path_reasons(action: str, manifest: CodexOpsManifest, target_path: Path) -> list[str]:
    reasons: list[str] = []
    if action == ACTION_CREATE_PATCH_DRAFT and not _is_relative_to(target_path, CODEX_OPS_PATCH_DRAFT_ROOT):
        reasons.append("patch_draft_path_outside_codex_ops")
    if action == ACTION_WRITE_REPORT and not _is_relative_to(target_path, report_root_for_job(manifest.job_type)):
        reasons.append("report_path_outside_job_root")
    if action == ACTION_CREATE_COWORK_REPORT and not _is_relative_to(target_path, Path("docs/cowork-reports")):
        reasons.append("cowork_report_path_outside_docs_cowork_reports")
    return reasons


def _check_to_dict(check: CodexOpsCheck) -> dict[str, Any]:
    return {
        "key": check.key,
        "status": check.status,
        "severity": check.severity,
        "summary": check.summary,
        "details": check.details,
    }


def _is_relative_to(path: Path, base: Path) -> bool:
    normalized_path = Path(path)
    normalized_base = Path(base)
    try:
        normalized_path.relative_to(normalized_base)
        return True
    except ValueError:
        return normalized_path == normalized_base


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
