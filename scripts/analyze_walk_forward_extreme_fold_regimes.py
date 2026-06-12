#!/usr/bin/env python3
"""Analyze market/data regimes around extreme walk-forward folds.

This read-only diagnostic joins the latest gate walk-forward fold summaries
with closed h15 labels and minute bars.  It does not retrain models or change
any model, gate, threshold, order, or config state.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WALK_FORWARD = REPO_ROOT / "runtime-data" / "reports" / "backtests" / "latest-walk-forward-h15.json"
DEFAULT_DATABASE = REPO_ROOT / "runtime-data" / "dev.db"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime-data" / "reports" / "backtests"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _metric(row: dict[str, Any]) -> float | None:
    for key in ("three_class_accuracy", "overall_accuracy", "accuracy"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _confusion_counts(confusion: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    actual: dict[str, int] = {}
    predicted: dict[str, int] = {}
    for actual_label, columns in (confusion or {}).items():
        if not isinstance(columns, dict):
            continue
        actual_count = 0
        for predicted_label, count_raw in columns.items():
            try:
                count = int(count_raw)
            except (TypeError, ValueError):
                continue
            actual_count += count
            predicted[str(predicted_label)] = predicted.get(str(predicted_label), 0) + count
        actual[str(actual_label)] = actual.get(str(actual_label), 0) + actual_count
    return actual, predicted


def _label_distribution(
    connection: sqlite3.Connection,
    *,
    start_at: str,
    end_at: str,
    horizon_min: int,
) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT label, COUNT(1) AS row_count, AVG(future_return_pct) AS avg_return,
               MIN(future_return_pct) AS min_return, MAX(future_return_pct) AS max_return
        FROM feature_labels
        WHERE horizon_min = ?
          AND event_time >= ?
          AND event_time <= ?
          AND future_return_pct IS NOT NULL
        GROUP BY label
        ORDER BY label
        """,
        (horizon_min, start_at, end_at),
    ).fetchall()
    labels: dict[str, dict[str, Any]] = {}
    total = 0
    for row in rows:
        count = int(row["row_count"])
        total += count
        labels[str(row["label"])] = {
            "rows": count,
            "avg_future_return_pct": row["avg_return"],
            "min_future_return_pct": row["min_return"],
            "max_future_return_pct": row["max_return"],
        }
    for item in labels.values():
        item["share"] = item["rows"] / total if total else 0.0
    symbol_count = connection.execute(
        """
        SELECT COUNT(DISTINCT symbol)
        FROM feature_labels
        WHERE horizon_min = ?
          AND event_time >= ?
          AND event_time <= ?
        """,
        (horizon_min, start_at, end_at),
    ).fetchone()[0]
    return {
        "rows": total,
        "symbols": int(symbol_count or 0),
        "labels": labels,
    }


