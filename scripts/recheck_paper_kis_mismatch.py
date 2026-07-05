#!/usr/bin/env python3
"""Post-close paper/KIS mismatch recheck wrapper.

This wrapper is intentionally conservative: it refuses to run during pre-open,
regular-session, or while live runtime is running unless explicitly overridden.
It performs no alignment and sends no orders. The default flow refreshes broker
paper order/fill sync, refreshes paper/account reconciliation, then rebuilds the
read-only mismatch trace report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = Path("runtime-data/reports/reconciliation/latest-paper-kis-mismatch-recheck.json")
DEFAULT_TRACE_PATH = Path("runtime-data/reports/reconciliation/latest-paper-kis-mismatch-trace.json")
PROTECTED_SESSION_STATUSES = {"pre-open", "regular-session"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--limit-per-table", type=int, default=12)
    parser.add_argument("--allow-protected-session", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).expanduser().resolve()
    output_path = _resolve_inside_repo(args.output_path, project_root, "output_path")
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    runtime_status = load_live_runtime_status(project_root)
    planned_commands = build_command_plan(project_root, limit_per_table=args.limit_per_table)

    if is_protected_runtime_status(runtime_status) and not args.allow_protected_session:
        payload = {
            "status": "blocked",
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

    if args.dry_run:
        payload = {
            "status": "dry_run",
            "generated_at": generated_at,
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

    payload = {
        "status": status,
        "generated_at": generated_at,
        "summary": build_recheck_summary(status, trace_summary),
        "runtime_status": runtime_status,
        "steps": steps,
        "trace_report_path": str(DEFAULT_TRACE_PATH),
        "trace_summary": trace_summary,
        "blocking_reasons": [] if status == "ok" else ["recheck_step_failed_or_trace_missing"],
        "dry_run": False,
        "safety": {
            "alignment_applied": False,
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
        ("sync_broker_paper_orders", [python, "-m", "app", "--sync-broker-paper-orders"]),
        ("reconcile_paper_accounts", [python, "-m", "app", "--reconcile-paper-accounts"]),
        (
            "trace_paper_kis_mismatch",
            [python, "scripts/trace_paper_kis_mismatch.py", "--limit-per-table", str(limit_per_table)],
        ),
    ]


def is_protected_runtime_status(status: dict[str, Any]) -> bool:
    session_status = str(status.get("current_session_status") or status.get("session_status") or "").strip()
    if session_status in PROTECTED_SESSION_STATUSES:
        return True
    if bool(status.get("process_running")):
        return True
    if bool(status.get("live_runtime_should_run")):
        return True
    return False


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
