#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _metric(mapping: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping:
            return mapping.get(name)
    return None


def _experiment_status(*, trades: int, hit_rate: float, net_return: float | None) -> str:
    if trades <= 0:
        return "no_trades"
    if net_return is None:
        return "diagnostic_only"
    if net_return > 0 and hit_rate >= 0.3:
        return "follow_up_candidate"
    if net_return > 0:
        return "positive_return_but_hit_rate_weak"
    if hit_rate >= 0.3:
        return "hit_rate_ok_but_cost_negative"
    return "hold"


def _summarize_bar_experiment(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path)
    if payload is None:
        return None
    walk_forward = payload.get("walk_forward") if isinstance(payload.get("walk_forward"), dict) else {}
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    feature_set = str(payload.get("feature_set_name") or payload.get("experiment") or path.stem)
    trades = _int(_metric(walk_forward, "trades_taken"))
    hit_rate = _float(_metric(walk_forward, "trade_hit_rate"))
    net_raw = _metric(walk_forward, "trade_sum_net_return_pct", "cumulative_net_return_pct")
    net_return = None if net_raw is None else _float(net_raw)
    return {
        "report_path": str(path),
        "feature_set_name": feature_set,
        "completed_at": payload.get("completed_at"),
        "folds": _int(_metric(walk_forward, "folds")),
        "rows_evaluated": _int(_metric(walk_forward, "rows_evaluated")),
        "trades_taken": trades,
        "overall_accuracy": _float(_metric(walk_forward, "overall_accuracy")),
        "trade_hit_rate": hit_rate,
        "net_return_pct": net_return,
        "trade_cost_pct": _metric(walk_forward, "trade_cost_pct"),
        "validation_accuracy": _float(_metric(validation, "overall_accuracy")),
        "feature_importance_top5": payload.get("feature_importance_top5") or [],
        "status": _experiment_status(trades=trades, hit_rate=hit_rate, net_return=net_return),
    }


def _summarize_expected_value(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path)
    if payload is None:
        return None
    headline = payload.get("headline") if isinstance(payload.get("headline"), dict) else {}
    sweep_rows: list[dict[str, Any]] = []
    for row in payload.get("cost_sweep", []):
        if not isinstance(row, dict):
            continue
        bootstrap = row.get("bootstrap") if isinstance(row.get("bootstrap"), dict) else {}
        ci = bootstrap.get("fold_sum_net_return_pct_ci95") if isinstance(bootstrap.get("fold_sum_net_return_pct_ci95"), dict) else {}
        dist = row.get("fold_distribution") if isinstance(row.get("fold_distribution"), dict) else {}
        sweep_rows.append(
            {
                "trade_cost_pct": _float(row.get("trade_cost_pct")),
                "trades_taken": _int(row.get("trades_taken")),
                "trade_sum_net_return_pct": _float(row.get("trade_sum_net_return_pct")),
                "ci95_low": _float(ci.get("low")),
                "ci95_high": _float(ci.get("high")),
                "positive_net_folds": _int(dist.get("positive_net_folds")),
                "negative_net_folds": _int(dist.get("negative_net_folds")),
                "no_trade_folds": _int(dist.get("no_trade_folds")),
                "conclusion": row.get("conclusion"),
            }
        )
    return {
        "report_path": str(path),
        "completed_at": payload.get("completed_at"),
        "feature_set_name": payload.get("feature_set_name"),
        "horizon_min": payload.get("horizon_min"),
        "headline": headline,
        "cost_sweep": sweep_rows,
        "reliability_flags": payload.get("reliability_flags") or [],
        "conclusion": payload.get("conclusion"),
    }