def _bar_regime(connection: sqlite3.Connection, *, start_at: str, end_at: str) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT symbol, bar_time, close
        FROM curated_minute_bars
        WHERE bar_time >= ?
          AND bar_time <= ?
          AND close IS NOT NULL
        ORDER BY symbol ASC, bar_time ASC
        """,
        (start_at, end_at),
    ).fetchall()
    by_symbol: dict[str, list[float]] = {}
    for row in rows:
        try:
            close = float(row["close"])
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        by_symbol.setdefault(str(row["symbol"]), []).append(close)
    symbol_returns: list[float] = []
    minute_returns: list[float] = []
    for closes in by_symbol.values():
        if len(closes) < 2:
            continue
        symbol_returns.append((closes[-1] - closes[0]) / closes[0] * 100.0)
        for left, right in zip(closes, closes[1:]):
            if left > 0:
                minute_returns.append((right - left) / left * 100.0)
    avg_symbol_return = sum(symbol_returns) / len(symbol_returns) if symbol_returns else None
    if len(minute_returns) >= 2:
        mean = sum(minute_returns) / len(minute_returns)
        variance = sum((value - mean) ** 2 for value in minute_returns) / (len(minute_returns) - 1)
        minute_volatility = math.sqrt(variance)
    else:
        minute_volatility = None
    return {
        "bar_rows": len(rows),
        "symbols": len(by_symbol),
        "avg_symbol_period_return_pct": avg_symbol_return,
        "min_symbol_period_return_pct": min(symbol_returns) if symbol_returns else None,
        "max_symbol_period_return_pct": max(symbol_returns) if symbol_returns else None,
        "minute_return_volatility_pct": minute_volatility,
    }


def _dominant_share(counts: dict[str, int]) -> tuple[str | None, float]:
    total = sum(counts.values())
    if not total:
        return None, 0.0
    label, count = max(counts.items(), key=lambda item: item[1])
    return label, count / total


def _hypotheses(fold: dict[str, Any], label_dist: dict[str, Any], bar_regime: dict[str, Any]) -> list[str]:
    hypotheses: list[str] = []
    actual_counts, predicted_counts = _confusion_counts(fold.get("confusion_matrix") or {})
    actual_label, actual_share = _dominant_share(actual_counts)
    predicted_label, predicted_share = _dominant_share(predicted_counts)
    if actual_label and actual_share >= 0.55:
        hypotheses.append(f"actual_label_imbalance:{actual_label}:{actual_share:.2f}")
    if predicted_label and predicted_share >= 0.55:
        hypotheses.append(f"prediction_bias:{predicted_label}:{predicted_share:.2f}")
    for label in ("up", "down", "flat"):
        value = fold.get(f"{label}_hit_rate")
        if isinstance(value, (int, float)) and value < 0.20:
            hypotheses.append(f"low_{label}_hit_rate:{value:.2f}")
    net = fold.get("virtual_direction_cumulative_net_return_pct")
    if isinstance(net, (int, float)) and net < 0:
        hypotheses.append(f"negative_virtual_direction_net:{net:.2f}")
    volatility = bar_regime.get("minute_return_volatility_pct")
    if isinstance(volatility, (int, float)) and volatility > 0.40:
        hypotheses.append(f"high_minute_volatility:{volatility:.2f}")
    avg_return = bar_regime.get("avg_symbol_period_return_pct")
    if isinstance(avg_return, (int, float)) and abs(avg_return) > 5:
        hypotheses.append(f"large_period_drift:{avg_return:.2f}")
    if label_dist.get("rows", 0) == 0:
        hypotheses.append("no_closed_labels_in_db_window")
    return hypotheses


def _analyze_fold(connection: sqlite3.Connection, fold: dict[str, Any], *, horizon_min: int) -> dict[str, Any]:
    start_at = str(fold.get("test_start_event_time"))
    end_at = str(fold.get("test_end_event_time"))
    actual_counts, predicted_counts = _confusion_counts(fold.get("confusion_matrix") or {})
    label_dist = _label_distribution(connection, start_at=start_at, end_at=end_at, horizon_min=horizon_min)
    bar_regime = _bar_regime(connection, start_at=start_at, end_at=end_at)
    return {
        "fold": fold.get("fold"),
        "test_start_event_time": start_at,
        "test_end_event_time": end_at,
        "three_class_accuracy": fold.get("three_class_accuracy") or fold.get("overall_accuracy"),
        "up_hit_rate": fold.get("up_hit_rate"),
        "flat_hit_rate": fold.get("flat_hit_rate"),
        "down_hit_rate": fold.get("down_hit_rate"),
        "virtual_direction_cumulative_net_return_pct": fold.get("virtual_direction_cumulative_net_return_pct"),
        "actual_label_counts_from_fold": actual_counts,
        "predicted_label_counts_from_fold": predicted_counts,
        "closed_label_distribution_from_db": label_dist,
        "bar_regime": bar_regime,
        "hypotheses": _hypotheses(fold, label_dist, bar_regime),
    }


def build_summary(
    report: dict[str, Any],
    *,
    database_path: Path,
    horizon_min: int,
    worst_count: int,
    best_count: int,
) -> dict[str, Any]:
    folds = [row for row in report.get("fold_summaries", []) if isinstance(row, dict) and _metric(row) is not None]
    folds.sort(key=lambda item: float(_metric(item) or 0.0))
    worst = folds[:worst_count]
    best = list(reversed(folds[-best_count:]))
    with _connect_readonly(database_path) as connection:
        worst_analysis = [_analyze_fold(connection, fold, horizon_min=horizon_min) for fold in worst]
        best_analysis = [_analyze_fold(connection, fold, horizon_min=horizon_min) for fold in best]
    return {
        "generated_at": _now_iso(),
        "source_evaluation_id": report.get("evaluation_id"),
        "source_evaluated_at": report.get("evaluated_at"),
        "database_path": str(database_path),
        "horizon_min": horizon_min,
        "fold_count": len(folds),
        "worst_count": len(worst_analysis),
        "best_count": len(best_analysis),
        "automatic_model_change": False,
        "automatic_gate_change": False,
        "automatic_order_change": False,
        "worst_folds": worst_analysis,
        "best_folds": best_analysis,
        "interpretation": {
            "summary": "Extreme fold periods are analyzed for label imbalance, prediction bias, return drift, and minute volatility.",
            "cause_is_hypothesis_not_proof": True,
            "recommended_next_step": "Use worst-fold periods as focused windows for feature/regime diagnostics before changing labels or gates.",
        },
    }


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _label_share(label_distribution: dict[str, Any], label: str) -> float | None:
    item = (label_distribution.get("labels") or {}).get(label) or {}
    value = item.get("share")
    return float(value) if isinstance(value, (int, float)) else None


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(value) for value in row) + " |")
    return "\n".join(lines)


def _analysis_rows(items: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for item in items:
        labels = item.get("closed_label_distribution_from_db") or {}
        bars = item.get("bar_regime") or {}
        rows.append(
            [
                item.get("fold"),
                item.get("test_start_event_time"),
                item.get("test_end_event_time"),
                item.get("three_class_accuracy"),
                item.get("up_hit_rate"),
                item.get("flat_hit_rate"),
                item.get("down_hit_rate"),
                _label_share(labels, "up"),
                _label_share(labels, "flat"),
                _label_share(labels, "down"),
                bars.get("avg_symbol_period_return_pct"),
                bars.get("minute_return_volatility_pct"),
                ", ".join(item.get("hypotheses") or []),
            ]
        )
    return rows


def render_markdown(summary: dict[str, Any]) -> str:
    headers = [
        "fold",
        "start",
        "end",
        "acc",
        "up_hit",
        "flat_hit",
        "down_hit",
        "db_up_share",
        "db_flat_share",
        "db_down_share",
        "avg_symbol_ret_pct",
        "minute_vol_pct",
        "hypotheses",
    ]
    lines = [
        "# Walk-Forward Extreme Fold Regime Analysis",
        "",
        f"- generated_at: `{summary.get('generated_at')}`",
        f"- source_evaluation_id: `{summary.get('source_evaluation_id')}`",
        f"- horizon_min: `{summary.get('horizon_min')}`",
        f"- fold_count: `{summary.get('fold_count')}`",
        "- automatic_model_change: `false`",
        "- automatic_gate_change: `false`",
        "- automatic_order_change: `false`",
        "",
        "## Worst Folds",
        "",
        _markdown_table(headers, _analysis_rows(summary.get("worst_folds") or [])),
        "",
        "## Best Folds",
        "",
        _markdown_table(headers, _analysis_rows(summary.get("best_folds") or [])),
        "",
        "## Interpretation Guardrails",
        "",
        "- 원인 후보는 증명값이 아니라 후속 분석 방향이다.",
        "- 라벨이나 gate 기준값은 이 리포트만으로 바꾸지 않는다.",
        "- worst fold 기간은 feature/regime/data-quality 진단의 우선 창으로 사용한다.",
        "",
        "관련 문서/코드 경로:",
        "`scripts/analyze_walk_forward_extreme_fold_regimes.py`,",
        "`runtime-data/reports/backtests/latest-walk-forward-h15.json`,",
        "`runtime-data/dev.db`",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--walk-forward", type=Path, default=DEFAULT_WALK_FORWARD)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--horizon-min", type=int, default=15)
    parser.add_argument("--worst-count", type=int, default=5)
    parser.add_argument("--best-count", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    report = json.loads(args.walk_forward.read_text(encoding="utf-8"))
    summary = build_summary(
        report,
        database_path=args.database_path,
        horizon_min=args.horizon_min,
        worst_count=max(1, args.worst_count),
        best_count=max(1, args.best_count),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"latest-walk-forward-extreme-fold-regimes-h{args.horizon_min}.json"
    md_path = args.output_dir / f"latest-walk-forward-extreme-fold-regimes-h{args.horizon_min}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"ok": True, "json_path": str(json_path), "markdown_path": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
