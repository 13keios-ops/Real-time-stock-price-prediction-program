"""Runtime reporting services for quick operational review."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config.settings import load_settings
from app.models.registry import ModelRegistry
from app.observability.logging import configure_logging
from app.services.live_alerting import LiveAlertOutbox, build_live_monitoring_alerts
from app.services.live_audit import verify_live_audit_chain
from app.services.live_execution_sync import build_live_order_fill_consistency_summary_from_store
from app.services.live_order_monitoring import (
    build_live_order_attention_summary_from_store,
    build_live_phase2_parent_order_limit_summary_from_store,
    live_order_attention_summary_to_dict,
    live_phase2_parent_order_limit_summary_to_dict,
)
from app.services.paper_alignment import apply_alignment_baseline
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
    live_order_rows = sqlite_store.fetch_all_rows("live_orders", "created_at")
    live_fill_trading_day = str(live_order_rows[-1]["trading_day"]) if live_order_rows else None
    live_fill_consistency = _build_live_fill_consistency_report(
        sqlite_store,
        trading_day=live_fill_trading_day,
    )
    live_order_attention = _build_live_order_attention_report(
        sqlite_store,
        trading_day=live_fill_trading_day,
    )
    live_phase2_parent_order_limit = _build_live_phase2_parent_order_limit_report(
        sqlite_store,
        trading_day=live_fill_trading_day,
    )
    live_audit_integrity = _build_live_audit_integrity_report(
        sqlite_store,
        trading_day=live_fill_trading_day,
    )
    live_alert_outbox = _write_live_monitoring_alert_outbox(
        settings.runtime_data_dir,
        created_at=datetime.now().astimezone(),
        live_fill_consistency=live_fill_consistency,
        live_order_attention=live_order_attention,
    )

    summary = {
        "raw_market_ticks": sqlite_store.count_rows("raw_market_ticks"),
        "raw_orderbook_ticks": sqlite_store.count_rows("raw_orderbook_ticks"),
        "minute_bars": sqlite_store.count_rows("curated_minute_bars"),
        "feature_rows": sqlite_store.count_rows("feature_model_inputs"),
        "labels": sqlite_store.count_rows("feature_labels"),
        "predictions": sqlite_store.count_rows("serving_predictions"),
        "signals": sqlite_store.count_rows("serving_trade_signals"),
        "decisions": sqlite_store.count_rows("serving_decision_ledger"),
        "orders": sqlite_store.count_rows("paper_orders"),
        "fills": sqlite_store.count_rows("paper_fills"),
        "broker_order_submissions": sqlite_store.count_rows("broker_paper_order_submissions"),
        "broker_order_status_snapshots": sqlite_store.count_rows("broker_paper_order_status_snapshots"),
        "live_orders": sqlite_store.count_rows("live_orders"),
        "live_fills": sqlite_store.count_rows("live_fills"),
        "live_fill_mismatches": live_fill_consistency["mismatch_count"],
        "live_order_attention": live_order_attention["attention_count"],
        "live_open_orders": live_order_attention["open_order_count"],
        "live_phase2_parent_orders": live_phase2_parent_order_limit["parent_order_count"],
        "live_phase2_parent_order_limit_blocked": live_phase2_parent_order_limit["blocked_by_limit"],
        "live_audit_integrity_issues": live_audit_integrity["issue_count"],
        "live_alerts": live_alert_outbox["alert_count"],
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
    latest_position_rows = [dict(row) for row in sqlite_store.fetch_all_rows("paper_positions", "symbol")]
    latest_snapshot_row = dict(latest_snapshot) if latest_snapshot else None
    latest_snapshot_row, latest_position_rows, _ = apply_alignment_baseline(
        latest_snapshot=latest_snapshot_row,
        position_rows=latest_position_rows,
        runtime_data_dir=settings.runtime_data_dir,
    )
    registry_payload = ModelRegistry(settings.runtime_data_dir).load()
    latest_challenger_report_path = settings.runtime_data_dir / "reports" / "challengers" / "latest-challengers-h15.json"
    latest_challenger_report = (
        json.loads(latest_challenger_report_path.read_text(encoding="utf-8"))
        if latest_challenger_report_path.exists()
        else None
    )
    latest_reconciliation_path = settings.runtime_data_dir / "reports" / "reconciliation" / "latest-paper-account-sync.json"
    latest_reconciliation_report = (
        json.loads(latest_reconciliation_path.read_text(encoding="utf-8"))
        if latest_reconciliation_path.exists()
        else None
    )
    latest_broker_sync_path = settings.runtime_data_dir / "reports" / "broker-paper" / "latest-sync.json"
    latest_broker_sync_report = (
        json.loads(latest_broker_sync_path.read_text(encoding="utf-8"))
        if latest_broker_sync_path.exists()
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
        "latest_broker_sync": latest_broker_sync_report,
        "latest_paper_reconciliation": latest_reconciliation_report,
        "live_fill_consistency": live_fill_consistency,
        "live_order_attention": live_order_attention,
        "live_phase2_parent_order_limit": live_phase2_parent_order_limit,
        "live_audit_integrity": live_audit_integrity,
        "live_alert_outbox": live_alert_outbox,
        "latest_portfolio_snapshot": latest_snapshot_row,
        "positions": latest_position_rows,
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

    markdown_lines.extend(["", "## Latest Paper Reconciliation", ""])
    if latest_reconciliation_report:
        comparison = latest_reconciliation_report.get("comparison") or {}
        markdown_lines.append(f"- `status`: {comparison.get('status')}")
        markdown_lines.append(f"- `mismatch_count`: {comparison.get('mismatch_count')}")
        markdown_lines.append(f"- `cash_gap`: {comparison.get('cash_gap')}")
        markdown_lines.append(f"- `total_asset_gap`: {comparison.get('total_asset_gap')}")
        markdown_lines.append(f"- `note`: {comparison.get('note')}")
    else:
        markdown_lines.append("- No paper-account reconciliation report recorded.")

    markdown_lines.extend(["", "## Live Fill Consistency", ""])
    markdown_lines.append(f"- `trading_day`: {live_fill_consistency.get('trading_day')}")
    markdown_lines.append(f"- `status`: {live_fill_consistency.get('status')}")
    markdown_lines.append(f"- `checked_order_count`: {live_fill_consistency.get('checked_order_count')}")
    markdown_lines.append(f"- `mismatch_count`: {live_fill_consistency.get('mismatch_count')}")
    if live_fill_consistency.get("error"):
        markdown_lines.append(f"- `error`: {live_fill_consistency.get('error')}")
    mismatches = live_fill_consistency.get("mismatches") or []
    if mismatches:
        for item in mismatches:
            markdown_lines.append(
                f"- `{item['order_id']}` order_filled_qty={item['order_filled_qty']} "
                f"live_fill_qty_sum={item['live_fill_qty_sum']}"
            )
    else:
        markdown_lines.append("- No live fill mismatches recorded.")

    markdown_lines.extend(["", "## Live Order Attention", ""])
    markdown_lines.append(f"- `trading_day`: {live_order_attention.get('trading_day')}")
    markdown_lines.append(f"- `status`: {live_order_attention.get('status')}")
    markdown_lines.append(f"- `checked_order_count`: {live_order_attention.get('checked_order_count')}")
    markdown_lines.append(f"- `open_order_count`: {live_order_attention.get('open_order_count')}")
    markdown_lines.append(f"- `attention_count`: {live_order_attention.get('attention_count')}")
    markdown_lines.append(f"- `max_attention_age_minutes`: {live_order_attention.get('max_attention_age_minutes')}")
    if live_order_attention.get("error"):
        markdown_lines.append(f"- `error`: {live_order_attention.get('error')}")
    attention_orders = live_order_attention.get("attention_orders") or []
    if attention_orders:
        for item in attention_orders:
            markdown_lines.append(
                f"- `{item['order_id']}` status={item['status']} symbol={item['symbol']} "
                f"remaining_qty={item['remaining_qty']} age_minutes={item['age_minutes']}"
            )
    else:
        markdown_lines.append("- No unknown/stuck live orders recorded.")

    markdown_lines.extend(["", "## Live Phase 2 Parent Order Limit", ""])
    markdown_lines.append(f"- `trading_day`: {live_phase2_parent_order_limit.get('trading_day')}")
    markdown_lines.append(f"- `status`: {live_phase2_parent_order_limit.get('status')}")
    markdown_lines.append(f"- `max_parent_orders_per_day`: {live_phase2_parent_order_limit.get('max_parent_orders_per_day')}")
    markdown_lines.append(f"- `parent_order_count`: {live_phase2_parent_order_limit.get('parent_order_count')}")
    markdown_lines.append(f"- `remaining_parent_orders`: {live_phase2_parent_order_limit.get('remaining_parent_orders')}")
    markdown_lines.append(f"- `blocked_by_limit`: {live_phase2_parent_order_limit.get('blocked_by_limit')}")
    if live_phase2_parent_order_limit.get("error"):
        markdown_lines.append(f"- `error`: {live_phase2_parent_order_limit.get('error')}")
    parent_orders = live_phase2_parent_order_limit.get("parent_orders") or []
    if parent_orders:
        for item in parent_orders:
            markdown_lines.append(
                f"- `{item['order_id']}` status={item['status']} phase={item['phase']} "
                f"symbol={item['symbol']} qty={item['qty']}"
            )
    else:
        markdown_lines.append("- No Phase 2 parent orders counted for the report trading day.")

    markdown_lines.extend(["", "## Live Audit Integrity", ""])
    markdown_lines.append(f"- `trading_day`: {live_audit_integrity.get('trading_day')}")
    markdown_lines.append(f"- `status`: {live_audit_integrity.get('status')}")
    markdown_lines.append(f"- `checked_count`: {live_audit_integrity.get('checked_count')}")
    markdown_lines.append(f"- `issue_count`: {live_audit_integrity.get('issue_count')}")
    markdown_lines.append(f"- `latest_hash`: {live_audit_integrity.get('latest_hash')}")
    if live_audit_integrity.get("error"):
        markdown_lines.append(f"- `error`: {live_audit_integrity.get('error')}")
    issues = live_audit_integrity.get("issues") or []
    if issues:
        for item in issues:
            markdown_lines.append(
                f"- `{item['audit_event_id']}` code={item['code']} message={item['message']}"
            )
    else:
        markdown_lines.append("- No live audit integrity issues recorded.")

    markdown_lines.extend(["", "## Live Alert Outbox", ""])
    markdown_lines.append(f"- `status`: {live_alert_outbox.get('status')}")
    markdown_lines.append(f"- `alert_count`: {live_alert_outbox.get('alert_count')}")
    markdown_lines.append(f"- `queued_count`: {live_alert_outbox.get('queued_count')}")
    markdown_lines.append(f"- `error_count`: {live_alert_outbox.get('error_count')}")
    markdown_lines.append(f"- `outbox_root`: {live_alert_outbox.get('outbox_root')}")
    for item in live_alert_outbox.get("routes") or []:
        markdown_lines.append(
            f"- `{item['alert_id']}` event_type={item['event_type']} "
            f"severity={item['severity']} channels={item['channels']}"
        )

    markdown_lines.extend(["", "## Latest Broker Paper Sync", ""])
    if latest_broker_sync_report:
        for key, value in latest_broker_sync_report.items():
            markdown_lines.append(f"- `{key}`: {value}")
    else:
        markdown_lines.append("- No broker paper sync report recorded.")

    markdown_lines.extend(["", "## Latest Portfolio Snapshot", ""])
    if latest_snapshot_row:
        markdown_lines.extend(f"- `{key}`: {value}" for key, value in latest_snapshot_row.items())
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


def _build_live_fill_consistency_report(sqlite_store, *, trading_day: str | None) -> dict[str, object]:
    if not trading_day:
        return {
            "status": "empty",
            "trading_day": None,
            "checked_order_count": 0,
            "mismatch_count": 0,
            "mismatches": [],
            "error": None,
        }
    try:
        summary = build_live_order_fill_consistency_summary_from_store(sqlite_store, trading_day=trading_day)
    except Exception as exc:  # pragma: no cover - report must survive partial live schema states.
        return {
            "status": "unknown",
            "trading_day": trading_day,
            "checked_order_count": 0,
            "mismatch_count": 0,
            "mismatches": [],
            "error": str(exc),
        }
    status = "empty" if summary.checked_order_count == 0 else "ok" if summary.ok else "mismatch"
    return {
        "status": status,
        "trading_day": summary.trading_day,
        "checked_order_count": summary.checked_order_count,
        "mismatch_count": summary.mismatch_count,
        "mismatches": [
            {
                "order_id": item.order_id,
                "order_filled_qty": item.order_filled_qty,
                "live_fill_qty_sum": item.live_fill_qty_sum,
            }
            for item in summary.mismatches
        ],
        "error": None,
    }


def _build_live_order_attention_report(sqlite_store, *, trading_day: str | None) -> dict[str, object]:
    if not trading_day:
        return {
            "status": "empty",
            "trading_day": None,
            "checked_order_count": 0,
            "open_order_count": 0,
            "attention_count": 0,
            "max_attention_age_minutes": None,
            "attention_orders": [],
            "error": None,
        }
    try:
        summary = build_live_order_attention_summary_from_store(
            sqlite_store,
            trading_day=trading_day,
            now=datetime.now().astimezone(),
        )
    except Exception as exc:  # pragma: no cover - report must survive partial live schema states.
        return {
            "status": "unknown",
            "trading_day": trading_day,
            "checked_order_count": 0,
            "open_order_count": 0,
            "attention_count": 0,
            "max_attention_age_minutes": None,
            "attention_orders": [],
            "error": str(exc),
        }
    return live_order_attention_summary_to_dict(summary)


def _build_live_phase2_parent_order_limit_report(sqlite_store, *, trading_day: str | None) -> dict[str, object]:
    if not trading_day:
        return {
            "status": "empty",
            "trading_day": None,
            "max_parent_orders_per_day": 1,
            "checked_order_count": 0,
            "parent_order_count": 0,
            "blocked_parent_order_count": 0,
            "remaining_parent_orders": 1,
            "blocked_by_limit": False,
            "parent_orders": [],
            "error": None,
        }
    try:
        summary = build_live_phase2_parent_order_limit_summary_from_store(sqlite_store, trading_day=trading_day)
    except Exception as exc:  # pragma: no cover - report must survive partial live schema states.
        return {
            "status": "unknown",
            "trading_day": trading_day,
            "max_parent_orders_per_day": 1,
            "checked_order_count": 0,
            "parent_order_count": 0,
            "blocked_parent_order_count": 0,
            "remaining_parent_orders": 0,
            "blocked_by_limit": False,
            "parent_orders": [],
            "error": str(exc),
        }
    return live_phase2_parent_order_limit_summary_to_dict(summary)


def _build_live_audit_integrity_report(sqlite_store, *, trading_day: str | None) -> dict[str, object]:
    if not trading_day:
        return {
            "status": "empty",
            "trading_day": None,
            "checked_count": 0,
            "issue_count": 0,
            "latest_hash": None,
            "issues": [],
            "error": None,
        }
    try:
        rows = sqlite_store.fetch_live_audit_events(trading_day=trading_day)
        verification = verify_live_audit_chain(rows)
    except Exception as exc:  # pragma: no cover - report must survive partial live schema states.
        return {
            "status": "unknown",
            "trading_day": trading_day,
            "checked_count": 0,
            "issue_count": 0,
            "latest_hash": None,
            "issues": [],
            "error": str(exc),
        }
    status = "empty" if verification.checked_count == 0 else "ok" if verification.ok else "mismatch"
    return {
        "status": status,
        "trading_day": trading_day,
        "checked_count": verification.checked_count,
        "issue_count": len(verification.issues),
        "latest_hash": verification.latest_hash if verification.checked_count else None,
        "issues": [
            {
                "index": item.index,
                "audit_event_id": item.audit_event_id,
                "code": item.code,
                "message": item.message,
            }
            for item in verification.issues
        ],
        "error": None,
    }


def _write_live_monitoring_alert_outbox(
    runtime_data_dir: Path,
    *,
    created_at: datetime,
    live_fill_consistency: dict[str, object],
    live_order_attention: dict[str, object],
) -> dict[str, object]:
    alerts_root = runtime_data_dir / "reports" / "alerts"
    alerts = build_live_monitoring_alerts(
        created_at=created_at,
        live_fill_consistency=live_fill_consistency,
        live_order_attention=live_order_attention,
        source="runtime_report",
    )
    outbox = LiveAlertOutbox(alerts_root)
    routes: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for alert in alerts:
        try:
            route = outbox.write_alert(alert)
        except Exception as exc:  # pragma: no cover - report generation must survive alert I/O failures.
            errors.append(
                {
                    "alert_id": alert.alert_id,
                    "event_type": alert.event_type,
                    "error": str(exc),
                }
            )
            continue
        routes.append(
            {
                "alert_id": alert.alert_id,
                "event_type": alert.event_type,
                "severity": alert.severity,
                "channels": list(route.channels),
                "written_channels": list(route.written_channels),
                "suppressed_channels": list(route.suppressed_channels),
                "important": route.important,
            }
        )
    if not alerts:
        status = "empty"
    elif errors:
        status = "partial_error"
    elif routes and all(item.get("suppressed_channels") and not item.get("written_channels") for item in routes):
        status = "duplicate_suppressed"
    else:
        status = "queued"
    queued_count = sum(1 for item in routes if item.get("written_channels"))
    suppressed_count = sum(1 for item in routes if item.get("suppressed_channels") and not item.get("written_channels"))
    return {
        "status": status,
        "alert_count": len(alerts),
        "queued_count": queued_count,
        "suppressed_count": suppressed_count,
        "error_count": len(errors),
        "outbox_root": str(alerts_root),
        "routes": routes,
        "errors": errors,
        "delivery_mode": "outbox_only",
    }
