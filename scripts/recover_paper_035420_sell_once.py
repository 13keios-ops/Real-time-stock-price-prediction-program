#!/usr/bin/env python3
"""Owner-approved current-state recovery for the 2026-09-29 paper sell timeout.

This is not a broker fill sync: the timeout lost the ACK order identity.
It never calls KIS, fabricates a fill/submission, or rewrites historical rows.
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

ORDER_ID = "paper-order-close-online-20260929080014-175568-6d2ebe1e-037413"
RECOVERY_ID = "paper-account-recovery-20260929-035420-v1"
BROKER_REF_HASH = "61c479a5639092e8"
EVIDENCE_PATH = Path("runtime-data/reports/codex/paper-035420-sell-20260929-kis-evidence.json")


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _timestamp(value):
    parsed = datetime.fromisoformat(str(value))
    _require(parsed.tzinfo is not None, "timezone required")
    return parsed


def recover(conn, *, account, evidence, alignment, applied_at, execute=False, backup_path):
    """Check a unique inferred trade and atomically correct current state only."""
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN IMMEDIATE" if execute else "BEGIN")
    try:
        existing = conn.execute(
            "SELECT event_type, detail FROM paper_order_events WHERE order_event_id=?",
            (RECOVERY_ID,),
        ).fetchone()
        if existing:
            _require(existing["event_type"] == "account_recovery_adjustment", "recovery ID collision")
            audit = json.loads(existing["detail"])
            _require(audit.get("recovery_id") == RECOVERY_ID, "recovery audit mismatch")
            conn.rollback()
            return {**audit, "status": "already_applied"}

        cutoff = _timestamp(alignment.get("aligned_at"))
        _require(cutoff.date().isoformat() == "2026-09-06", "wrong account baseline")
        observed = _timestamp(account.get("as_of"))
        applied = _timestamp(applied_at)
        _require(observed.date().isoformat() == "2026-10-02", "stale or changed account snapshot")
        _require(applied.date().isoformat() in {"2026-10-03", "2026-10-04"} and applied >= observed, "recovery window expired")
        broker = account.get("broker_account") or {}
        _require(account.get("ok") is True and broker.get("mode") == "paper", "paper broker account evidence required")
        broker_qty = {r["symbol"]: int(r.get("holding_qty") or 0) for r in broker.get("positions") or []}
        _require(broker_qty.get("035420", 0) == 0, "broker quantity changed")

        pagination = evidence.get("pagination") or {}
        rows = evidence.get("rows") or []
        _require(evidence.get("mode") == "paper" and evidence.get("order_date") == "20260929"
                 and evidence.get("symbol") == "035420", "wrong KIS evidence scope")
        _require(pagination.get("pagination_complete") is True
                 and int(pagination.get("records_returned") or 0) == len(rows), "incomplete KIS evidence")
        unlinked = [r for r in rows if r.get("linked_submission") is False]
        _require(len(unlinked) == 1, "ambiguous unlinked broker orders")
        trade = unlinked[0]
        _require(trade.get("broker_ref_sha256") == BROKER_REF_HASH
                 and trade.get("side") == "01"
                 and int(trade.get("order_qty") or 0) == 3
                 and float(trade.get("order_price") or 0) == 194600.0
                 and int(trade.get("filled_qty") or 0) == 3
                 and int(trade.get("remaining_qty") or 0) == 0
                 and int(trade.get("reject_qty") or 0) == 0
                 and int(trade.get("cancel_confirm_qty") or 0) == 0, "broker trade identity or final state changed")
        gross = float(trade.get("filled_amount") or 0)
        fill_price = float(trade.get("avg_fill_price") or 0)
        _require(math.isfinite(gross) and math.isfinite(fill_price) and fill_price > 0
                 and math.isclose(gross, 3 * fill_price, rel_tol=0, abs_tol=1.0), "broker fill amount invalid")

        order_row = conn.execute("SELECT * FROM paper_orders WHERE order_id=?", (ORDER_ID,)).fetchone()
        _require(order_row is not None, "local order missing")
        order = dict(order_row)
        _require((order["symbol"], order["side"], order["qty"], order["limit_price"], order["status"],
                  order["event_time"]) == ("035420", "sell", 3, 194600.0, "submission_unknown",
                                           "2026-09-29T10:47:00+09:00"), "local order changed")
        broker_order_time = datetime.fromisoformat(
            "2026-09-29T" + str(trade.get("order_time") or "").zfill(6)[:2] + ":"
            + str(trade.get("order_time") or "").zfill(6)[2:4] + ":"
            + str(trade.get("order_time") or "").zfill(6)[4:] + "+09:00"
        )
        delay = (broker_order_time - _timestamp(order["event_time"])).total_seconds()
        _require(0 <= delay <= 120, "broker order time outside timeout window")
        candidate_count = conn.execute(
            "SELECT count(*) FROM paper_orders WHERE symbol='035420' AND side='sell' AND qty=3 "
            "AND limit_price=194600 AND event_time>=? AND event_time<?",
            ("2026-09-29", "2026-09-30"),
        ).fetchone()[0]
        _require(candidate_count == 1, "ambiguous local sell candidate")
        for table, column in (("paper_fills", "order_id"),
                              ("broker_paper_order_submissions", "local_order_id"),
                              ("broker_paper_order_status_snapshots", "local_order_id")):
            _require(conn.execute(f"SELECT count(*) FROM {table} WHERE {column}=?", (ORDER_ID,)).fetchone()[0] == 0,
                     "order already has broker accounting")
        risks = conn.execute(
            "SELECT detail FROM ops_risk_events WHERE symbol='035420' AND event_time=? AND gate='broker_paper_mirroring'",
            (order["event_time"],),
        ).fetchall()
        _require(any(
            (detail := json.loads(row[0])).get("local_order_id") == ORDER_ID
            and (detail.get("failure") or {}).get("category") == "broker_network_error"
            and (detail.get("failure") or {}).get("network_attempted") is True
            for row in risks
        ), "network timeout attempt evidence missing")
        _require(conn.execute("SELECT count(*) FROM paper_orders WHERE status='submission_unknown'").fetchone()[0] == 1,
                 "other unknown submissions remain")
        for table in ("paper_orders", "paper_fills"):
            _require(conn.execute(f"SELECT count(*) FROM {table} WHERE event_time>?", (order["event_time"],)).fetchone()[0] == 0,
                     "later local trades invalidate correction")

        position_rows = [dict(r) for r in conn.execute("SELECT * FROM paper_positions ORDER BY symbol")]
        current = {r["symbol"]: dict(r) for r in alignment.get("baseline_positions") or []}
        current.update({r["symbol"]: r for r in position_rows if _timestamp(r["updated_at"]) >= cutoff})
        positions = list(current.values())
        target = next((r for r in positions if r["symbol"] == "035420"), None)
        _require(target is not None and target["qty"] == 3
                 and math.isclose(float(target["cost_basis"]), 584187.615, rel_tol=0, abs_tol=0.01),
                 "local position changed")
        _require(all(int(r["qty"]) == broker_qty.get(r["symbol"], 0)
                     for r in positions if r["symbol"] != "035420" and int(r["qty"]) > 0),
                 "other local positions differ from broker")
        _require(all(any(r["symbol"] == symbol and int(r["qty"]) == qty for r in positions)
                     for symbol, qty in broker_qty.items() if qty > 0),
                 "other broker positions differ from local")
        snapshot_row = conn.execute(
            "SELECT * FROM paper_portfolio_snapshots ORDER BY event_time DESC LIMIT 1"
        ).fetchone()
        _require(snapshot_row is not None, "local snapshot missing")
        before = dict(snapshot_row)
        source = account.get("local_account") or {}
        _require(before["event_time"] == source.get("latest_snapshot_time")
                 and math.isclose(float(before["cash_balance"]), float(source.get("cash_balance")), rel_tol=0, abs_tol=0.01),
                 "local snapshot changed")
        _require(target["updated_at"] == before["event_time"], "target mark is not from latest snapshot")

        _require(conn.execute("SELECT count(*) FROM paper_fills WHERE event_time>?", (before["event_time"],)).fetchone()[0] == 0,
                 "unaccounted fills after snapshot")

        commission = gross * DEFAULT_COMMISSION_RATE
        tax = gross * DEFAULT_DOMESTIC_STOCK_SELL_TAX_RATE
        cash_delta = gross - commission - tax
        pnl_delta = cash_delta - float(target["cost_basis"])
        _require(abs(float(before["cash_balance"]) + cash_delta - float(broker.get("cash_balance"))) < 10000,
                 "post-correction cash still outside Phase 0 tolerance")
        remaining = [r for r in positions if r["symbol"] != "035420" and int(r["qty"]) > 0]
        after = {
            "snapshot_id": RECOVERY_ID,
            "event_time": applied_at,
            "cash_balance": float(before["cash_balance"]) + cash_delta,
            "gross_market_value": float(before["gross_market_value"]) - float(target["market_value"]),
            "open_positions": len(remaining),
            "realized_pnl": float(before["realized_pnl"]) + pnl_delta,
            "unrealized_pnl": float(before["unrealized_pnl"]) - float(target["unrealized_pnl"]),
        }
        after["net_liquidation_value"] = after["cash_balance"] + after["gross_market_value"]
        audit = {
            "recovery_id": RECOVERY_ID, "local_order_id": ORDER_ID, "symbol": "035420",
            "source_trade_date": "2026-09-29", "source_broker_order_time": trade["order_time"],
            "broker_ref_sha256": BROKER_REF_HASH,
            "account_snapshot_as_of": observed.isoformat(),
            "broker_identity_link": "inferred_owner_approved_not_exact",
            "cost_basis": "research_assumption_not_broker_statement",
            "cost_model_version": DOMESTIC_STOCK_COST_MODEL_VERSION,
            "commission": commission, "tax": tax, "cash_delta": cash_delta,
            "realized_pnl_delta": pnl_delta,
            "valuation_basis": "stored_position_marks_not_fresh_quotes",
            "official_phase0_pass": False,
            "before_position": target, "before_snapshot": before, "after_snapshot": after,
        }
        if not execute:
            conn.rollback()
            return {**audit, "status": "ready_dry_run"}

        encoded = (json.dumps(audit, indent=2, sort_keys=True) + "\n").encode()
        fd = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as backup:
            backup.write(encoded)
            backup.flush()
            os.fsync(backup.fileno())
        conn.execute(
            "INSERT INTO paper_order_events VALUES (?, ?, ?, ?, ?)",
            (RECOVERY_ID, ORDER_ID, applied_at, "account_recovery_adjustment", json.dumps(audit, sort_keys=True)),
        )
        conn.execute(
            "UPDATE paper_orders SET status='externally_reconciled' WHERE order_id=? AND status='submission_unknown'",
            (ORDER_ID,),
        )
        _require(conn.execute("SELECT changes()").fetchone()[0] == 1, "unknown order transition failed")
        conn.execute(
            "UPDATE paper_positions SET opened_at=NULL, updated_at=?, qty=0, avg_price=0, last_price=?, "
            "market_value=0, cost_basis=0, realized_pnl=realized_pnl+?, unrealized_pnl=0 WHERE symbol='035420' AND qty=3",
            (applied_at, fill_price, pnl_delta),
        )
        _require(conn.execute("SELECT changes()").fetchone()[0] == 1, "position transition failed")
        conn.execute(
            "INSERT INTO paper_portfolio_snapshots(snapshot_id,event_time,cash_balance,gross_market_value,"
            "net_liquidation_value,open_positions,realized_pnl,unrealized_pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(after[k] for k in ("snapshot_id", "event_time", "cash_balance", "gross_market_value",
                                     "net_liquidation_value", "open_positions", "realized_pnl", "unrealized_pnl")),
        )
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
    _require(settings.trading_mode == "paper" and settings.kis_paper_account_lifecycle.account_epoch_id == "paper-2026-09-03",
             "wrong account epoch or trading mode")
    for helper in ("get_live_runtime_status.sh", "get_runtime_watchdog_status.sh"):
        status = json.loads(subprocess.check_output(["bash", str(ROOT / "scripts" / helper)], cwd=ROOT, text=True))
        if helper == "get_live_runtime_status.sh":
            _require(status.get("process_running") is False
                     and status.get("current_session_status") in {"weekend", "holiday", "overnight", "post-close"},
                     "runtime protected")
        else:
            _require(status.get("live_runtime_should_run") is False, "runtime should run")
    paths = [
        settings.runtime_data_dir / "reports/reconciliation/latest-paper-account-sync.json",
        settings.runtime_data_dir / EVIDENCE_PATH.relative_to("runtime-data"),
        settings.runtime_data_dir / "reports/broker-paper/latest-alignment.json",
    ]
    account, evidence, alignment = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    output_dir = settings.runtime_data_dir / "reports/codex"
    if args.execute:
        output_dir.mkdir(parents=True, exist_ok=True)
    mode = "rw" if args.execute else "ro"
    with sqlite3.connect(f"file:{settings.runtime_data_dir / 'dev.db'}?mode={mode}", uri=True, timeout=10) as conn:
        if not args.execute:
            conn.execute("PRAGMA query_only=ON")
        result = recover(
            conn, account=account, evidence=evidence, alignment=alignment,
            applied_at=datetime.now().astimezone().isoformat(), execute=args.execute,
            backup_path=output_dir / f"{RECOVERY_ID}-before.json",
        )
    result["source_report_sha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }
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
