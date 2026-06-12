#!/usr/bin/env python3
"""Summarize extreme walk-forward folds from the latest gate report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "runtime-data" / "reports" / "backtests" / "latest-walk-forward-h15.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "backtests"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _candidate_fold_lists(report: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key, value in report.items():
        if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value[:5]):
            continue
        score = 0
        sample_keys = set().union(*(item.keys() for item in value[: min(5, len(value))]))
        if any("accuracy" in str(k).lower() for k in sample_keys):
            score += 2
        if any("fold" in str(k).lower() for k in sample_keys):
            score += 1
        if any("start" in str(k).lower() or "end" in str(k).lower() for k in sample_keys):
            score += 1
        if score:
            candidates.append({"key": key, "score": score, "rows": value})
    candidates.sort(key=lambda item: (-item["score"], item["key"]))
    return candidates


def _metric(row: dict[str, Any]) -> float | None:
    for key in ("three_class_accuracy", "overall_accuracy", "accuracy"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _pick_fold_key(report: dict[str, Any], explicit_key: str | None) -> tuple[str | None, list[dict[str, Any]]]:
    if explicit_key:
        rows = report.get(explicit_key)
        return explicit_key, rows if isinstance(rows, list) else []
    for candidate in _candidate_fold_lists(report):
        rows = [row for row in candidate["rows"] if _metric(row) is not None]
        if rows:
            return str(candidate["key"]), rows
    return None, []


def build_summary(report: dict[str, Any], *, fold_key: str | None, worst_count: int, best_count: int) -> dict[str, Any]:
    used_key, rows = _pick_fold_key(report, fold_key)
    scored = [(row, _metric(row)) for row in rows]
    scored = [(row, metric) for row, metric in scored if metric is not None]
    scored.sort(key=lambda item: item[1])
    worst = [row for row, _ in scored[:worst_count]]
    best = [row for row, _ in scored[-best_count:]][::-1]
    metrics = [metric for _, metric in scored]
    low_threshold = 0.2
    extreme_low = [row for row, metric in scored if metric < low_threshold]
    return {
        "generated_at": _utc_now_iso(),
        "source_evaluation_id": report.get("evaluation_id"),
        "source_evaluated_at": report.get("evaluated_at"),
        "source_fold_key": used_key,
        "fold_count": len(scored),
        "overall_three_class_accuracy": report.get("three_class_accuracy") or report.get("overall_accuracy"),
        "walk_forward_gate_status": report.get("walk_forward_gate_status"),
        "min_accuracy": min(metrics) if metrics else None,
        "max_accuracy": max(metrics) if metrics else None,
        "low_accuracy_threshold": low_threshold,
        "extreme_low_count": len(extreme_low),
        "worst_folds": worst,
        "best_folds": best,
        "assessment": {
            "status": "needs_review" if extreme_low else "ok",
            "summary": (
                f"{len(extreme_low)} fold(s) below {low_threshold:.3f} accuracy"
                if extreme_low
                else "no extreme low-accuracy folds found"
            ),
        },
    }


def _compact_fold(row: dict[str, Any]) -> dict[str, Any]:
    preferred = (
        "fold_index",
        "fold",
        "train_start",
        "train_end",
        "test_start",
        "test_end",
        "rows_evaluated",
        "three_class_accuracy",
        "overall_accuracy",
        "accuracy",
        "class_hit_rates",
        "virtual_direction_cumulative_net_return_pct",
        "cumulative_net_return_pct",
    )
    compact = {key: row[key] for key in preferred if key in row}
    if compact:
        return compact
    return {key: row[key] for key in list(row)[:12]}


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Walk-Forward Extreme Fold Summary",
        "",
        f"- generated_at: `{summary.get('generated_at')}`",
        f"- source_evaluation_id: `{summary.get('source_evaluation_id')}`",
        f"- source_fold_key: `{summary.get('source_fold_key')}`",
        f"- fold_count: `{summary.get('fold_count')}`",
        f"- overall_three_class_accuracy: `{summary.get('overall_three_class_accuracy')}`",
        f"- min_accuracy: `{summary.get('min_accuracy')}`",
        f"- max_accuracy: `{summary.get('max_accuracy')}`",
        f"- assessment: `{summary.get('assessment', {}).get('status')}` - {summary.get('assessment', {}).get('summary')}",
        "",
        "## Worst Folds",
        "",
    ]
    for row in summary.get("worst_folds", []):
        lines.append(f"- `{json.dumps(_compact_fold(row), ensure_ascii=False, default=str)}`")
    lines.extend(["", "## Best Folds", ""])
    for row in summary.get("best_folds", []):
        lines.append(f"- `{json.dumps(_compact_fold(row), ensure_ascii=False, default=str)}`")
    lines.extend(
        [
            "",
            "## Interpretation Guardrails",
            "",
            "- Extreme folds do not identify a cause by themselves.",
            "- Use this report to pick periods for follow-up regime, liquidity, data-quality, or market-event analysis.",
            "",
            "관련 문서/코드 경로:",
            "`scripts/summarize_walk_forward_extreme_folds.py`,",
            "`runtime-data/reports/backtests/latest-walk-forward-h15.json`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fold-key", default=None)
    parser.add_argument("--worst-count", type=int, default=10)
    parser.add_argument("--best-count", type=int, default=5)
    args = parser.parse_args()

    report = json.loads(args.input.read_text(encoding="utf-8"))
    summary = build_summary(
        report,
        fold_key=args.fold_key,
        worst_count=max(1, args.worst_count),
        best_count=max(1, args.best_count),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "latest-walk-forward-extreme-folds-h15.json"
    md_path = args.output_dir / "latest-walk-forward-extreme-folds-h15.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"ok": True, "json_path": str(json_path), "markdown_path": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
