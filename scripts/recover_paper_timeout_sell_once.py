#!/usr/bin/env python3
"""Owner-approved current-state compensation for the 2026-09-08 timeout.

No broker API, synthetic fill/submission, history rewrite, or baseline change.
This incident-specific command defaults to read-only and is not an automation.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import load_settings
from app.paper_trading.costs import (
    DEFAULT_COMMISSION_RATE,
    DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE,
    DOMESTIC_STOCK_COST_MODEL_VERSION,
)

ORDER_ID = "paper-order-close-online-20260908080016-138040-11b61ad7-081914"
RECOVERY_ID = "paper-account-recovery-20260908-373220-v1"


def _timestamp(value):
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def recover(conn, *, account, activity, alignment, applied_at, execute=False, backup_path):
    """Validate under a transaction, then apply only current state plus audit."""
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN IMMEDIATE" if execute else "BEGIN")
    try:
        existing = conn.execute("SELECT event_type, detail FROM paper_order_events WHERE order_event_id=?", (RECOVERY_ID,)).fetchone()
        if existing:
            _require(existing["event_type"] == "account_recovery_adjustment", "recovery ID collision")
            audit = json.loads(existing["detail"])
            _require(audit.get("recovery_id") == RECOVERY_ID, "recovery audit mismatch")
            conn.rollback()
            return {**audit, "status": "already_applied"}

        scope = activity.get("scope") or {}
        reconstruction = activity.get("position_reconstruction") or {}
        _require((activity.get("pagination") or {}).get("pagination_complete") is True, "incomplete broker evidence")
        _require(reconstruction.get("evidence_complete") is True and reconstruction.get("activity_matches_broker_snapshot") is True, "broker quantity reconstruction incomplete")
        cutoff = _timestamp(alignment.get("aligned_at"))
        _require(cutoff.date().isoformat() == "2026-09-06", "wrong baseline")
        _require(cutoff == _timestamp(scope.get("alignment_at")), "baseline scope drift")
        observed = _timestamp(account.get("as_of"))
        activity_observed = _timestamp(scope.get("account_snapshot_as_of"))
        _require(activity_observed.date().isoformat() == "2026-09-24" and observed >= activity_observed, "account scope drift")
        _require(observed.date().isoformat() in {"2026-09-24", "2026-09-25"}, "wrong source observation")
        _require(_timestamp(applied_at) >= observed, "correction cannot be backdated")
        broker = account.get("broker_account") or {}
        _require(account.get("ok") is True and broker.get("mode") == "paper", "paper account evidence required")
        _require(not any(r.get("symbol") == "373220" and int(r.get("holding_qty") or 0) != 0 for r in broker.get("positions") or []), "broker quantity changed")
        evidence_rows = [r for r in reconstruction.get("rows") or [] if r.get("symbol") == "373220"]
        _require(len(evidence_rows) == 1 and evidence_rows[0].get("local_qty") == 1 and evidence_rows[0].get("broker_snapshot_qty") == 0 and evidence_rows[0].get("full_activity_qty") == 0, "incident quantity evidence missing")
        quantities = {r["symbol"]: int(r.get("holding_qty") or 0) for r in broker.get("positions") or []}
        reconstructed = {r["symbol"]: int(r["full_activity_qty"]) for r in reconstruction.get("rows") or []}
        _require(all(quantities.get(s, 0) == q for s, q in reconstructed.items()) and all(reconstructed.get(s, 0) == q for s, q in quantities.items()), "newer broker quantities changed")

        order_row = conn.execute("SELECT * FROM paper_orders WHERE order_id=?", (ORDER_ID,)).fetchone()
        _require(order_row is not None, "missing local order")
        order = dict(order_row)
        _require((order["symbol"], order["side"], order["qty"], order["limit_price"], order["status"], order["event_time"]) == ("373220", "sell", 1, 349500., "rejected", "2026-09-08T15:01:00+09:00"), "local order changed")
        candidates = conn.execute("SELECT count(*) FROM paper_orders WHERE symbol='373220' AND side='sell' AND qty=1 AND limit_price=349500 AND event_time>=? AND event_time<?", ("2026-09-08", "2026-09-09")).fetchone()[0]
        _require(candidates == 1, "ambiguous local candidate")
        for table, column in (("paper_fills", "order_id"), ("broker_paper_order_submissions", "local_order_id"), ("broker_paper_order_status_snapshots", "local_order_id")):
            _require(conn.execute(f"SELECT count(*) FROM {table} WHERE {column}=?", (ORDER_ID,)).fetchone()[0] == 0, "order already has broker accounting")
        risks = conn.execute("SELECT detail FROM ops_risk_events WHERE symbol='373220' AND event_time=? AND gate='broker_paper_mirroring'", (order["event_time"],)).fetchall()
        failures = [json.loads(r[0]) for r in risks]
        _require(any(r.get("local_order_id") == ORDER_ID and (r.get("failure") or {}).get("category") == "broker_network_error" and (r.get("failure") or {}).get("network_attempted") is True for r in failures), "network-attempt evidence missing")
        _require(conn.execute("SELECT count(*) FROM paper_orders WHERE status='submission_unknown'").fetchone()[0] == 0, "other unknown submissions remain")
        for table in ("paper_orders", "paper_fills"):
            _require(conn.execute(f"SELECT count(*) FROM {table} WHERE event_time>?", (activity_observed.isoformat(),)).fetchone()[0] == 0, "new trading invalidates cached evidence")

        positions = [dict(r) for r in conn.execute("SELECT * FROM paper_positions ORDER BY symbol")]
        # Match the runtime alignment overlay; preserve old-epoch DB rows untouched.
        current_positions = {r["symbol"]: dict(r) for r in alignment.get("baseline_positions") or []}
        current_positions.update({r["symbol"]: r for r in positions if _timestamp(r["updated_at"]) >= cutoff})
        positions = list(current_positions.values())
        target = next((r for r in positions if r["symbol"] == "373220"), None)
        _require(target is not None and target["qty"] == 1 and math.isclose(target["avg_price"], 351052.65, abs_tol=1e-6), "local position changed")
        snapshot_row = conn.execute("SELECT * FROM paper_portfolio_snapshots ORDER BY event_time DESC LIMIT 1").fetchone()
        _require(snapshot_row is not None, "missing current snapshot")
        before = dict(snapshot_row)
        source = account.get("local_account") or {}
        _require(before["event_time"] == source.get("latest_snapshot_time") and math.isfinite(before["cash_balance"]) and math.isclose(before["cash_balance"], float(source.get("cash_balance")), rel_tol=0, abs_tol=1e-6), "local snapshot changed")
        _require(conn.execute("SELECT count(*) FROM paper_fills WHERE event_time>?", (before["event_time"],)).fetchone()[0] == 0, "unaccounted fills after snapshot")
        _require(all(_timestamp(r["updated_at"]) <= activity_observed for r in positions), "positions newer than evidence")

        gross = 349500.
        commission = gross * DEFAULT_COMMISSION_RATE
        tax = gross * DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE
        cash_delta = gross - commission - tax
        pnl_delta = cash_delta - target["avg_price"]
        remaining = [r for r in positions if r["symbol"] != "373220" and r["qty"] > 0]
        after = {"snapshot_id": RECOVERY_ID, "event_time": applied_at,
                 "cash_balance": before["cash_balance"] + cash_delta,
                 "gross_market_value": sum(r["market_value"] for r in remaining),
                 "open_positions": len(remaining), "realized_pnl": before["realized_pnl"] + pnl_delta,
                 "unrealized_pnl": sum(r["unrealized_pnl"] for r in remaining)}
        after["net_liquidation_value"] = after["cash_balance"] + after["gross_market_value"]
        audit = {"recovery_id": RECOVERY_ID, "local_order_id": ORDER_ID, "symbol": "373220",
                 "source_trade_date": "2026-09-08", "source_broker_order_time": "15:03:22",
                 "source_query_date": "2026-09-24", "owner_manual_sell_denied": True,
                 "activity_snapshot_as_of": activity_observed.isoformat(), "account_snapshot_as_of": observed.isoformat(),
                 "broker_identity_link": "inferred_owner_approved_not_exact",
                 "cost_basis": "research_assumption_not_broker_statement", "cost_model_version": DOMESTIC_STOCK_COST_MODEL_VERSION,
                 "commission": commission, "tax": tax, "cash_delta": cash_delta, "realized_pnl_delta": pnl_delta,
                 "valuation_basis": "stored_position_marks_not_fresh_quotes", "official_phase0_pass": False,
                 "before_position": target, "before_snapshot": before, "after_snapshot": after}
        if not execute:
            conn.rollback()
            return {**audit, "status": "ready_dry_run"}

        # Durable preimage before any accounting mutation; never overwrite a backup.
        encoded = (json.dumps(audit, indent=2, sort_keys=True) + "\n").encode()
        fd = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as backup:
            backup.write(encoded)
            backup.flush()
            os.fsync(backup.fileno())
        conn.execute("INSERT INTO paper_order_events VALUES (?, ?, ?, ?, ?)",
                     (RECOVERY_ID, ORDER_ID, applied_at, "account_recovery_adjustment", json.dumps(audit, sort_keys=True)))
        conn.execute("UPDATE paper_positions SET opened_at=NULL, updated_at=?, qty=0, avg_price=0, last_price=?, market_value=0, cost_basis=0, realized_pnl=realized_pnl+?, unrealized_pnl=0 WHERE symbol='373220'", (applied_at, gross, pnl_delta))
        conn.execute("INSERT INTO paper_portfolio_snapshots(snapshot_id,event_time,cash_balance,gross_market_value,net_liquidation_value,open_positions,realized_pnl,unrealized_pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", tuple(after[k] for k in ("snapshot_id", "event_time", "cash_balance", "gross_market_value", "net_liquidation_value", "open_positions", "realized_pnl", "unrealized_pnl")))
        conn.commit()
        return {**audit, "status": "applied"}
    except BaseException:
        conn.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--owner-approved", action="store_true")
    args = parser.parse_args()
    _require(not args.execute or args.owner_approved, "explicit owner approval required")
    settings = load_settings(project_root=ROOT)
    _require(settings.trading_mode == "paper" and settings.kis_paper_account_lifecycle.account_epoch_id == "paper-2026-09-03", "wrong account epoch or trading mode")
    for helper in ("get_live_runtime_status.sh", "get_runtime_watchdog_status.sh"):
        status = json.loads(subprocess.check_output(["bash", str(ROOT / "scripts" / helper)], cwd=ROOT, text=True))
        if helper == "get_live_runtime_status.sh":
            _require(status.get("process_running") is False and status.get("current_session_status") in {"weekend", "holiday", "overnight", "post-close"}, "runtime protected")
        else:
            _require(status.get("live_runtime_should_run") is False, "runtime should run")
    runtime = settings.runtime_data_dir
    paths = [runtime / "reports/reconciliation/latest-paper-account-sync.json",
             runtime / "reports/reconciliation/latest-paper-account-activity.json",
             runtime / "reports/broker-paper/latest-alignment.json"]
    inputs = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    output_dir = runtime / "reports/codex"
    if args.execute:
        output_dir.mkdir(parents=True, exist_ok=True)
    db = runtime / "dev.db"
    mode = "rw" if args.execute else "ro"
    with sqlite3.connect(f"file:{db}?mode={mode}", uri=True, timeout=10) as conn:
        if not args.execute:
            conn.execute("PRAGMA query_only=ON")
        result = recover(conn, account=inputs[0], activity=inputs[1], alignment=inputs[2],
                         applied_at=datetime.now().astimezone().isoformat(), execute=args.execute,
                         backup_path=output_dir / f"{RECOVERY_ID}-before.json")
    result["source_report_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if args.execute:
        report = output_dir / f"{RECOVERY_ID}-result.json"
        if not report.exists():
            with report.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2, sort_keys=True)
                handle.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
