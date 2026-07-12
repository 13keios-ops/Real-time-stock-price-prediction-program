#!/usr/bin/env python3
"""Run the frozen review_ver_27 E1/E5 measurement once after 2026-07-20 close."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.utils.time import get_market_session_status, now_local
from scripts.summarize_lightgbm_defensive_shadow import (
    DEFAULT_DIAGNOSTICS,
    build_summary as build_defensive_shadow_summary,
)
from scripts.summarize_signal_ic import (
    build_summary as build_signal_ic_summary,
    render_markdown as render_signal_ic_markdown,
)


KST = ZoneInfo("Asia/Seoul")
WINDOW_START = "2026-07-04"
WINDOW_END = "2026-07-18"
NOT_BEFORE = datetime(2026, 7, 20, 15, 30, tzinfo=KST)
HORIZON_MIN = 15
E5_THRESHOLD = 0.40
E5_Z_THRESHOLD = 1.6449
DEFAULT_REPORT_ROOT = Path("runtime-data/reports/research/preregistered-e1-e5-20260718")
DEFAULT_ATTEMPT_PATH = DEFAULT_REPORT_ROOT / "latest-attempt.json"
DEFAULT_LATEST_PATH = DEFAULT_REPORT_ROOT / "latest-completed-round.json"
LABEL_REFRESH_STATE = Path("runtime-data/reports/ml-maintenance/state/latest-post-close-label-refresh.json")
PROTECTED_SESSIONS = frozenset({"pre-open", "regular-session"})

PRIOR_E5_REFERENCE = {
    "start_date": "2026-06-11",
    "end_date": "2026-07-03",
    "threshold": E5_THRESHOLD,
    "joined_rows": 25_198,
    "excess_vs_random_pct": 225.47722081790482,
    "z_score": 4.62776791142487,
    "passed_reverse_selection_observation": True,
    "source": "docs/cowork-reports/2026-07-04-buy-avoid-validation-verification-work_ver_23.md",
}

E5_PREREGISTERED_CRITERIA = {
    "source": "docs/cowork-reports/2026-07-05-alternative-approaches-validation-plan.md#e5",
    "window": {"start_date": WINDOW_START, "end_date": WINDOW_END},
    "threshold": E5_THRESHOLD,
    "second_interval_pass": "excess_vs_random_pct > 0 and z_score >= 1.6449",
    "hypothesis_limit": "two consecutive passing intervals establish a reverse-selection hypothesis only",
    "policy_review_requirement": "three consecutive passing intervals plus explicit account-owner approval",
    "automatic_policy_change": False,
}


def evaluate_execution_gate(*, current_time: datetime, session_status: str) -> dict[str, Any]:
    localized = current_time.astimezone(KST)
    reasons: list[str] = []
    if localized < NOT_BEFORE:
        reasons.append("before_preregistered_not_before")
    if str(session_status).strip().lower() in PROTECTED_SESSIONS:
        reasons.append("protected_market_session")
    return {
        "allowed": not reasons,
        "current_time": localized.isoformat(timespec="seconds"),
        "not_before": NOT_BEFORE.isoformat(timespec="seconds"),
        "session_status": session_status,
        "blocking_reasons": reasons,
    }


def evaluate_label_refresh_gate(state_path: Path) -> dict[str, Any]:
    if not state_path.is_file():
        return {
            "ready": False,
            "status": "missing",
            "maintenance_date": None,
            "completed_at": None,
            "blocking_reason": "label_refresh_state_missing",
        }
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "ready": False,
            "status": "invalid",
            "maintenance_date": None,
            "completed_at": None,
            "blocking_reason": "label_refresh_state_invalid",
        }
    status = str(payload.get("status") or "unknown")
    maintenance_date = str(payload.get("maintenance_date") or "")
    completed_at = payload.get("completed_at")
    ready = bool(
        status == "ok"
        and maintenance_date >= "2026-07-20"
        and isinstance(completed_at, str)
        and completed_at.strip()
    )
    return {
        "ready": ready,
        "status": status,
        "maintenance_date": maintenance_date or None,
        "completed_at": completed_at,
        "blocking_reason": None if ready else "label_refresh_not_ready_for_2026_07_20",
    }


def _threshold_result(summary: dict[str, Any], threshold: float) -> dict[str, Any] | None:
    for result in summary.get("buy_avoid_shadow", {}).get("thresholds", []):
        if abs(float(result.get("threshold", -1.0)) - threshold) < 1e-12:
            return result
    return None


def _build_e5_result(shadow_summary: dict[str, Any]) -> dict[str, Any]:
    threshold_result = _threshold_result(shadow_summary, E5_THRESHOLD)
    comparison = (
        threshold_result.get("random_control", {}).get("comparison", {})
        if threshold_result
        else {}
    )
    excess = comparison.get("excess_vs_random_pct")
    z_score = comparison.get("z_score")
    current_pass = bool(
        excess is not None
        and z_score is not None
        and float(excess) > 0
        and float(z_score) >= E5_Z_THRESHOLD
    )
    two_interval_pass = bool(
        PRIOR_E5_REFERENCE["passed_reverse_selection_observation"] and current_pass
    )
    if threshold_result is None:
        decision = "threshold_result_missing"
    elif two_interval_pass:
        decision = "reverse_selection_hypothesis_established_second_interval"
    else:
        decision = "reverse_selection_not_reproduced_second_interval"
    return {
        "status": "ok" if threshold_result is not None else "insufficient_data",
        "experiment": "E5_reverse_selection_observation",
        "preregistered_criteria": E5_PREREGISTERED_CRITERIA,
        "prior_interval": PRIOR_E5_REFERENCE,
        "current_interval": {
            "start_date": WINDOW_START,
            "end_date": WINDOW_END,
            "joined_rows": shadow_summary.get("joined_rows"),
            "prediction_lineage": shadow_summary.get("prediction_lineage", {}),
            "threshold": E5_THRESHOLD,
            "skipped_signals": (
                threshold_result.get("skipped", {}).get("signals")
                if threshold_result
                else None
            ),
            "excess_vs_random_pct": excess,
            "z_score": z_score,
            "verdict": comparison.get("verdict"),
            "sign_convention": comparison.get("sign_convention"),
            "passed_reverse_selection_observation": current_pass,
        },
        "decision": decision,
        "two_consecutive_intervals_passed": two_interval_pass,
        "automatic_policy_change": False,
        "policy_review_eligible": False,
        "next_requirement": "A third independent interval and explicit approval are required before policy review.",
    }


def run_preregistered_round(
    *,
    database_path: Path,
    diagnostics_path: Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = (generated_at or datetime.now(tz=KST)).astimezone(KST)
    e1 = build_signal_ic_summary(
        database_path=database_path,
        diagnostics_path=diagnostics_path,
        horizon_min=HORIZON_MIN,
        min_daily_rows=2,
        start_date=WINDOW_START,
        end_date=WINDOW_END,
    )
    shadow = build_defensive_shadow_summary(
        database_path=database_path,
        diagnostics_path=diagnostics_path,
        horizon_min=HORIZON_MIN,
        thresholds=[E5_THRESHOLD],
        require_down_argmax=True,
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        evaluate_early_exit=False,
    )
    e5 = _build_e5_result(shadow)
    rows_available = int(e1.get("joined_rows") or 0) > 0 and int(shadow.get("joined_rows") or 0) > 0
    window_locked = bool(
        e1.get("preregistered_remeasurement", {}).get("window_locked_to_review_ver_27")
    )
    return {
        "schema_version": 1,
        "job_type": "preregistered-e1-e5-round",
        "status": "ok" if rows_available and window_locked else "insufficient_data",
        "generated_at": generated.isoformat(timespec="seconds"),
        "window": {"start_date": WINDOW_START, "end_date": WINDOW_END},
        "horizon_min": HORIZON_MIN,
        "database_path": str(database_path),
        "lineage_scope": {
            "e1": {
                "status": "legacy_or_mixed_lineage_diagnostic_only",
                "lineage_required": False,
                "legacy_rows_may_be_included": True,
            },
            "e5": dict(shadow.get("prediction_lineage", {})),
            "candidate_or_policy_eligible": False,
            "reason": "E1/E5 are frozen diagnostics and cannot establish promotion lineage.",
        },
        "e1": e1,
        "e5": e5,
        "safety": {
            "read_only_database": True,
            "model_training_executed": False,
            "network_calls_executed": 0,
            "order_calls_executed": 0,
            "automatic_policy_change": False,
            "active_model_or_gate_changed": False,
        },
    }


def render_e5_markdown(e5: dict[str, Any]) -> str:
    current = e5.get("current_interval", {})
    prior = e5.get("prior_interval", {})
    lineage = current.get("prediction_lineage", {})
    return "\n".join(
        [
            "# E5 Reverse-Selection Observation",
            "",
            f"- status: `{e5.get('status')}`",
            f"- decision: `{e5.get('decision')}`",
            f"- current_window: `{current.get('start_date')}` ~ `{current.get('end_date')}`",
            f"- threshold: `{current.get('threshold')}`",
            f"- joined_rows: `{current.get('joined_rows')}`",
            f"- excess_vs_random_pct: `{current.get('excess_vs_random_pct')}`",
            f"- prediction_lineage_status: `{lineage.get('status')}`",
            f"- z_score: `{current.get('z_score')}`",
            f"- current_interval_passed: `{current.get('passed_reverse_selection_observation')}`",
            f"- prior_interval_passed: `{prior.get('passed_reverse_selection_observation')}`",
            f"- two_consecutive_intervals_passed: `{e5.get('two_consecutive_intervals_passed')}`",
            "- automatic_policy_change: `false`",
            "- policy_review_eligible: `false`",
            "",
            "This is a diagnostic observation only. It cannot change thresholds, gates, models, or order policy.",
            "",
        ]
    )


def render_round_markdown(payload: dict[str, Any]) -> str:
    e1 = payload.get("e1", {})
    reproduction = e1.get("preregistered_remeasurement", {}).get(
        "candidate_reproducibility", {}
    )
    relationship = e1.get("preregistered_remeasurement", {}).get(
        "special_105560_probability_relationship", {}
    )
    relation = relationship.get("down_up_daily_ic_relationship", {})
    e5 = payload.get("e5", {})
    current = e5.get("current_interval", {})
    lineage_scope = payload.get("lineage_scope", {})
    e5_lineage = lineage_scope.get("e5", {})
    return "\n".join(
        [
            "# Preregistered E1/E5 Round",
            "",
            f"- generated_at: `{payload.get('generated_at')}`",
            f"- status: `{payload.get('status')}`",
            f"- window: `{payload.get('window', {}).get('start_date')}` ~ `{payload.get('window', {}).get('end_date')}`",
            f"- E1 joined_rows: `{e1.get('joined_rows')}`",
            f"- E1 reproduced candidates: `{reproduction.get('reproduced_count')}/3`",
            f"- 105560 p_down/p_up paired days: `{relation.get('paired_days')}`",
            f"- E1 lineage: `{lineage_scope.get('e1', {}).get('status')}`",
            f"- E5 lineage: `{e5_lineage.get('status')}`",
            f"- 105560 p_down/p_up daily IC Pearson: `{relation.get('pearson')}`",
            f"- E5 excess_vs_random_pct: `{current.get('excess_vs_random_pct')}`",
            f"- E5 z_score: `{current.get('z_score')}`",
            f"- E5 decision: `{e5.get('decision')}`",
            "- automatic policy/model/gate/order change: `false`",
            "",
        ]
    )


def write_round_outputs(payload: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=False)
    paths = {
        "round_json": output_dir / "preregistered-e1-e5-round.json",
        "round_markdown": output_dir / "preregistered-e1-e5-round.md",
        "e1_json": output_dir / "e1-signal-ic-h15.json",
        "e1_markdown": output_dir / "e1-signal-ic-h15.md",
        "e5_json": output_dir / "e5-reverse-selection-h15.json",
        "e5_markdown": output_dir / "e5-reverse-selection-h15.md",
    }
    _write_json_atomic(paths["round_json"], payload)
    _write_text_atomic(paths["round_markdown"], render_round_markdown(payload))
    _write_json_atomic(paths["e1_json"], payload["e1"])
    _write_text_atomic(paths["e1_markdown"], render_signal_ic_markdown(payload["e1"]))
    _write_json_atomic(paths["e5_json"], payload["e5"])
    _write_text_atomic(paths["e5_markdown"], render_e5_markdown(payload["e5"]))
    return {key: str(path) for key, path in paths.items()}


def _create_snapshot(project_root: Path) -> Path:
    result = subprocess.run(
        ["bash", str(project_root / "scripts" / "create_research_db_snapshot.sh"), "--json"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    snapshot_path = Path(str(payload["snapshot_path"])).expanduser().resolve()
    if not snapshot_path.is_file() or payload.get("quick_check") != "ok":
        raise RuntimeError("research snapshot verification failed")
    return snapshot_path


def _resolve_repo_path(path: Path, project_root: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else project_root / path
    resolved = candidate.expanduser().resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise SystemExit(f"{label} must stay inside repository root: {resolved}") from exc
    return resolved


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(content, encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--database-path", type=Path)
    parser.add_argument("--diagnostics-path", type=Path, default=DEFAULT_DIAGNOSTICS)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    report_root = _resolve_repo_path(args.report_root, project_root, "report_root")
    attempt_path = report_root / DEFAULT_ATTEMPT_PATH.name
    latest_path = report_root / DEFAULT_LATEST_PATH.name
    settings = load_settings(project_root=project_root)
    current = now_local(settings.timezone)
    session = get_market_session_status(settings.market_calendar, current)
    gate = evaluate_execution_gate(current_time=current, session_status=session)
    label_refresh_path = _resolve_repo_path(
        LABEL_REFRESH_STATE,
        project_root,
        "label_refresh_state",
    )
    label_refresh_gate = evaluate_label_refresh_gate(label_refresh_path)
    gate["label_refresh"] = label_refresh_gate
    if not label_refresh_gate["ready"]:
        gate["blocking_reasons"].append(label_refresh_gate["blocking_reason"])
        gate["allowed"] = False

    if not args.execute:
        attempt = {
            "schema_version": 1,
            "job_type": "preregistered-e1-e5-round-attempt",
            "status": "dry_run",
            "execution_requested": False,
            "gate": gate,
            "window": {"start_date": WINDOW_START, "end_date": WINDOW_END},
            "would_create_snapshot": args.database_path is None,
            "safety": {"network_calls_executed": 0, "order_calls_executed": 0},
        }
        _write_json_atomic(attempt_path, attempt)
        print(json.dumps(attempt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if latest_path.is_file():
        existing = json.loads(latest_path.read_text(encoding="utf-8"))
        if existing.get("status") == "ok":
            print(
                json.dumps(
                    {"status": "already_completed", "report": existing},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    if not gate["allowed"]:
        attempt = {
            "schema_version": 1,
            "job_type": "preregistered-e1-e5-round-attempt",
            "status": "blocked",
            "execution_requested": True,
            "gate": gate,
            "window": {"start_date": WINDOW_START, "end_date": WINDOW_END},
            "safety": {"network_calls_executed": 0, "order_calls_executed": 0},
        }
        _write_json_atomic(attempt_path, attempt)
        print(json.dumps(attempt, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    database_path = (
        args.database_path.expanduser().resolve()
        if args.database_path is not None
        else _create_snapshot(project_root)
    )
    if not database_path.is_file():
        raise SystemExit(f"database not found: {database_path}")
    diagnostics_path = args.diagnostics_path
    if not diagnostics_path.is_absolute():
        diagnostics_path = project_root / diagnostics_path
    payload = run_preregistered_round(
        database_path=database_path,
        diagnostics_path=diagnostics_path.resolve(),
        generated_at=current,
    )
    run_id = current.astimezone(KST).strftime("%Y%m%d-%H%M%S-%f")
    output_dir = report_root / "runs" / run_id
    outputs = write_round_outputs(payload, output_dir)
    completion = {
        "schema_version": 1,
        "status": payload["status"],
        "generated_at": payload["generated_at"],
        "window": payload["window"],
        "database_path": str(database_path),
        "outputs": outputs,
        "automatic_policy_change": False,
    }
    _write_json_atomic(latest_path, completion)
    print(json.dumps(completion, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
