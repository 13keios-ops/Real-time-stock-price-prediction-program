from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


KST = timezone(timedelta(hours=9))


def _now_kst() -> str:
    return datetime.now(KST).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _input_status(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "generated_at": payload.get("generated_at"),
        "status": payload.get("status") or payload.get("assessment", {}).get("posture") or payload.get("decision", {}).get("status"),
        "report": payload.get("report") or payload.get("review"),
    }


def _models_from_overlay(overlay: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model in overlay.get("models", []) or []:
        classification = model.get("classification", {}) or {}
        avoid = model.get("buy_avoid", {}) or {}
        rescue = model.get("buy_rescue", {}) or {}
        hold = model.get("hold_rescue", {}) or {}
        role = model.get("role_assessment", {}) or {}
        rescue_best = rescue.get("best") or {}
        rows.append(
            {
                "name": model.get("name"),
                "model_version": model.get("model_version"),
                "suggested_roles": role.get("suggested_roles", []),
                "policy_status": role.get("policy_status"),
                "three_class_accuracy": classification.get("three_class_accuracy"),
                "virtual_direction_cumulative_net_return_pct": classification.get(
                    "virtual_direction_cumulative_net_return_pct"
                ),
                "buy_avoid_best_delta_net_return_pct": (avoid.get("best") or {}).get("delta_net_return_pct"),
                "buy_rescue_best_net_return_pct": rescue_best.get("rescued_net_return_pct")
                if "rescued_net_return_pct" in rescue_best
                else rescue_best.get("policy_net_return_pct"),
                "hold_rescue_best_delta_cash_sum": (hold.get("best") or {}).get("delta_cash_sum"),
                "recommended_next_step": role.get("recommended_next_step"),
            }
        )
    return rows


def _policy_candidates(overlay: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    review = overlay.get("combination_policy_review", {}) or {}
    candidates = list(review.get("policy_candidates", []) or [])
    best = dict(review.get("best_policy", {}) or {})
    normalized: list[dict[str, Any]] = []
    for candidate in candidates:
        normalized.append(
            {
                "family": candidate.get("family"),
                "policy": candidate.get("policy"),
                "baseline_rows": candidate.get("baseline_rows"),
                "executed_rows": candidate.get("executed_rows"),
                "skipped_or_filtered_rows": candidate.get("skipped_or_filtered_rows"),
                "coverage": candidate.get("coverage"),
                "baseline_net_return_pct": candidate.get("baseline_net_return_pct"),
                "policy_net_return_pct": candidate.get("policy_net_return_pct"),
                "delta_net_return_pct": candidate.get("delta_net_return_pct"),
                "loss_share": candidate.get("loss_share"),
                "shadow_interpretation": "diagnostic_only_no_order_policy_change",
            }
        )
    if best:
        best["shadow_interpretation"] = "best_backtest_candidate_not_live_policy"
    return normalized, best


def _candidate_actions_from_transfer(transfer: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for action in transfer.get("candidate_actions", []) or []:
        actions.append(
            {
                "candidate": action.get("candidate"),
                "type": action.get("type"),
                "role": action.get("role"),
                "evidence": action.get("evidence", {}),
                "recommended_next_step": action.get("recommended_next_step"),
                "shadow_interpretation": "phase1_observe_only",
            }
        )
    return actions


def _buy_rescue_summary(rescue: dict[str, Any]) -> dict[str, Any]:
    decision = rescue.get("decision", {}) or {}
    return {
        "status": decision.get("status") or "not_available",
        "recommended_action": decision.get("recommended_action"),
        "best_buy_rescue_target_rate": decision.get("best_buy_rescue_target_rate"),
        "reason": decision.get("reason"),
        "runtime_baseline_replay": rescue.get("runtime_baseline_replay", {}),
        "scope": rescue.get("scope"),
        "shadow_interpretation": "diagnostic_only_do_not_start_kis_live_rescue_shadow",
    }


def _hold_rescue_summary(hold: dict[str, Any]) -> dict[str, Any]:
    decision = hold.get("decision", {}) or {}
    replay = hold.get("replay", {}) or {}
    threshold_results = replay.get("threshold_results", []) or []
    best = None
    if threshold_results:
        best = max(threshold_results, key=lambda row: row.get("delta_cash_sum", float("-inf")))
    return {
        "status": decision.get("status") or "not_available",
        "recommended_action": decision.get("recommended_action"),
        "candidate_thresholds": decision.get("candidate_thresholds", []),
        "eligible_lots": hold.get("eligibility", {}).get("eligible_lots"),
        "best_threshold_result": best,
        "scope_guardrail": decision.get("scope_guardrail"),
        "shadow_interpretation": "paper_only_diagnostic_no_order_policy_change",
    }


def build_report(
    *,
    repo_root: Path,
    horizon_min: int,
    generated_at: str | None = None,
    overlay_path: Path | None = None,
    transfer_path: Path | None = None,
    rescue_path: Path | None = None,
    hold_path: Path | None = None,
) -> dict[str, Any]:
    overlay_path = overlay_path or repo_root / f"runtime-data/reports/challengers/latest-model-overlay-comparison-h{horizon_min}.json"
    transfer_path = transfer_path or repo_root / "runtime-data/reports/research/latest-cybos-kis-transfer-review.json"
    rescue_path = rescue_path or repo_root / f"runtime-data/reports/backtests/latest-cybos-rescue-proxy-h{horizon_min}.json"
    hold_path = hold_path or repo_root / f"runtime-data/reports/challengers/latest-hold-rescue-paper-replay-h{horizon_min}.json"

    overlay = _read_json(overlay_path)
    transfer = _read_json(transfer_path)
    rescue = _read_json(rescue_path)
    hold = _read_json(hold_path)

    policies, best_policy = _policy_candidates(overlay)
    model_roles = _models_from_overlay(overlay)
    transfer_actions = _candidate_actions_from_transfer(transfer)
    buy_rescue = _buy_rescue_summary(rescue)
    hold_rescue = _hold_rescue_summary(hold)

    posture = "phase1_shadow_only_no_order_policy_change"
    blockers: list[str] = []
    if not overlay:
        blockers.append("missing_model_overlay_report")
    if not transfer:
        blockers.append("missing_cybos_kis_transfer_report")

    primary_candidate = None
    if best_policy:
        primary_candidate = {
            "candidate": best_policy.get("policy"),
            "family": best_policy.get("family"),
            "delta_net_return_pct": best_policy.get("delta_net_return_pct"),
            "coverage": best_policy.get("coverage"),
            "policy_net_return_pct": best_policy.get("policy_net_return_pct"),
            "interpretation": "strongest historical/shadow candidate, not an execution rule",
        }

    return {
        "generated_at": generated_at or _now_kst(),
        "report": "meta_policy_shadow",
        "horizon_min": horizon_min,
        "scope": posture,
        "status": "ok" if not blockers else "needs_inputs",
        "blockers": blockers,
        "inputs": {
            "model_overlay": _input_status(overlay_path, overlay),
            "cybos_kis_transfer": _input_status(transfer_path, transfer),
            "cybos_buy_rescue_proxy": _input_status(rescue_path, rescue),
            "hold_rescue_paper_replay": _input_status(hold_path, hold),
        },
        "current_recommendation": {
            "posture": posture,
            "primary_shadow_candidate": primary_candidate,
            "active_model_change": False,
            "gate_change": False,
            "paper_order_policy_change": False,
            "kis_live_shadow_expansion": False,
            "recommended_next_step": (
                "Phase 1에서는 baseline 주문 판단을 유지하고, meta-policy 후보는 대시보드/리포트에서 "
                "would-skip/would-allow 진단으로만 누적합니다."
            ),
        },
        "model_roles": model_roles,
        "combination_policy_candidates": policies,
        "kis_transfer_candidates": transfer_actions,
        "buy_rescue": buy_rescue,
        "hold_rescue": hold_rescue,
        "guardrails": [
            "No live order, paper order policy, active model, gate, config, VERSION, or app/risk change.",
            "Cybos-only evidence cannot promote a KIS live execution policy.",
            "KIS-only orderbook candidates require 20/30/60 trading-day live checkpoints.",
            "Policy candidates remain diagnostic when policy net return is negative or sample is concentrated.",
            "Buy-rescue and hold-rescue stay disabled until independent live/paper evidence turns positive after costs.",
        ],
        "phase1_observation_plan": {
            "collect": [
                "baseline decision",
                "LightGBM probabilities",
                "linear-score probabilities",
                "would_skip_by_each_model",
                "would_skip_by_either_model",
                "KIS orderbook context",
                "time/momentum regime",
                "actual h15/h60 result",
            ],
            "evaluate_after": [
                "10 trading days",
                "20 trading days",
                "30 trading days",
                "60 trading days",
            ],
            "minimum_for_formal_read": {
                "matched_buy_shadow_rows": 1000,
                "matched_trade_days": 10,
                "avoid_candidate_rows": 200,
            },
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    recommendation = report["current_recommendation"]
    lines = [
        "# Meta Policy Shadow",
        "",
        f"- 생성 시각: `{report['generated_at']}`",
        f"- horizon: `{report['horizon_min']}분`",
        f"- 상태: `{report['status']}`",
        f"- 범위: `{report['scope']}`",
        "",
        "## 결론",
        "",
        "- 현재 적용 방향은 `단독 모델 주문 판단`이 아니라 `baseline 신호 + 메타 필터/라우터 shadow 관측`입니다.",
        "- 이 리포트는 주문 정책, active model, gate, KIS live shadow 확장을 바꾸지 않습니다.",
        f"- 다음 행동: {recommendation['recommended_next_step']}",
        "",
    ]
    primary = recommendation.get("primary_shadow_candidate")
    if primary:
        lines.extend(
            [
                "## 1차 shadow 후보",
                "",
                f"- 후보: `{primary.get('candidate')}`",
                f"- 계열: `{primary.get('family')}`",
                f"- 비용 차감 delta: `{primary.get('delta_net_return_pct')}`",
                f"- 실행 coverage: `{primary.get('coverage')}`",
                f"- 정책 순수익률: `{primary.get('policy_net_return_pct')}`",
                "- 해석: 가장 강한 과거/진단 후보지만, 실전 실행 규칙이 아닙니다.",
                "",
            ]
        )

    lines.extend(["## 모델별 현재 역할", ""])
    for model in report.get("model_roles", []):
        lines.append(
            "- `{name}`: roles={roles}, 3분류 정확도={acc}, buy-avoid delta={avoid}, "
            "buy-rescue net={rescue}, hold-rescue cash delta={hold}".format(
                name=model.get("name"),
                roles=model.get("suggested_roles"),
                acc=model.get("three_class_accuracy"),
                avoid=model.get("buy_avoid_best_delta_net_return_pct"),
                rescue=model.get("buy_rescue_best_net_return_pct"),
                hold=model.get("hold_rescue_best_delta_cash_sum"),
            )
        )
    lines.append("")

    lines.extend(["## KIS/Cybos 전이성 후보", ""])
    for action in report.get("kis_transfer_candidates", []):
        lines.append(
            f"- `{action.get('candidate')}`: `{action.get('role')}` / `{action.get('type')}` / {action.get('recommended_next_step')}"
        )
    if not report.get("kis_transfer_candidates"):
        lines.append("- 입력 리포트가 없거나 후보가 없습니다.")
    lines.append("")

    lines.extend(
        [
            "## rescue 상태",
            "",
            f"- buy-rescue: `{report['buy_rescue'].get('status')}` / {report['buy_rescue'].get('recommended_action')}",
            f"- hold-rescue: `{report['hold_rescue'].get('status')}` / {report['hold_rescue'].get('recommended_action')}",
            "",
            "## 안전 가드레일",
            "",
        ]
    )
    for guardrail in report.get("guardrails", []):
        lines.append(f"- {guardrail}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize Phase 1 meta-policy shadow candidates.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runtime-data/reports/research"),
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    report = build_report(repo_root=repo_root, horizon_min=args.horizon_min)
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    json_path = output_dir / f"latest-meta-policy-shadow-h{args.horizon_min}.json"
    md_path = output_dir / f"latest-meta-policy-shadow-h{args.horizon_min}.md"
    _write_json(json_path, report)
    _write_text(md_path, render_markdown(report))
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
