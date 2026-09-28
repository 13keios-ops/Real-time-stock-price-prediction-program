#!/usr/bin/env python3
"""Post-close paper/KIS mismatch recheck wrapper.

This wrapper is intentionally conservative: it refuses to run during pre-open,
regular-session, weekend/holiday, or while live runtime is running unless
explicitly overridden. It performs no alignment and sends no orders. The default
flow refreshes broker paper order/fill sync, refreshes paper/account
reconciliation, then rebuilds the read-only mismatch trace report.
Dry-run and blocked attempts are written to a separate attempt report so they
cannot replace the latest completed operational evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
import math
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = Path("runtime-data/reports/reconciliation/latest-paper-kis-mismatch-recheck.json")
DEFAULT_ATTEMPT_OUTPUT_PATH = Path(
    "runtime-data/reports/reconciliation/latest-paper-kis-mismatch-recheck-attempt.json"
)
DEFAULT_TRACE_PATH = Path("runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.json")
DEFAULT_ACCOUNT_PATH = Path("runtime-data/reports/reconciliation/latest-paper-account-sync.json")
DEFAULT_BROKER_PATH = Path("runtime-data/reports/broker-paper/latest-sync.json")
DEFAULT_HISTORY_PATH = Path("runtime-data/reports/reconciliation/latest-paper-account-history.json")
PROTECTED_SESSION_STATUSES = {"pre-open", "regular-session"}
NON_TRADING_DAY_STATUSES = {"weekend", "holiday"}


def choose_default_output_path(
    *,
    dry_run: bool,
    protected_blocked: bool,
    non_trading_blocked: bool,
) -> Path:
    if dry_run or protected_blocked or non_trading_blocked:
        return DEFAULT_ATTEMPT_OUTPUT_PATH
    return DEFAULT_OUTPUT_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--output-path")
    parser.add_argument("--limit-per-table", type=int, default=12)
    parser.add_argument("--allow-protected-session", action="store_true")
    parser.add_argument("--allow-non-trading-day", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--diagnose-only", action="store_true", help="Use existing evidence without KIS calls or accounting writes")
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).expanduser().resolve()
    generated_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="microseconds")
    trade_date = generated_at[:10]
    runtime_status = load_live_runtime_status(project_root)
    planned_commands = build_command_plan(project_root, limit_per_table=args.limit_per_table)
    history = load_json(project_root / DEFAULT_HISTORY_PATH)
    eligible_today = any(
        isinstance(day, dict) and day.get("trade_date") == trade_date
        and day.get("eligible_for_phase0_gate") is True
        for day in history.get("days", [])
    )
    diagnose_only = args.diagnose_only or eligible_today
    if diagnose_only:
        planned_commands = planned_commands[-1:]
    protected_blocked = is_protected_runtime_status(runtime_status) and not args.allow_protected_session
    non_trading_blocked = is_non_trading_day_status(runtime_status) and not args.allow_non_trading_day
    default_output = choose_default_output_path(
        dry_run=args.dry_run,
        protected_blocked=protected_blocked,
        non_trading_blocked=non_trading_blocked,
    )
    output_path = _resolve_inside_repo(str(args.output_path or default_output), project_root, "output_path")

    if protected_blocked:
        payload = {
            "status": "blocked",
            "mode": "attempt",
            "generated_at": generated_at,
            "summary": "paper/KIS mismatch recheck blocked during protected runtime session",
            "runtime_status": runtime_status,
            "planned_commands": [display_command(command, project_root) for command in planned_commands],
            "blocking_reasons": ["protected_runtime_session"],
            "dry_run": args.dry_run,
        }
        write_json(output_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    if non_trading_blocked:
        payload = {
            "status": "blocked",
            "generated_at": generated_at,
            "mode": "attempt",
            "summary": "paper/KIS mismatch recheck blocked on non-trading day; wait for next trading-day post-close",
            "runtime_status": runtime_status,
            "planned_commands": [display_command(command, project_root) for command in planned_commands],
            "blocking_reasons": ["non_trading_day"],
            "dry_run": args.dry_run,
        }
        write_json(output_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    if args.dry_run:
        payload = {
            "status": "dry_run",
            "generated_at": generated_at,
            "mode": "attempt",
            "summary": "paper/KIS mismatch recheck command plan only",
            "runtime_status": runtime_status,
            "planned_commands": [display_command(command, project_root) for command in planned_commands],
            "blocking_reasons": [],
            "dry_run": True,
        }
        write_json(output_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    steps: list[dict[str, Any]] = []
    status = "ok"
    for name, command in planned_commands:
        result = run_step(name, command, project_root)
        steps.append(result)
        if result["returncode"] != 0:
            status = "failed"
            break

    trace_path = project_root / DEFAULT_TRACE_PATH
    trace_summary: dict[str, Any] = {}
    if trace_path.exists():
        trace_summary = summarize_trace_payload(load_json(trace_path))
    elif status == "ok":
        status = "failed"
        trace_summary = {"status": "missing", "path": str(DEFAULT_TRACE_PATH)}

    step_ok = {step["name"]: step["returncode"] == 0 for step in steps}
    remediation = build_remediation_diagnosis(
        load_json(project_root / DEFAULT_ACCOUNT_PATH),
        load_json(project_root / DEFAULT_BROKER_PATH), load_json(trace_path),
        trade_date=trade_date, sync_attempted=not diagnose_only,
        sync_completed=step_ok.get("sync_broker_paper_orders", False),
        reconciliation_completed=step_ok.get("reconcile_paper_accounts", False),
        trace_completed=step_ok.get("trace_paper_kis_mismatch", False),
        execution_started_at=generated_at,
    )
    execution_status = status
    if remediation["status"] not in {"aligned", "aligned_with_tolerated_gaps", "no_submission_observation"}:
        status = "failed" if execution_status == "failed" else "needs_review"

    payload = {
        "status": status,
        "generated_at": generated_at,
        "mode": "diagnose_existing_evidence" if diagnose_only else "executed_recheck",
        "execution_status": execution_status,
        "summary": "paper/KIS post-close diagnosis: " + remediation["status"],
        "remediation": remediation,
        "runtime_status": runtime_status,
        "steps": steps,
        "trace_report_path": str(DEFAULT_TRACE_PATH),
        "trace_summary": trace_summary,
        "blocking_reasons": remediation["evidence_blocking_reasons"],
        "dry_run": False,
        "safety": {
            "alignment_applied": False,
            "broker_calls_skipped": diagnose_only,
            "orders_sent": False,
            "live_orders_enabled_changed": False,
        },
    }
    write_json(output_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == "ok" else 1


def build_command_plan(project_root: Path, *, limit_per_table: int) -> list[tuple[str, list[str]]]:
    python = sys.executable
    return [
        ("sync_broker_paper_orders", [python, "-m", "app", "--sync-broker-paper-orders", "--broker-sync-confirmed-only"]),
        ("reconcile_paper_accounts", [python, "-m", "app", "--reconcile-paper-accounts", "--require-fresh-broker-account"]),
        (
            "trace_paper_kis_mismatch",
            [python, "scripts/trace_paper_kis_mismatch.py", "--limit-per-table", str(limit_per_table)],
        ),
    ]


def is_protected_runtime_status(status: dict[str, Any]) -> bool:
    session_status = str(status.get("current_session_status") or status.get("session_status") or "").strip()
    if not session_status or status.get("status_command_returncode", 0) != 0:
        return True
    if session_status in PROTECTED_SESSION_STATUSES:
        return True
    if bool(status.get("process_running")):
        return True
    if bool(status.get("live_runtime_should_run")):
        return True
    return False


def _evidence_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(ZoneInfo("Asia/Seoul"))
    except (ValueError, TypeError):
        return None


def build_remediation_diagnosis(
    account: dict[str, Any], broker: dict[str, Any], trace: dict[str, Any], *,
    trade_date: str, sync_completed: bool, trace_completed: bool, sync_attempted: bool,
    execution_started_at: str | None = None,
    reconciliation_completed: bool = True,
) -> dict[str, Any]:
    """Separate observed discrepancies from unproven causes; never synthesize accounting."""
    comparison = account.get("comparison") or {}
    blockers: list[str] = []
    account_time = _evidence_time(account.get("as_of"))
    broker_time = _evidence_time(broker.get("synced_at"))
    trace_time = _evidence_time(trace.get("generated_at"))
    start_time = _evidence_time(execution_started_at)
    fetch_time = _evidence_time(comparison.get("latest_broker_fetch_time"))
    if (not account_time or account_time.date().isoformat() != trade_date
            or account.get("market_session_status") != "post-close"
            or not trace_completed or not trace_time or not account_time
            or trace_time.date().isoformat() != trade_date
            or trace_time.replace(microsecond=0) < account_time.replace(microsecond=0)):
        blockers.append("stale_or_missing_account_trace")
    if (not fetch_time or fetch_time.date().isoformat() != trade_date
            or (account_time and fetch_time > account_time)
            or (sync_attempted and start_time and fetch_time.replace(microsecond=0) < start_time)
            or comparison.get("broker_account_refresh_confirmed") is False):
        blockers.append("stale_or_failed_account_fetch")
    if sync_attempted and not reconciliation_completed:
        blockers.append("reconciliation_not_completed")
    if (not broker_time or broker_time.date().isoformat() != trade_date
            or (account_time and broker_time > account_time)):
        blockers.append("stale_or_missing_broker_sync")
    if sync_attempted and start_time and (
        not broker_time or broker_time < start_time
        or not account_time or account_time < start_time
    ):
        blockers.append("evidence_not_from_current_execution")
    broker_ok = (broker.get("ok") is True
                 and (broker.get("order_fill_pagination_complete") is True
                      or broker.get("status") == "no_submissions"))
    if not broker_ok or (sync_attempted and (
        not sync_completed or broker.get("confirmed_evidence_required") is not True
    )):
        blockers.extend(broker.get("evidence_blocking_reasons") or ["broker_sync_not_complete"])
        status = "blocked_broker_evidence"
    elif blockers:
        status = "stale_evidence"
    else:
        status = "aligned"
    categories: list[str] = []
    for flag, category in (("positions_match", "quantity"), ("balance_match", "cash"),
                           ("total_asset_match", "valuation")):
        if comparison.get(flag) is not True:
            categories.append(category)
    if int(comparison.get("unknown_local_submission_count", 0) or 0) > 0:
        categories.append("unconfirmed_submission")
    gaps = [comparison.get("cash_gap"), comparison.get("total_asset_gap")]
    valid_gaps = all(isinstance(gap, (int, float)) and math.isfinite(gap) for gap in gaps)
    if not valid_gaps:
        categories.append("invalid_gap_evidence")
    if status == "aligned":
        if categories or comparison.get("status") not in {"aligned", "aligned_waiting_first_submission"}:
            status = "needs_review"
        elif comparison.get("status") == "aligned_waiting_first_submission":
            status = "no_submission_observation"
        elif any(gap != 0 for gap in gaps):
            status = "aligned_with_tolerated_gaps"
    # A cached prior recovery is not a recovery performed by this invocation.
    report_current = (broker_time and broker_time.date().isoformat() == trade_date
                      and (not start_time or broker_time >= start_time))
    applied = (sync_attempted and report_current and broker.get("confirmed_evidence_required") is True
               and (sync_completed or broker.get("status") == "accounting_sync_failed"))
    applied_events = int(broker.get("applied_fill_events", 0) or 0) if applied else 0
    applied_qty = int(broker.get("applied_fill_qty", 0) or 0) if applied else 0
    action = "confirmed_fill_sync_applied" if applied_events else "no_accounting_change"
    if applied_events and broker.get("status") == "accounting_sync_failed":
        action = "partial_confirmed_fill_sync_applied"
    if sync_attempted and not sync_completed and (not report_current or broker.get("ok") is True):
        action = "accounting_change_unverified"
        applied_events = applied_qty = None
    remaining = list(categories)
    if valid_gaps and any(gap != 0 for gap in gaps):
        remaining.append("cost_settlement_or_mark_timing_unresolved")
    if blockers:
        remaining.append("complete_current_broker_evidence_required_no_automatic_retry")
    return {
        "status": status, "gap_categories": categories,
        "cash_gap": comparison.get("cash_gap"), "total_asset_gap": comparison.get("total_asset_gap"),
        "accounting_action": action,
        "applied_fill_events": applied_events, "applied_fill_qty": applied_qty,
        "automatic_account_alignment": False, "evidence_blocking_reasons": sorted(set(blockers)),
        "root_cause_scope_counts": summarize_trace_payload(trace)["root_cause_scope_counts"] if not blockers else {},
        "cause_confidence": "existing_trace_evidence_only" if not blockers else "unresolved",
        "remaining_investigation": remaining,
        "phase0_history_rewritten": False,
    }


def is_non_trading_day_status(status: dict[str, Any]) -> bool:
    session_status = str(status.get("current_session_status") or status.get("session_status") or "").strip()
    return session_status in NON_TRADING_DAY_STATUSES


def load_live_runtime_status(project_root: Path) -> dict[str, Any]:
    command = ["bash", "./scripts/get_live_runtime_status.sh"]
    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "unknown", "error": type(exc).__name__}
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        payload = {"status": "invalid_json"}
    if isinstance(payload, dict):
        payload["status_command_returncode"] = completed.returncode
        return payload
    return {"status": "invalid_json", "status_command_returncode": completed.returncode}


def run_step(name: str, command: list[str], project_root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "name": name,
        "command": display_command((name, command), project_root),
        "returncode": completed.returncode,
        "stdout_tail": tail_text(completed.stdout),
        "stderr_tail": tail_text(completed.stderr),
    }


def summarize_trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    symbol_summaries = payload.get("symbol_summaries")
    if not isinstance(symbol_summaries, list):
        symbol_summaries = []
    root_causes = Counter(
        str(item.get("root_cause_scope") or "missing")
        for item in symbol_summaries
        if isinstance(item, dict)
    )
    likely_issues = Counter(
        str(item.get("likely_issue") or "missing")
        for item in symbol_summaries
        if isinstance(item, dict)
    )
    return {
        "assessment_status": (payload.get("assessment") or {}).get("status") if isinstance(payload.get("assessment"), dict) else None,
        "assessment_summary": (payload.get("assessment") or {}).get("summary") if isinstance(payload.get("assessment"), dict) else None,
        "mismatch_count": payload.get("mismatch_count"),
        "broker_sync_status": (payload.get("broker_sync") or {}).get("status") if isinstance(payload.get("broker_sync"), dict) else None,
        "broker_open_order_count": (payload.get("broker_sync") or {}).get("open_order_count") if isinstance(payload.get("broker_sync"), dict) else None,
        "root_cause_scope_counts": dict(sorted(root_causes.items())),
        "likely_issue_counts": dict(sorted(likely_issues.items())),
        "symbols": payload.get("symbols", []),
    }


def build_recheck_summary(status: str, trace_summary: dict[str, Any]) -> str:
    if status != "ok":
        return "paper/KIS mismatch recheck did not complete"
    mismatch_count = trace_summary.get("mismatch_count")
    root_causes = trace_summary.get("root_cause_scope_counts") or {}
    if mismatch_count in (0, "0"):
        return "paper/KIS mismatch recheck completed with no mismatches"
    if root_causes:
        return f"paper/KIS mismatch recheck completed: {mismatch_count} mismatch(es), root causes {root_causes}"
    return "paper/KIS mismatch recheck completed"


def tail_text(value: str, *, max_lines: int = 20, max_chars: int = 4000) -> str:
    lines = value.splitlines()[-max_lines:]
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[-max_chars:]
    return text


def display_command(command_item: tuple[str, list[str]], project_root: Path) -> list[str]:
    _name, command = command_item
    displayed: list[str] = []
    for part in command:
        try:
            path = Path(part)
            if path.is_absolute():
                displayed.append(str(path.relative_to(project_root)))
                continue
        except (ValueError, OSError):
            pass
        displayed.append(part)
    return displayed


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_inside_repo(value: str, repo_root: Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise SystemExit(f"{label} must stay inside repository root: {resolved}") from exc
    return resolved


if __name__ == "__main__":
    raise SystemExit(main())
