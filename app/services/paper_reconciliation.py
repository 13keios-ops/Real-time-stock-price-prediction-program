"""Reconcile local virtual paper state against the broker paper account."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from app.config.settings import AppSettings, load_settings
from app.observability.logging import configure_logging
from app.services.kis_account import KisAccountReportResult, refresh_kis_account_report
from app.services.paper_alignment import (
    adjust_snapshot_for_fills_after_snapshot,
    apply_alignment_baseline,
    filter_rows_after_alignment,
)
from app.services.paper_reconciliation_history import record_paper_reconciliation_history
from app.storage.runtime_writer import get_sqlite_store
from app.utils.time import get_market_session_status, now_local


@dataclass(slots=True)
class PaperAccountReconciliationResult:
    ok: bool
    as_of: str
    status: str
    mismatch_count: int
    comparison: dict[str, Any]
    local_account: dict[str, Any]
    broker_account: dict[str, Any] | None
    report_markdown_path: Path
    report_json_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "as_of": self.as_of,
            "status": self.status,
            "mismatch_count": self.mismatch_count,
            "comparison": self.comparison,
            "local_account": self.local_account,
            "broker_account": self.broker_account,
            "report_markdown_path": str(self.report_markdown_path),
            "report_json_path": str(self.report_json_path),
        }


def _report_paths(runtime_data_dir: Path) -> tuple[Path, Path]:
    report_dir = runtime_data_dir / "reports" / "reconciliation"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir / "latest-paper-account-sync.md", report_dir / "latest-paper-account-sync.json"


def _money_text(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def load_local_paper_account_state(settings: AppSettings) -> dict[str, Any]:
    sqlite_store = get_sqlite_store(settings)
    if sqlite_store is None:
        return {
            "cash_balance": settings.strategy.paper_initial_cash,
            "net_liquidation_value": settings.strategy.paper_initial_cash,
            "positions": [],
            "latest_snapshot_time": None,
            "orders_total": 0,
            "fills_total": 0,
            "broker_order_submissions": 0,
        }

    latest_snapshot = sqlite_store.fetch_latest_row("paper_portfolio_snapshots", "event_time")
    position_rows = [dict(row) for row in sqlite_store.fetch_all_rows("paper_positions", "symbol")]
    latest_snapshot_dict = dict(latest_snapshot) if latest_snapshot is not None else None
    latest_snapshot_dict, position_rows, _ = apply_alignment_baseline(
        latest_snapshot=latest_snapshot_dict,
        position_rows=position_rows,
        runtime_data_dir=settings.runtime_data_dir,
    )
    open_positions = [row for row in position_rows if int(row.get("qty", 0) or 0) > 0]
    order_rows = filter_rows_after_alignment(
        [dict(row) for row in sqlite_store.fetch_all_rows("paper_orders", "event_time")],
        runtime_data_dir=settings.runtime_data_dir,
        time_fields=("event_time",),
    )
    fill_rows = filter_rows_after_alignment(
        [dict(row) for row in sqlite_store.fetch_all_rows("paper_fills", "event_time")],
        runtime_data_dir=settings.runtime_data_dir,
        time_fields=("event_time",),
    )
    broker_submission_rows = filter_rows_after_alignment(
        [dict(row) for row in sqlite_store.fetch_all_rows("broker_paper_order_submissions", "event_time")],
        runtime_data_dir=settings.runtime_data_dir,
        time_fields=("event_time",),
    )

    latest_snapshot_dict = latest_snapshot_dict or {}
    latest_snapshot_dict = adjust_snapshot_for_fills_after_snapshot(
        latest_snapshot_dict,
        order_rows=order_rows,
        fill_rows=fill_rows,
        open_positions=open_positions,
    )
    return {
        "cash_balance": float(latest_snapshot_dict.get("cash_balance", settings.strategy.paper_initial_cash) or settings.strategy.paper_initial_cash),
        "net_liquidation_value": float(latest_snapshot_dict.get("net_liquidation_value", settings.strategy.paper_initial_cash) or settings.strategy.paper_initial_cash),
        "gross_market_value": float(latest_snapshot_dict.get("gross_market_value", 0.0) or 0.0),
        "realized_pnl": float(latest_snapshot_dict.get("realized_pnl", 0.0) or 0.0),
        "unrealized_pnl": float(latest_snapshot_dict.get("unrealized_pnl", 0.0) or 0.0),
        "latest_snapshot_time": latest_snapshot_dict.get("event_time"),
        "snapshot_adjusted_from_fills": bool(latest_snapshot_dict.get("adjusted_from_fills", False)),
        "positions": open_positions,
        "orders_total": len(order_rows),
        "fills_total": len(fill_rows),
        "broker_order_submissions": len(broker_submission_rows),
        "latest_broker_submission_time": broker_submission_rows[-1]["event_time"] if broker_submission_rows else None,
    }


def build_paper_account_reconciliation_payload(
    *,
    local_account_state: dict[str, Any],
    broker_report: dict[str, Any] | None,
    order_mirroring_enabled: bool,
    mirrored_order_count: int,
) -> dict[str, Any]:
    broker_payload = broker_report or {}
    broker_snapshot = broker_payload.get("account_snapshot") or {}
    broker_positions = broker_snapshot.get("positions") or []

    local_positions_map = {
        str(row.get("symbol")): {
            "symbol": str(row.get("symbol")),
            "local_qty": int(row.get("qty", 0) or 0),
            "local_avg_price": float(row.get("avg_price", 0.0) or 0.0),
            "local_last_price": float(row.get("last_price", 0.0) or 0.0),
            "local_market_value": float(row.get("market_value", 0.0) or 0.0),
            "local_realized_pnl": float(row.get("realized_pnl", 0.0) or 0.0),
            "local_unrealized_pnl": float(row.get("unrealized_pnl", 0.0) or 0.0),
        }
        for row in (local_account_state.get("positions") or [])
    }
    broker_positions_map = {
        str(row.get("symbol")): {
            "symbol": str(row.get("symbol")),
            "symbol_name": str(row.get("name") or ""),
            "broker_qty": int(row.get("holding_qty", 0) or 0),
            "broker_orderable_qty": int(row.get("orderable_qty", 0) or 0),
            "broker_avg_price": float(row.get("average_buy_price", 0.0) or 0.0),
            "broker_current_price": float(row.get("current_price", 0.0) or 0.0),
            "broker_evaluation_amount": float(row.get("evaluation_amount", 0.0) or 0.0),
            "broker_profit_loss_amount": float(row.get("evaluation_profit_loss_amount", 0.0) or 0.0),
            "broker_profit_loss_pct": float(row.get("evaluation_profit_loss_pct", 0.0) or 0.0),
        }
        for row in broker_positions
    }

    position_rows: list[dict[str, Any]] = []
    mismatch_rows: list[dict[str, Any]] = []
    for symbol in sorted(set(local_positions_map) | set(broker_positions_map)):
        local_row = local_positions_map.get(symbol, {})
        broker_row = broker_positions_map.get(symbol, {})
        local_qty = int(local_row.get("local_qty", 0) or 0)
        broker_qty = int(broker_row.get("broker_qty", 0) or 0)
        if local_qty == broker_qty and symbol in local_positions_map and symbol in broker_positions_map:
            position_status = "match"
        elif symbol in local_positions_map and symbol not in broker_positions_map:
            position_status = "only_local"
        elif symbol not in local_positions_map and symbol in broker_positions_map:
            position_status = "only_broker"
        else:
            position_status = "qty_mismatch"

        row = {
            "symbol": symbol,
            "symbol_name": broker_row.get("symbol_name") or "",
            "status": position_status,
            "local_qty": local_qty,
            "broker_qty": broker_qty,
            "qty_gap": local_qty - broker_qty,
            "local_avg_price": local_row.get("local_avg_price"),
            "broker_avg_price": broker_row.get("broker_avg_price"),
            "local_market_value": local_row.get("local_market_value"),
            "broker_evaluation_amount": broker_row.get("broker_evaluation_amount"),
        }
        position_rows.append(row)
        if position_status != "match":
            mismatch_rows.append(row)

    local_cash = local_account_state.get("cash_balance")
    broker_raw_cash = broker_snapshot.get("cash_balance")
    local_total = local_account_state.get("net_liquidation_value")
    broker_total = broker_snapshot.get("total_asset_amount")
    if broker_total in (None, "", 0):
        broker_total = broker_snapshot.get("total_evaluation_amount")
    broker_stock_evaluation = broker_snapshot.get("stock_evaluation_amount")
    broker_effective_cash = broker_raw_cash
    if broker_total not in (None, "") and broker_stock_evaluation not in (None, ""):
        broker_effective_cash = float(broker_total) - float(broker_stock_evaluation)
    cash_gap = (
        float(local_cash) - float(broker_effective_cash)
        if local_cash is not None and broker_effective_cash is not None
        else None
    )
    raw_cash_gap = (
        float(local_cash) - float(broker_raw_cash)
        if local_cash is not None and broker_raw_cash is not None
        else None
    )
    total_asset_gap = (float(local_total) - float(broker_total)) if local_total is not None and broker_total is not None else None
    positions_match = len(mismatch_rows) == 0
    balance_match = cash_gap is not None and abs(cash_gap) < 10_000.0
    total_asset_match = total_asset_gap is not None and abs(total_asset_gap) < 10_000.0

    if not broker_payload.get("ok"):
        status = "broker_unavailable"
        note = "브로커 모의계좌 조회에 실패했거나 아직 조회 결과가 준비되지 않았습니다."
    elif not order_mirroring_enabled:
        status = "mirroring_disabled"
        note = "브로커 모의주문 미러링이 꺼져 있어 로컬 가상 장부와 브로커 모의계좌가 자동으로 같아지지 않습니다."
    elif positions_match and balance_match and total_asset_match and mirrored_order_count == 0:
        status = "aligned_waiting_first_submission"
        note = "브로커 기준 정렬이 완료됐고, 아직 브로커로 제출된 첫 주문은 없습니다."
    elif mirrored_order_count == 0:
        status = "waiting_first_submission"
        note = "브로커 미러링은 켜져 있지만 아직 제출된 주문이 없어 동기화 여부를 더 지켜봐야 합니다."
    elif positions_match and balance_match and total_asset_match:
        status = "aligned"
        note = "현재 로컬 가상 장부와 브로커 모의계좌의 보유 수량과 예수금이 일치합니다."
    else:
        status = "needs_review"
        note = "브로커 모의계좌와 로컬 가상 장부 사이에 수량 또는 예수금 차이가 있어 점검이 필요합니다."

    return {
        "status": status,
        "note": note,
        "mismatch_count": len(mismatch_rows),
        "positions_match": positions_match,
        "balance_match": balance_match,
        "total_asset_match": total_asset_match,
        "cash_gap": cash_gap,
        "raw_cash_gap": raw_cash_gap,
        "total_asset_gap": total_asset_gap,
        "broker_effective_cash_balance": broker_effective_cash,
        "broker_raw_cash_balance": broker_raw_cash,
        "local_positions_count": len(local_positions_map),
        "broker_positions_count": len(broker_positions_map),
        "order_mirroring_enabled": bool(order_mirroring_enabled),
        "mirrored_order_count": int(mirrored_order_count),
        "latest_local_snapshot_time": local_account_state.get("latest_snapshot_time"),
        "latest_broker_fetch_time": broker_payload.get("fetched_at"),
        "latest_broker_submission_time": local_account_state.get("latest_broker_submission_time"),
        "position_rows": position_rows,
        "mismatch_rows": mismatch_rows,
    }


def _write_report(markdown_path: Path, json_path: Path, payload: dict[str, Any]) -> None:
    comparison = payload.get("comparison") or {}
    mismatch_rows = comparison.get("mismatch_rows") or []
    lines = [
        "# Paper Account Reconciliation",
        "",
        "## Summary",
        "",
        f"- `ok`: {payload.get('ok')}",
        f"- `as_of`: {payload.get('as_of')}",
        f"- `status`: {comparison.get('status')}",
        f"- `market_session_status`: {payload.get('market_session_status')}",
        f"- `history_status`: {(payload.get('history_recording') or {}).get('status')}",
        f"- `mismatch_count`: {comparison.get('mismatch_count')}",
        f"- `cash_gap`: {comparison.get('cash_gap')}",
        f"- `total_asset_gap`: {comparison.get('total_asset_gap')}",
        f"- `order_mirroring_enabled`: {comparison.get('order_mirroring_enabled')}",
        f"- `mirrored_order_count`: {comparison.get('mirrored_order_count')}",
        "",
        "## Note",
        "",
        f"- {comparison.get('note')}",
        "",
        "## Mismatches",
        "",
    ]
    if mismatch_rows:
        for row in mismatch_rows:
            lines.append(
                f"- `{row.get('symbol')}` status={row.get('status')} local_qty={row.get('local_qty')} broker_qty={row.get('broker_qty')} qty_gap={row.get('qty_gap')}"
            )
    else:
        lines.append("- none")

    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def reconcile_paper_accounts(
    project_root: Path,
    *,
    force_account_refresh: bool = False,
    max_account_age_seconds: int = 60,
) -> PaperAccountReconciliationResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)
    local_account_state = load_local_paper_account_state(settings)
    broker_report_result: KisAccountReportResult = refresh_kis_account_report(
        project_root=project_root,
        account_mode="paper",
        force_refresh=force_account_refresh,
        max_age_seconds=max_account_age_seconds,
    )
    broker_report = broker_report_result.to_dict()
    comparison = build_paper_account_reconciliation_payload(
        local_account_state=local_account_state,
        broker_report=broker_report,
        order_mirroring_enabled=settings.strategy.enable_broker_paper_mirroring,
        mirrored_order_count=int(local_account_state.get("broker_order_submissions", 0) or 0),
    )
    as_of = now_local(settings.timezone)
    market_session_status = get_market_session_status(settings.market_calendar, as_of)
    markdown_path, json_path = _report_paths(settings.runtime_data_dir)
    payload = {
        "ok": bool(broker_report.get("ok")),
        "as_of": as_of.isoformat(),
        "market_session_status": market_session_status,
        "comparison": comparison,
        "local_account": local_account_state,
        "broker_account": broker_report.get("account_snapshot"),
    }
    try:
        history_result = record_paper_reconciliation_history(
            settings.runtime_data_dir,
            payload,
            market_session_status=market_session_status,
            account_epoch_id=settings.kis_paper_account_lifecycle.account_epoch_id,
            account_activated_on=settings.kis_paper_account_lifecycle.activated_on,
        )
        history_summary = history_result["summary"]
        payload["history_recording"] = {
            "status": history_summary.get("status"),
            "observation_status": history_summary.get("observation_status"),
            "days_available": history_summary.get("days_available"),
            "required_days": history_summary.get("required_days"),
            "summary_json_path": history_result["summary_json_path"],
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        payload["history_recording"] = {
            "status": "recording_failed",
            "error_type": type(exc).__name__,
        }
    _write_report(markdown_path, json_path, payload)
    return PaperAccountReconciliationResult(
        ok=bool(payload["ok"]),
        as_of=str(payload["as_of"]),
        status=str(comparison.get("status") or "unknown"),
        mismatch_count=int(comparison.get("mismatch_count") or 0),
        comparison=comparison,
        local_account=local_account_state,
        broker_account=broker_report.get("account_snapshot"),
        report_markdown_path=markdown_path,
        report_json_path=json_path,
    )