def _summarize_rule_challengers(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path)
    if payload is None:
        return None
    leaderboard = [row for row in payload.get("leaderboard", []) if isinstance(row, dict)]
    best = max(leaderboard, key=lambda row: _float(row.get("cumulative_net_return_pct")), default=None)
    compact_top5 = [
        {
            "strategy_name": row.get("strategy_name"),
            "trades_taken": _int(row.get("trades_taken")),
            "trade_hit_rate": _float(row.get("trade_hit_rate")),
            "win_rate": _float(row.get("win_rate")),
            "average_net_return_pct": _float(row.get("average_net_return_pct")),
            "cumulative_net_return_pct": _float(row.get("cumulative_net_return_pct")),
            "profit_factor": _float(row.get("profit_factor")),
            "max_drawdown_pct": _float(row.get("max_drawdown_pct")),
        }
        for row in leaderboard[:5]
    ]
    return {
        "report_path": str(path),
        "completed_at": payload.get("completed_at"),
        "trade_cost_pct": payload.get("trade_cost_pct"),
        "decision": payload.get("decision") or {},
        "strategy_count": len(leaderboard),
        "best_by_net_return": {
            "strategy_name": best.get("strategy_name") if best else None,
            "trades_taken": _int(best.get("trades_taken")) if best else 0,
            "trade_hit_rate": _float(best.get("trade_hit_rate")) if best else 0.0,
            "cumulative_net_return_pct": _float(best.get("cumulative_net_return_pct")) if best else 0.0,
            "profit_factor": _float(best.get("profit_factor")) if best else 0.0,
        },
        "leaderboard_top5": compact_top5,
    }


def _summarize_decision_report(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path)
    if payload is None:
        return None
    return {
        "report_path": str(path),
        "completed_at": payload.get("completed_at"),
        "review": payload.get("review"),
        "decision": payload.get("decision") or {},
    }


