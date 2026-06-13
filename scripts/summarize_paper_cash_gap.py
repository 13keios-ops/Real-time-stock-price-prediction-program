#!/usr/bin/env python3
"""Summarize paper/KIS cash gap before applying cash sync or alignment.

This script is read-only with respect to the trading ledger and environment.
It only reads the latest reconciliation reports and writes a diagnostic report.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DATA_DIR = REPO_ROOT / "runtime-data"
DEFAULT_DUAL_MATCH_PATH = (
    DEFAULT_RUNTIME_DATA_DIR / "reports" / "reconciliation" / "latest-paper-dual-account-match.json"
)
DEFAULT_ACCOUNT_SYNC_PATH = (
    DEFAULT_RUNTIME_DATA_DIR / "reports" / "reconciliation" / "latest-paper-account-sync.json"
)
DEFAULT_BROKER_SYNC_PATH = DEFAULT_RUNTIME_DATA_DIR / "reports" / "broker-paper" / "latest-sync.json"
DEFAULT_ALIGNMENT_PATH = DEFAULT_RUNTIME_DATA_DIR / "reports" / "broker-paper" / "latest-alignment.json"
DEFAULT_OUTPUT_DIR = DEFAULT_RUNTIME_DATA_DIR / "reports" / "reconciliation"
BALANCE_TOLERANCE_KRW = 10_000.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"_missing": True, "_path": str(path)}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"_invalid_json": True, "_path": str(path), "error": str(exc)}


def _parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _position_count(account: dict[str, Any], comparison: dict[str, Any]) -> int:
    raw = _number_or_none(account.get("position_row_count"))
    if raw is not None:
        return int(raw)
    positions = account.get("positions")
    if isinstance(positions, list):
        return len([row for row in positions if int(_number_or_none((row or {}).get("holding_qty")) or 0) > 0])
    raw = _number_or_none(comparison.get("broker_positions_count"))
    return int(raw or 0)


def _effective_cash(account: dict[str, Any], comparison: dict[str, Any]) -> float | None:
    from_comparison = _number_or_none(comparison.get("broker_effective_cash_balance"))
    if from_comparison is not None:
        return from_comparison
    total = _number_or_none(account.get("total_asset_amount"))
    if total is None:
        total = _number_or_none(account.get("total_evaluation_amount"))
    stock = _number_or_none(account.get("stock_evaluation_amount"))
    if total is None or stock is None:
        return _number_or_none(account.get("cash_balance"))
    return total - stock


def _balance_match(gap: float | None, tolerance_krw: float = BALANCE_TOLERANCE_KRW) -> bool | None:
    if gap is None:
        return None
    return abs(gap) < tolerance_krw


def _hypothetical_alignment_baseline(account: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    total = _number_or_none(account.get("total_asset_amount"))
    if total is None:
        total = _number_or_none(account.get("total_evaluation_amount"))
    stock = _number_or_none(account.get("stock_evaluation_amount")) or 0.0
    cash = _effective_cash(account, comparison)
    positions = account.get("positions") if isinstance(account.get("positions"), list) else []
    return {
        "cash_balance": cash,
        "gross_market_value": stock,
        "net_liquidation_value": total,
        "open_positions": _position_count(account, comparison),
        "broker_position_rows": len(positions),
        "unrealized_pnl": _number_or_none(account.get("total_profit_loss_amount")) or 0.0,
    }


def build_cash_gap_analysis(
    *,
    env: dict[str, str],
    dual_match: dict[str, Any],
    account_sync: dict[str, Any],
    broker_sync: dict[str, Any],
    alignment: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    comparison = dual_match.get("comparison") or account_sync.get("comparison") or {}
    local_account = dual_match.get("local_account") or account_sync.get("local_account") or {}
    broker_account = dual_match.get("broker_account") or account_sync.get("broker_account") or {}
    dual_env = dual_match.get("env") if isinstance(dual_match.get("env"), dict) else {}

    env_initial_cash = _number_or_none(env.get("PAPER_INITIAL_CASH"))
    reported_initial_cash = _number_or_none(dual_env.get("paper_initial_cash_after"))
    current_initial_cash = reported_initial_cash if reported_initial_cash is not None else env_initial_cash
    broker_raw_cash = _number_or_none(comparison.get("broker_raw_cash_balance"))
    if broker_raw_cash is None:
        broker_raw_cash = _number_or_none(broker_account.get("cash_balance"))
    broker_effective_cash = _effective_cash(broker_account, comparison)
    broker_total_asset = _number_or_none(broker_account.get("total_asset_amount"))
    if broker_total_asset is None:
        broker_total_asset = _number_or_none(broker_account.get("total_evaluation_amount"))
    broker_stock_eval = _number_or_none(broker_account.get("stock_evaluation_amount")) or 0.0
    local_cash = _number_or_none(local_account.get("cash_balance"))
    local_total = _number_or_none(local_account.get("net_liquidation_value"))
    cash_gap = _number_or_none(comparison.get("cash_gap"))
    if cash_gap is None and local_cash is not None and broker_effective_cash is not None:
        cash_gap = local_cash - broker_effective_cash
    raw_cash_gap = _number_or_none(comparison.get("raw_cash_gap"))
    if raw_cash_gap is None and local_cash is not None and broker_raw_cash is not None:
        raw_cash_gap = local_cash - broker_raw_cash
    total_asset_gap = _number_or_none(comparison.get("total_asset_gap"))
    if total_asset_gap is None and local_total is not None and broker_total_asset is not None:
        total_asset_gap = local_total - broker_total_asset

    broker_position_count = _position_count(broker_account, comparison)
    local_positions = local_account.get("positions") if isinstance(local_account.get("positions"), list) else []
    local_position_count = len(local_positions)
    open_order_count = int(_number_or_none(broker_sync.get("open_order_count")) or 0)
    pending_symbols = broker_sync.get("pending_symbols") if isinstance(broker_sync.get("pending_symbols"), list) else []

    sync_allowed = broker_position_count == 0 and broker_raw_cash is not None and broker_raw_cash > 0
    target_initial_cash = broker_raw_cash if sync_allowed else None
    env_delta = (
        target_initial_cash - current_initial_cash
        if target_initial_cash is not None and current_initial_cash is not None
        else None
    )
    sync_snapshot_cash_gap_after = cash_gap
    sync_snapshot_total_gap_after = total_asset_gap
    sync_fix_snapshot_gap = bool(_balance_match(sync_snapshot_cash_gap_after)) and bool(
        _balance_match(sync_snapshot_total_gap_after)
    )

    alignment_baseline = _hypothetical_alignment_baseline(broker_account, comparison)
    alignment_allowed = not bool(broker_account.get("_missing")) and broker_total_asset is not None
    alignment_would_zero_current_view_gap = alignment_allowed and broker_effective_cash is not None

    raw_effective_gap = (
        broker_raw_cash - broker_effective_cash
        if broker_raw_cash is not None and broker_effective_cash is not None
        else None
    )

    warnings: list[str] = []
    if open_order_count > 0:
        warnings.append("open_order_backlog_present")
    if sync_allowed and not sync_fix_snapshot_gap:
        warnings.append("initial_cash_only_does_not_fix_current_snapshot_gap")
    if raw_effective_gap is not None and abs(raw_effective_gap) >= 1:
        warnings.append("broker_raw_cash_differs_from_effective_cash")
    if comparison.get("mismatch_count") in (0, "0") and not _balance_match(cash_gap):
        warnings.append("cash_gap_without_position_mismatch")
    if alignment_allowed and open_order_count > 0:
        warnings.append("align_to_broker_should_review_open_order_backlog_first")

    already_aligned = (
        open_order_count == 0
        and bool(comparison.get("positions_match"))
        and bool(_balance_match(cash_gap))
        and bool(_balance_match(total_asset_gap))
    )
    recommended_action = "do_not_apply_automatically"
    operator_approval_required = True
    next_action = "review_open_order_backlog_then_decide_alignment"
    reason = (
        "Position mismatch is closed, but cash gap remains and broker open order backlog is present. "
        "A baseline-changing command should not be applied automatically."
    )
    if already_aligned:
        recommended_action = "keep_current_alignment"
        operator_approval_required = False
        next_action = "no_cash_gap_action_required"
        reason = (
            "Position, effective cash, total asset, and open order backlog are already aligned. "
            "No SyncInitialCash or AlignToBroker action is required now."
        )
    elif sync_allowed and sync_fix_snapshot_gap and open_order_count == 0:
        next_action = "operator_may_run_sync_initial_cash_then_reconcile"
        reason = (
            "Position mismatch and open order backlog are closed, and SyncInitialCash would be enough "
            "to satisfy the current cash check."
        )
    elif alignment_allowed and open_order_count == 0:
        next_action = "operator_may_run_align_to_broker_after_audit_note"
        reason = (
            "Position mismatch and open order backlog are closed, but SyncInitialCash alone would not "
            "fix the current snapshot gap. Marker-only alignment is the remaining baseline candidate."
        )

    return {
        "generated_at": generated_at or _now_iso(),
        "ok": True,
        "status": "analysis_only",
        "read_only": True,
        "source_reports": {
            "dual_match_status": dual_match.get("status"),
            "account_sync_status": (account_sync.get("comparison") or {}).get("status"),
            "broker_sync_status": broker_sync.get("status"),
            "alignment_status": alignment.get("status"),
        },
        "current_state": {
            "trading_mode": env.get("TRADING_MODE") or dual_env.get("trading_mode"),
            "broker_paper_mirroring_enabled": bool(comparison.get("order_mirroring_enabled")),
            "paper_initial_cash": current_initial_cash,
            "broker_raw_cash": broker_raw_cash,
            "broker_effective_cash": broker_effective_cash,
            "broker_total_asset": broker_total_asset,
            "broker_stock_evaluation": broker_stock_eval,
            "local_cash": local_cash,
            "local_net_liquidation": local_total,
            "cash_gap": cash_gap,
            "raw_cash_gap": raw_cash_gap,
            "total_asset_gap": total_asset_gap,
            "positions_match": bool(comparison.get("positions_match")),
            "balance_match": bool(comparison.get("balance_match")),
            "total_asset_match": bool(comparison.get("total_asset_match")),
            "local_position_count": local_position_count,
            "broker_position_count": broker_position_count,
            "mirrored_order_count": int(_number_or_none(comparison.get("mirrored_order_count")) or 0),
            "open_order_count": open_order_count,
            "pending_symbols": pending_symbols,
            "latest_local_snapshot_time": comparison.get("latest_local_snapshot_time"),
            "latest_broker_fetch_time": comparison.get("latest_broker_fetch_time"),
            "latest_broker_submission_time": comparison.get("latest_broker_submission_time"),
        },
        "dry_run": {
            "sync_initial_cash": {
                "would_modify_env": bool(sync_allowed and env_delta not in (None, 0.0)),
                "allowed_by_current_shape": sync_allowed,
                "blocked_reason": None if sync_allowed else "broker_positions_or_cash_unavailable",
                "current_env_initial_cash": current_initial_cash,
                "target_env_initial_cash": target_initial_cash,
                "env_delta": env_delta,
                "target_source": "broker_account.cash_balance",
                "would_fix_initial_cash_check_against_raw_cash": bool(sync_allowed),
                "would_fix_current_snapshot_cash_gap": sync_fix_snapshot_gap,
                "current_snapshot_cash_gap_after_sync": sync_snapshot_cash_gap_after,
                "current_snapshot_total_asset_gap_after_sync": sync_snapshot_total_gap_after,
                "note": (
                    "SyncInitialCash updates PAPER_INITIAL_CASH only. It does not rewrite the latest "
                    "paper portfolio snapshot, fills, or broker order backlog."
                ),
            },
            "align_to_broker": {
                "would_modify_alignment_marker": alignment_allowed,
                "allowed_by_current_shape": alignment_allowed,
                "blocked_reason": None if alignment_allowed else "broker_account_snapshot_unavailable",
                "mode": "marker_only",
                "current_alignment_status": alignment.get("status"),
                "hypothetical_baseline_snapshot": alignment_baseline,
                "would_modify_env": False,
                "would_hide_prior_ledger_from_current_paper_view": True,
                "would_zero_current_view_gap_if_no_later_fills": alignment_would_zero_current_view_gap,
                "requires_operator_audit_note": True,
                "note": (
                    "AlignToBroker writes a marker-only broker baseline and filters older paper rows "
                    "from the current view. It preserves the old ledger but changes the paper baseline."
                ),
            },
        },
        "recommendation": {
            "recommended_action": recommended_action,
            "next_action": next_action,
            "operator_approval_required_for_mutation": operator_approval_required,
            "reason": reason,
        },
        "warnings": warnings,
    }


def _money(value: Any) -> str:
    number = _number_or_none(value)
    if number is None:
        return "-"
    return f"{number:,.0f}원"


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    current = payload.get("current_state") or {}
    sync = ((payload.get("dry_run") or {}).get("sync_initial_cash") or {})
    align = ((payload.get("dry_run") or {}).get("align_to_broker") or {})
    recommendation = payload.get("recommendation") or {}
    warnings = payload.get("warnings") or []
    lines = [
        "# Paper Cash Gap Analysis",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        "- mode: read-only analysis",
        "",
        "## Summary",
        "",
        f"- paper initial cash: `{_money(current.get('paper_initial_cash'))}`",
        f"- broker raw cash: `{_money(current.get('broker_raw_cash'))}`",
        f"- broker effective cash: `{_money(current.get('broker_effective_cash'))}`",
        f"- local cash: `{_money(current.get('local_cash'))}`",
        f"- cash gap: `{_money(current.get('cash_gap'))}`",
        f"- total asset gap: `{_money(current.get('total_asset_gap'))}`",
        f"- positions match: `{current.get('positions_match')}`",
        f"- open order count: `{current.get('open_order_count')}`",
        "",
        "## SyncInitialCash Dry Run",
        "",
        f"- allowed by current shape: `{sync.get('allowed_by_current_shape')}`",
        f"- target env initial cash: `{_money(sync.get('target_env_initial_cash'))}`",
        f"- env delta: `{_money(sync.get('env_delta'))}`",
        f"- would fix current snapshot cash gap: `{sync.get('would_fix_current_snapshot_cash_gap')}`",
        f"- note: {sync.get('note')}",
        "",
        "## AlignToBroker Dry Run",
        "",
        f"- allowed by current shape: `{align.get('allowed_by_current_shape')}`",
        f"- mode: `{align.get('mode')}`",
        f"- would modify env: `{align.get('would_modify_env')}`",
        f"- would zero current view gap if no later fills: `{align.get('would_zero_current_view_gap_if_no_later_fills')}`",
        f"- note: {align.get('note')}",
        "",
        "## Recommendation",
        "",
        f"- recommended action: `{recommendation.get('recommended_action')}`",
        f"- next action: `{recommendation.get('next_action')}`",
        f"- reason: {recommendation.get('reason')}",
        "",
        "## Warnings",
        "",
    ]
    if warnings:
        lines.extend(f"- `{warning}`" for warning in warnings)
    else:
        lines.append("- none")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_reports(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest-paper-cash-gap-analysis.json"
    markdown_path = output_dir / "latest-paper-cash-gap-analysis.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(markdown_path, payload)
    return json_path, markdown_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-path", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--dual-match-path", type=Path, default=DEFAULT_DUAL_MATCH_PATH)
    parser.add_argument("--account-sync-path", type=Path, default=DEFAULT_ACCOUNT_SYNC_PATH)
    parser.add_argument("--broker-sync-path", type=Path, default=DEFAULT_BROKER_SYNC_PATH)
    parser.add_argument("--alignment-path", type=Path, default=DEFAULT_ALIGNMENT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_cash_gap_analysis(
        env=_parse_env(args.env_path),
        dual_match=_read_json(args.dual_match_path),
        account_sync=_read_json(args.account_sync_path),
        broker_sync=_read_json(args.broker_sync_path),
        alignment=_read_json(args.alignment_path),
    )
    json_path, markdown_path = write_reports(payload, args.output_dir)
    payload["report_json_path"] = str(json_path)
    payload["report_markdown_path"] = str(markdown_path)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"paper cash gap analysis: {payload['recommendation']['next_action']}")
        print(f"report: {markdown_path}")


if __name__ == "__main__":
    main()
