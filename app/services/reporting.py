"""Runtime reporting services for quick operational review."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import load_settings
from app.models.registry import ModelRegistry
from app.observability.logging import configure_logging
from app.storage.runtime_writer import get_sqlite_store


@dataclass(slots=True)
class RuntimeReportResult:
    report_markdown_path: Path
    report_json_path: Path
    summary: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "report_markdown_path": str(self.report_markdown_path),
            "report_json_path": str(self.report_json_path),
            "summary": self.summary,
        }


def build_runtime_report(project_root: Path) -> RuntimeReportResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        raise ValueError("A sqlite database_url is required for runtime reporting.")

    evaluation_rows = sqlite_store.fetch_all_rows("ml_model_evaluations", "evaluated_at")
    backtest_rows = [row for row in evaluation_rows if str(row["split_name"]).startswith("backtest_")]
    walk_forward_rows = [row for row in evaluation_rows if str(row["split_name"]).startswith("walk_forward_")]
    challenger_rows = [row for row in evaluation_rows if str(row["split_name"]).startswith("challenger_")]

    summary = {
        "raw_market_ticks": sqlite_store.count_rows("raw_market_ticks"),
        "raw_orderbook_ticks": sqlite_store.count_rows("raw_orderbook_ticks"),
        "minute_bars": sqlite_store.count_rows("curated_minute_bars"),
        "feature_rows": sqlite_store.count_rows("feature_model_inputs"),
        "labels": sqlite_store.count_rows("feature_labels"),
        "predictions": sqlite_store.count_rows("serving_predictions"),
        "signals": sqlite_store.count_rows("serving_trade_signals"),
        "orders": sqlite_store.count_rows("paper_orders"),
        "fills": sqlite_store.count_rows("paper_fills"),
        "positions": sqlite_store.count_rows("paper_positions"),
        "portfolio_snapshots": sqlite_store.count_rows("paper_portfolio_snapshots"),
        "training_runs": sqlite_store.count_rows("ml_training_runs"),
        "evaluations": sqlite_store.count_rows("ml_model_evaluations"),
        "backtests": len(backtest_rows),
        "walk_forward_runs": len(walk_forward_rows),
        "challenger_runs": len(challenger_rows),
    }

    latest_training = sqlite_store.fetch_latest_row("ml_training_runs", "completed_at")
    latest_evaluation = sqlite_store.fetch_latest_row("ml_model_evaluations", "evaluated_at")
    latest_backtest = backtest_rows[-1] if backtest_rows else None
    latest_walk_forward = walk_forward_rows[-1] if walk_forward_rows else None
    latest_challenger = challenger_rows[-1] if challenger_rows else None
    latest_snapshot = sqlite_store.fetch_latest_row("paper_portfolio_snapshots", "event_time")
    latest_position_rows = sqlite_store.fetch_all_rows("paper_positions", "symbol")
    registry_payload = ModelRegistry(settings.runtime_data_dir).load()
    latest_challenger_report_path = settings.runtime_data_dir / "reports" / "challengers" / "latest-challengers-h15.json"
    latest_challenger_report = (
        json.loads(latest_challenger_report_path.read_text(encoding="utf-8"))
        if latest_challenger_report_path.exists()
        else None
    )

    def serialize_evaluation(row):
        if row is None:
            return None
        payload = dict(row)
        payload["metrics"] = json.loads(str(payload.pop("metrics_json")))
        return payload

    report_payload = {
        "summary": summary,
        "model_registry": registry_payload,
        "latest_training": dict(latest_training) if latest_training else None,
        "latest_evaluation": serialize_evaluation(latest_evaluation),
        "latest_backtest": serialize_evaluation(latest_backtest),
        "latest_walk_forward": serialize_evaluation(latest_walk_forward),
        "latest_challenger": serialize_evaluation(latest_challenger),
        "latest_challenger_report": latest_challenger_report,
        "latest_portfolio_snapshot": dict(latest_snapshot) if latest_snapshot else None,
        "positions": [dict(row) for row in latest_position_rows],
    }

    report_dir = settings.runtime_data_dir / "reports" / "runtime"
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = report_dir / "latest-runtime-report.md"
    json_path = report_dir / "latest-runtime-report.json"

    markdown_lines = [
        "# Runtime Report",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        markdown_lines.append(f"- `{key}`: {value}")

    markdown_lines.extend(["", "## Latest Training", ""])
    if latest_training:
        markdown_lines.extend(f"- `{key}`: {value}" for key, value in dict(latest_training).items())
    else:
        markdown_lines.append("- No training runs recorded.")

    markdown_lines.extend(["", "## Latest Evaluation", ""])
    if latest_evaluation:
        evaluation_payload = serialize_evaluation(latest_evaluation) or {}
        for key, value in evaluation_payload.items():
            markdown_lines.append(f"- `{key}`: {value}")
    else:
        markdown_lines.append("- No evaluations recorded.")

    markdown_lines.extend(["", "## Latest Backtest", ""])
    if latest_backtest:
        backtest_payload = serialize_evaluation(latest_backtest) or {}
        for key, value in backtest_payload.items():
            markdown_lines.append(f"- `{key}`: {value}")
    else:
        markdown_lines.append("- No backtest evaluations recorded.")

    markdown_lines.extend(["", "## Latest Walk-Forward", ""])
    if latest_walk_forward:
        walk_forward_payload = serialize_evaluation(latest_walk_forward) or {}
        for key, value in walk_forward_payload.items():
            markdown_lines.append(f"- `{key}`: {value}")
    else:
        markdown_lines.append("- No walk-forward evaluations recorded.")

    markdown_lines.extend(["", "## Latest Challenger", ""])
    if latest_challenger_report:
        for key, value in latest_challenger_report.items():
            markdown_lines.append(f"- `{key}`: {value}")
    elif latest_challenger:
        challenger_payload = serialize_evaluation(latest_challenger) or {}
        for key, value in challenger_payload.items():
            markdown_lines.append(f"- `{key}`: {value}")
    else:
        markdown_lines.append("- No challenger evaluations recorded.")

    markdown_lines.extend(["", "## Latest Portfolio Snapshot", ""])
    if latest_snapshot:
        markdown_lines.extend(f"- `{key}`: {value}" for key, value in dict(latest_snapshot).items())
    else:
        markdown_lines.append("- No portfolio snapshots recorded.")

    markdown_lines.extend(["", "## Positions", ""])
    if latest_position_rows:
        for row in latest_position_rows:
            markdown_lines.append(
                f"- `{row['symbol']}` qty={row['qty']} avg={row['avg_price']} last={row['last_price']} "
                f"unrealized={row['unrealized_pnl']} realized={row['realized_pnl']}"
            )
    else:
        markdown_lines.append("- No open or recorded positions.")

    markdown_lines.extend(["", "## Model Registry", ""])
    active_models = registry_payload.get("active_models", {})
    if isinstance(active_models, dict) and active_models:
        for horizon, entry in active_models.items():
            markdown_lines.append(
                f"- `horizon {horizon}` model={entry.get('model_version')} artifact={entry.get('artifact_path')}"
            )
    else:
        markdown_lines.append("- No active model registry entries.")

    markdown_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return RuntimeReportResult(
        report_markdown_path=markdown_path,
        report_json_path=json_path,
        summary=summary,
    )