def summarize(report_dir: Path) -> dict[str, Any]:
    bar_patterns = [
        "latest-cybos-bar-only-h15.json",
        "latest-cybos-bar-only-f1-h15.json",
        "latest-cybos-bar-context-h15.json",
        "latest-cybos-bar-context-momentum-h15.json",
    ]
    bar_experiments = [
        item
        for item in (_summarize_bar_experiment(report_dir / pattern) for pattern in bar_patterns)
        if item is not None
    ]
    bar_experiments.sort(
        key=lambda row: (
            _float(row.get("net_return_pct"), -1_000_000.0),
            _float(row.get("trade_hit_rate")),
            _int(row.get("trades_taken")),
        ),
        reverse=True,
    )
    expected_value = _summarize_expected_value(
        report_dir / "latest-cybos-expected-value-stability-bar-context-momentum-h15.json"
    )
    rule_challengers = _summarize_rule_challengers(report_dir / "latest-cybos-rule-challengers-review.json")
    label_sensitivity = _summarize_decision_report(report_dir / "latest-cybos-label-sensitivity-review.json")
    label_reproducibility = _summarize_decision_report(report_dir / "latest-cybos-label-reproducibility-review.json")

    follow_up_candidates = [row for row in bar_experiments if row.get("status") == "follow_up_candidate"]
    ev_candidate = False
    if expected_value:
        for row in expected_value.get("cost_sweep", []):
            if _float(row.get("trade_sum_net_return_pct")) > 0 and _float(row.get("ci95_low")) > 0:
                ev_candidate = True
                break
    rule_best = (rule_challengers or {}).get("best_by_net_return") or {}
    rule_candidate = _float(rule_best.get("cumulative_net_return_pct")) > 0

    if follow_up_candidates or ev_candidate or rule_candidate:
        posture = "follow_up_candidate_exists"
        conclusion = "일부 후보가 후속 검증 후보로 남아 있습니다. 자동 승격이 아니라 out-of-sample 검증으로 넘깁니다."
    else:
        posture = "hold_all_current_cybos_candidates"
        conclusion = "현재 Cybos 기반 ML/룰 후보는 비용 반영과 fold 안정성 기준에서 자동 승격할 후보가 없습니다."

    return {
        "review": "cybos_research_suite_summary",
        "completed_at": datetime.now().astimezone().isoformat(),
        "report_dir": str(report_dir),
        "posture": posture,
        "conclusion": conclusion,
        "bar_experiments": bar_experiments,
        "expected_value": expected_value,
        "rule_challengers": rule_challengers,
        "label_sensitivity": label_sensitivity,
        "label_reproducibility": label_reproducibility,
        "next_actions": [
            "Cybos 15분 bar-only 계열은 신규 튜닝보다 KIS 실시간 호가/체결 데이터 누적 품질 확인을 우선한다.",
            "후속 모델 실험은 비용 0.13% 이상에서 fold bootstrap CI 하단이 양수인지 먼저 보도록 설계한다.",
            "룰 기반 전략은 현재 고정 룰을 늘리기보다 regime/시장상태 피처를 추가한 뒤 기간 분리로 검증한다.",
            "월요일 장전에는 live runtime/watchdog 자동 기동과 09:30 수집률 확인을 우선한다.",
        ],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Cybos Research Suite Summary",
        "",
        f"- completed_at: `{summary.get('completed_at')}`",
        f"- posture: `{summary.get('posture')}`",
        f"- conclusion: {summary.get('conclusion')}",
        "",
        "## Bar Experiments",
        "",
        "| feature_set | folds | trades | accuracy | hit_rate | net_pct | status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary.get("bar_experiments", []):
        net = row.get("net_return_pct")
        net_text = "n/a" if net is None else f"{_float(net):.6f}"
        lines.append(
            "| "
            f"{row.get('feature_set_name')} | "
            f"{_int(row.get('folds'))} | "
            f"{_int(row.get('trades_taken'))} | "
            f"{_float(row.get('overall_accuracy')):.6f} | "
            f"{_float(row.get('trade_hit_rate')):.6f} | "
            f"{net_text} | "
            f"{row.get('status')} |"
        )

    expected_value = summary.get("expected_value") or {}
    lines.extend(
        [
            "",
            "## Expected-Value Cost Sweep",
            "",
            "| cost_pct | trades | net_pct | ci95_sum_net_pct | conclusion |",
            "| ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in expected_value.get("cost_sweep", []):
        lines.append(
            "| "
            f"{_float(row.get('trade_cost_pct')):.6f} | "
            f"{_int(row.get('trades_taken'))} | "
            f"{_float(row.get('trade_sum_net_return_pct')):.6f} | "
            f"{_float(row.get('ci95_low')):.6f}..{_float(row.get('ci95_high')):.6f} | "
            f"{row.get('conclusion')} |"
        )

    rules = summary.get("rule_challengers") or {}
    best_rule = rules.get("best_by_net_return") or {}
    lines.extend(
        [
            "",
            "## Rule Challengers",
            "",
            f"- decision: `{(rules.get('decision') or {}).get('label')}`",
            f"- best_by_net_return: `{best_rule.get('strategy_name')}`",
            f"- best_trades: `{_int(best_rule.get('trades_taken'))}`",
            f"- best_hit_rate: `{_float(best_rule.get('trade_hit_rate')):.6f}`",
            f"- best_net_pct: `{_float(best_rule.get('cumulative_net_return_pct')):.6f}`",
            "",
            "## Label Reviews",
            "",
            f"- sensitivity: `{((summary.get('label_sensitivity') or {}).get('decision') or {}).get('label')}`",
            f"- reproducibility: `{((summary.get('label_reproducibility') or {}).get('decision') or {}).get('label')}`",
            "",
            "## Next Actions",
            "",
        ]
    )
    for item in summary.get("next_actions", []):
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize existing Cybos research reports into one decision sheet.")
    parser.add_argument("--report-dir", default="runtime-data/reports/backtests")
    parser.add_argument("--out-json", default="runtime-data/reports/backtests/latest-cybos-research-suite-summary.json")
    parser.add_argument("--out-md", default="runtime-data/reports/backtests/latest-cybos-research-suite-summary.md")
    args = parser.parse_args()

    summary = summarize(Path(args.report_dir))
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
