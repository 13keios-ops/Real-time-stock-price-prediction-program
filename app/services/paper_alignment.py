"""Align the local virtual paper account to the broker paper account baseline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from app.config.settings import load_settings
from app.observability.logging import configure_logging
from app.services.kis_account import refresh_kis_account_report
from app.utils.time import now_local


@dataclass(slots=True)
class PaperAlignmentResult:
    ok: bool
    aligned_at: str
    backup_path: Path
    report_markdown_path: Path
    report_json_path: Path
    broker_position_count: int
    broker_cash_balance: float
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "aligned_at": self.aligned_at,
            "backup_path": str(self.backup_path),
            "report_markdown_path": str(self.report_markdown_path),
            "report_json_path": str(self.report_json_path),
            "broker_position_count": self.broker_position_count,
            "broker_cash_balance": self.broker_cash_balance,
            "status": self.status,
        }


def _report_paths(runtime_data_dir: Path) -> tuple[Path, Path]:
    report_dir = runtime_data_dir / "reports" / "broker-paper"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir / "latest-alignment.md", report_dir / "latest-alignment.json"


def load_paper_alignment_marker(runtime_data_dir: Path) -> dict[str, Any] | None:
    _, json_path = _report_paths(runtime_data_dir)
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _parse_iso_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _is_on_or_after_cutoff(value: Any, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    timestamp = _parse_iso_timestamp(value)
    return timestamp is not None and timestamp >= cutoff


def get_alignment_cutoff(runtime_data_dir: Path) -> datetime | None:
    marker = load_paper_alignment_marker(runtime_data_dir)
    if not marker:
        return None
    return _parse_iso_timestamp(marker.get("aligned_at"))


def filter_rows_after_alignment(
    rows: list[dict[str, Any]],
    *,
    runtime_data_dir: Path,
    time_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    cutoff = get_alignment_cutoff(runtime_data_dir)
    if cutoff is None:
        return list(rows)
    return [
        row
        for row in rows
        if any(_is_on_or_after_cutoff(row.get(field_name), cutoff) for field_name in time_fields)
    ]


def apply_alignment_baseline(
    *,
    latest_snapshot: dict[str, Any] | None,
    position_rows: list[dict[str, Any]],
    runtime_data_dir: Path,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None]:
    marker = load_paper_alignment_marker(runtime_data_dir)
    if not marker:
        return latest_snapshot, position_rows, None

    cutoff = _parse_iso_timestamp(marker.get("aligned_at"))
    if cutoff is None:
        return latest_snapshot, position_rows, marker

    filtered_positions = [
        row
        for row in position_rows
        if _is_on_or_after_cutoff(row.get("updated_at") or row.get("event_time"), cutoff)
    ]
    filtered_snapshot = latest_snapshot
    if latest_snapshot is not None and not _is_on_or_after_cutoff(latest_snapshot.get("event_time"), cutoff):
        filtered_snapshot = None

    baseline_positions = [dict(row) for row in (marker.get("baseline_positions") or [])]
    baseline_snapshot = marker.get("baseline_snapshot")
    if baseline_positions:
        positions_by_symbol = {
            str(row.get("symbol") or ""): row
            for row in baseline_positions
            if str(row.get("symbol") or "")
        }
        for row in filtered_positions:
            symbol = str(row.get("symbol") or "")
            if symbol:
                positions_by_symbol[symbol] = row
        filtered_positions = list(positions_by_symbol.values())
    if filtered_snapshot is None and isinstance(baseline_snapshot, dict):
        filtered_snapshot = dict(baseline_snapshot)
    return filtered_snapshot, filtered_positions, marker


def adjust_snapshot_for_fills_after_snapshot(
    latest_snapshot: dict[str, Any] | None,
    *,
    order_rows: list[dict[str, Any]],
    fill_rows: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not latest_snapshot:
        return latest_snapshot

    snapshot_time = _parse_iso_timestamp(latest_snapshot.get("event_time"))
    orders_by_id = {str(row.get("order_id") or ""): row for row in order_rows}
    cash_balance = float(latest_snapshot.get("cash_balance", 0.0) or 0.0)
    latest_fill_time = snapshot_time
    adjusted = False

    for fill in sorted(fill_rows, key=lambda row: str(row.get("event_time") or "")):
        fill_time = _parse_iso_timestamp(fill.get("event_time"))
        if snapshot_time is not None and (fill_time is None or fill_time <= snapshot_time):
            continue
        order = orders_by_id.get(str(fill.get("order_id") or ""))
        if not order:
            continue
        side = str(order.get("side") or "").lower()
        gross = float(fill.get("fill_price", 0.0) or 0.0) * int(fill.get("fill_qty", 0) or 0)
        fees = float(fill.get("commission", 0.0) or 0.0) + float(fill.get("tax", 0.0) or 0.0)
        if side == "buy":
            cash_balance -= gross + fees
        elif side == "sell":
            cash_balance += gross - fees
        else:
            continue
        latest_fill_time = fill_time or latest_fill_time
        adjusted = True

    if not adjusted:
        return latest_snapshot

    gross_market_value = sum(float(row.get("market_value", 0.0) or 0.0) for row in open_positions)
    unrealized_pnl = sum(float(row.get("unrealized_pnl", 0.0) or 0.0) for row in open_positions)
    adjusted_snapshot = dict(latest_snapshot)
    adjusted_snapshot.update(
        {
            "cash_balance": cash_balance,
            "gross_market_value": gross_market_value,
            "net_liquidation_value": cash_balance + gross_market_value,
            "open_positions": len(open_positions),
            "unrealized_pnl": unrealized_pnl,
            "adjusted_from_fills": True,
        }
    )
    if latest_fill_time is not None:
        adjusted_snapshot["event_time"] = latest_fill_time.isoformat()
    return adjusted_snapshot


def _build_baseline_position_row(aligned_at: datetime, position: dict[str, Any]) -> dict[str, Any] | None:
    qty = int(position.get("holding_qty", 0) or 0)
    if qty <= 0:
        return None
    return {
        "symbol": str(position.get("symbol") or ""),
        "opened_at": aligned_at.isoformat(),
        "updated_at": aligned_at.isoformat(),
        "qty": qty,
        "avg_price": float(position.get("average_buy_price", 0.0) or 0.0),
        "last_price": float(position.get("current_price", 0.0) or 0.0),
        "market_value": float(position.get("evaluation_amount", 0.0) or 0.0),
        "cost_basis": float(position.get("buy_amount", 0.0) or 0.0),
        "realized_pnl": 0.0,
        "unrealized_pnl": float(position.get("evaluation_profit_loss_amount", 0.0) or 0.0),
    }


def _build_baseline_snapshot(aligned_at: datetime, snapshot_dict: dict[str, Any], open_positions: int) -> dict[str, Any]:
    gross_market_value = float(snapshot_dict.get("stock_evaluation_amount", 0.0) or 0.0)
    total_asset_value = snapshot_dict.get("total_asset_amount")
    total_evaluation_value = snapshot_dict.get("total_evaluation_amount")
    net_liquidation_value = float(total_asset_value or total_evaluation_value or 0.0)
    cash_balance = float(snapshot_dict.get("cash_balance", 0.0) or 0.0)
    if total_asset_value not in (None, "") or total_evaluation_value not in (None, ""):
        cash_balance = net_liquidation_value - gross_market_value
    return {
        "snapshot_id": f"portfolio-broker-aligned-{aligned_at.strftime('%Y%m%d%H%M%S')}",
        "event_time": aligned_at.isoformat(),
        "cash_balance": cash_balance,
        "gross_market_value": gross_market_value,
        "net_liquidation_value": net_liquidation_value,
        "open_positions": open_positions,
        "realized_pnl": 0.0,
        "unrealized_pnl": float(snapshot_dict.get("total_profit_loss_amount", 0.0) or 0.0),
    }


def align_local_paper_to_broker(project_root: Path) -> PaperAlignmentResult:
    settings = load_settings(project_root=project_root)
    configure_logging(settings)

    broker_report = refresh_kis_account_report(
        project_root=project_root,
        account_mode="paper",
        force_refresh=True,
        max_age_seconds=300,
    )
    if not broker_report.ok or not broker_report.account_snapshot:
        raise ValueError(f"Broker paper account could not be loaded: {broker_report.error}")

    aligned_at = now_local(settings.timezone)
    snapshot_dict = broker_report.account_snapshot
    baseline_positions: list[dict[str, Any]] = []
    for position in snapshot_dict.get("positions") or []:
        baseline_row = _build_baseline_position_row(aligned_at, position)
        if baseline_row is not None:
            baseline_positions.append(baseline_row)
    baseline_snapshot = _build_baseline_snapshot(aligned_at, snapshot_dict, len(baseline_positions))

    markdown_path, json_path = _report_paths(settings.runtime_data_dir)
    backup_dir = settings.runtime_data_dir / "backups" / "paper-alignment"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{aligned_at.strftime('%y%m%d_%H%M%S_%f')}_marker-only.json"

    payload = {
        "ok": True,
        "aligned_at": aligned_at.isoformat(),
        "backup_path": str(backup_path),
        "broker_position_count": len(baseline_positions),
        "broker_cash_balance": float(snapshot_dict.get("cash_balance", 0.0) or 0.0),
        "status": "aligned_to_broker_marker",
        "broker_account_snapshot": snapshot_dict,
        "baseline_positions": baseline_positions,
        "baseline_snapshot": baseline_snapshot,
    }
    markdown_path.write_text(
        "\n".join(
            [
                "# Paper Alignment",
                "",
                f"- `aligned_at`: {payload['aligned_at']}",
                f"- `backup_path`: {payload['backup_path']}",
                f"- `broker_position_count`: {payload['broker_position_count']}",
                f"- `broker_cash_balance`: {payload['broker_cash_balance']}",
                f"- `status`: {payload['status']}",
                "- `mode`: marker_only",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    serialized_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    backup_path.write_text(serialized_payload, encoding="utf-8")
    json_path.write_text(serialized_payload, encoding="utf-8")
    return PaperAlignmentResult(
        ok=True,
        aligned_at=payload["aligned_at"],
        backup_path=backup_path,
        report_markdown_path=markdown_path,
        report_json_path=json_path,
        broker_position_count=int(payload["broker_position_count"]),
        broker_cash_balance=float(payload["broker_cash_balance"]),
        status=str(payload["status"]),
    )
