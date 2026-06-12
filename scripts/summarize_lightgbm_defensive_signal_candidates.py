#!/usr/bin/env python3
"""Summarize LightGBM downside/avoid defensive-signal candidates.

This is a research-only bridge from diagnostics to a plan-B paper-shadow test.
It does not change the active model, thresholds, gates, or paper/live orders.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIAGNOSTICS = (
    REPO_ROOT / "runtime-data" / "reports" / "challengers" / "latest-lightgbm-performance-diagnostics-h15.json"
)
DEFAULT_CALIBRATION = (
    REPO_ROOT / "runtime-data" / "reports" / "challengers" / "latest-lightgbm-calibration-experiment-h15.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "challengers"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"_missing": True, "_path": str(path)}
    return json.loads(path.read_text(encoding="utf-8"))


def _downside_rows_from_sweep(source_name: str, sweep: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in sweep:
        by_label = item.get("by_predicted_label") or {}
        down = by_label.get("down") or {}
        up = by_label.get("up") or {}
        rows.append(
            {
                "source_name": source_name,
                "threshold": item.get("threshold"),
                "direction_trades_taken": item.get("direction_trades_taken"),
                "coverage_rate": item.get("coverage_rate"),
                "down_trades": down.get("trades"),
                "down_hit_rate": down.get("hit_rate"),
                "down_win_rate": down.get("win_rate"),
                "down_average_net_return_pct": down.get("average_net_return_pct"),
                "down_cumulative_net_return_pct": down.get("cumulative_net_return_pct"),
                "up_trades": up.get("trades"),
                "up_cumulative_net_return_pct": up.get("cumulative_net_return_pct"),
            }
        )
    return rows


def _candidate_score(row: dict[str, Any]) -> tuple[float, int, float]:
    net = row.get("down_cumulative_net_return_pct")
    trades = row.get("down_trades")
    hit = row.get("down_hit_rate")
    return (
        float(net) if isinstance(net, (int, float)) else float("-inf"),
        int(trades) if isinstance(trades, int) else 0,
        float(hit) if isinstance(hit, (int, float)) else 0.0,
    )


def build_summary(diagnostics: dict[str, Any], calibration: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    rows.extend(_downside_rows_from_sweep("performance-diagnostics", diagnostics.get("direction_threshold_sweep") or []))
    for candidate in calibration.get("candidates") or []:
        name = candidate.get("candidate_name") or "calibration-candidate"
        rows.extend(_downside_rows_from_sweep(str(name), candidate.get("direction_threshold_sweep") or []))
    positive = [
        row
        for row in rows
        if isinstance(row.get("down_cumulative_net_return_pct"), (int, float))
        and row["down_cumulative_net_return_pct"] > 0
        and isinstance(row.get("down_trades"), int)
        and row["down_trades"] > 0
    ]
    positive.sort(key=_candidate_score, reverse=True)
    top = positive[:12]
    return {
        "generated_at": _now_iso(),
        "source_reports": {
            "performance_diagnostics": str(DEFAULT_DIAGNOSTICS),
            "calibration_experiment": str(DEFAULT_CALIBRATION),
        },
        "status": "defensive_candidates_found" if top else "no_positive_downside_candidates",
        "automatic_promotion": False,
        "automatic_threshold_adoption": False,
        "automatic_order_change": False,
        "candidate_count": len(positive),
        "top_candidates": top,
        "interpretation": {
            "summary": (
                "downside evidence can be tested as buy-avoid or early-exit paper-shadow filters"
                if top
                else "no downside candidate has positive net evidence in the available diagnostics"
            ),
            "not_a_live_short_signal": True,
            "not_a_buy_promotion_signal": True,
            "requires_paper_shadow_test": True,
        },
    }


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join("" if value is None else str(value) for value in row) + " |")
    return "\n".join(lines)


def render_markdown(summary: dict[str, Any]) -> str:
    rows = []
    for item in summary.get("top_candidates", []):
        rows.append(
            [
                item.get("source_name"),
                item.get("threshold"),
                item.get("down_trades"),
                item.get("down_hit_rate"),
                item.get("down_win_rate"),
                item.get("down_average_net_return_pct"),
                item.get("down_cumulative_net_return_pct"),
                item.get("up_cumulative_net_return_pct"),
            ]
        )
    lines = [
        "# LightGBM Defensive Signal Candidates",
        "",
        f"- generated_at: `{summary.get('generated_at')}`",
        f"- status: `{summary.get('status')}`",
        f"- candidate_count: `{summary.get('candidate_count')}`",
        "- automatic_promotion: `false`",
        "- automatic_threshold_adoption: `false`",
        "- automatic_order_change: `false`",
        "",
        "## Top Downside Candidates",
        "",
        _markdown_table(
            [
                "source",
                "threshold",
                "down_trades",
                "down_hit_rate",
                "down_win_rate",
                "down_avg_net_pct",
                "down_cum_net_pct",
                "up_cum_net_pct",
            ],
            rows,
        )
        if rows
        else "No positive downside candidates.",
        "",
        "## Interpretation",
        "",
        "- These rows are research-only evidence for buy-avoid or early-exit filters.",
        "- They are not live short signals and not LightGBM buy-promotion evidence.",
        "- Next validation must compare baseline-only vs baseline plus defensive filter in paper shadow.",
        "",
        "관련 문서/코드 경로:",
        "`scripts/summarize_lightgbm_defensive_signal_candidates.py`,",
        "`runtime-data/reports/challengers/latest-lightgbm-performance-diagnostics-h15.json`,",
        "`runtime-data/reports/challengers/latest-lightgbm-calibration-experiment-h15.json`",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostics", type=Path, default=DEFAULT_DIAGNOSTICS)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    summary = build_summary(_read_optional_json(args.diagnostics), _read_optional_json(args.calibration))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "latest-lightgbm-defensive-signal-candidates-h15.json"
    md_path = args.output_dir / "latest-lightgbm-defensive-signal-candidates-h15.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"ok": True, "json_path": str(json_path), "markdown_path": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
