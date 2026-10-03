"""One-off recovery tests for the September 29 paper sell timeout."""

import json
import sqlite3
import unittest
import uuid
from pathlib import Path

from app.storage.sqlite_store import SQLiteRuntimeStore


class Paper035420RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / ".tmp-tests" / "paper-035420-recovery" / str(uuid.uuid4())
        self.root.mkdir(parents=True)
        self.db = self.root / "dev.db"
        SQLiteRuntimeStore(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.order_id = "paper-order-close-online-20260929080014-175568-6d2ebe1e-037413"
        self.conn.execute(
            "INSERT INTO paper_orders VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
            (self.order_id, "035420", "2026-09-29T10:47:00+09:00", "sell", 3, 194600.0, "submission_unknown"),
        )
        self.conn.execute(
            "INSERT INTO ops_risk_events VALUES (?, ?, ?, ?, ?)",
            ("risk-unknown", "035420", "2026-09-29T10:47:00+09:00", "broker_paper_mirroring",
             json.dumps({"local_order_id": self.order_id, "failure": {
                 "category": "broker_network_error", "network_attempted": True
             }})),
        )
        self.conn.execute(
            "INSERT INTO paper_positions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("035420", "2026-09-29T10:26:59+09:00", "2026-09-29T10:26:59+09:00",
             3, 194729.205, 194700.0, 584100.0, 584187.615, -5295.6325, -87.615),
        )
        self.conn.execute(
            "INSERT INTO paper_portfolio_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("snapshot-before", "2026-09-29T10:26:59+09:00", 7003772.0725, 584100.0,
             7587872.0725, 1, -5295.6325, -87.615),
        )
        self.conn.commit()
        self.account = {
            "as_of": "2026-10-02T17:51:35+09:00", "ok": True,
            "local_account": {"latest_snapshot_time": "2026-09-29T10:26:59+09:00",
                              "cash_balance": 7003772.0725},
            "broker_account": {"mode": "paper", "positions": [], "cash_balance": 7588544.0},
        }
        self.alignment = {"aligned_at": "2026-09-06T07:10:53+09:00"}
        self.evidence = {
            "mode": "paper", "order_date": "20260929", "symbol": "035420",
            "pagination": {"pagination_complete": True, "records_returned": 1},
            "rows": [{
                "side": "01", "order_time": "104821", "order_qty": 3,
                "order_price": 194600.0, "filled_qty": 3,
                "avg_fill_price": 194700.0, "filled_amount": 584100.0,
                "remaining_qty": 0, "cancel_confirm_qty": 0, "reject_qty": 0,
                "linked_submission": False,
                "broker_ref_sha256": "61c479a5639092e8",
            }],
        }

    def tearDown(self):
        self.conn.close()

    def run_recovery(self, *, execute=False):
        from scripts.recover_paper_035420_sell_once import recover
        return recover(
            self.conn, account=self.account, evidence=self.evidence, alignment=self.alignment,
            applied_at="2026-10-03T12:00:00+09:00", execute=execute,
            backup_path=self.root / "before.json",
        )

    def rows(self, table):
        return [dict(row) for row in self.conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]

    def test_dry_run_does_not_mutate_accounting(self):
        before = self.rows("paper_positions")
        result = self.run_recovery()
        self.assertEqual(result["status"], "ready_dry_run")
        self.assertAlmostEqual(result["cash_delta"], 582844.185)
        self.assertEqual(self.rows("paper_positions"), before)
        self.assertFalse((self.root / "before.json").exists())

    def test_execute_preserves_history_and_records_inferred_resolution(self):
        old_snapshot = self.rows("paper_portfolio_snapshots")[0]
        result = self.run_recovery(execute=True)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.rows("paper_orders")[0]["status"], "externally_reconciled")
        self.assertEqual(self.rows("paper_positions")[0]["qty"], 0)
        self.assertEqual(self.rows("paper_portfolio_snapshots")[0], old_snapshot)
        self.assertAlmostEqual(self.rows("paper_portfolio_snapshots")[-1]["cash_balance"], 7586616.2575)
        self.assertEqual(self.rows("paper_fills"), [])
        self.assertEqual(self.rows("broker_paper_order_submissions"), [])
        audit = json.loads(self.rows("paper_order_events")[-1]["detail"])
        self.assertEqual(audit["broker_identity_link"], "inferred_owner_approved_not_exact")
        self.assertFalse(audit["official_phase0_pass"])
        self.assertTrue((self.root / "before.json").exists())
        self.assertEqual(self.run_recovery(execute=True)["status"], "already_applied")
        self.assertEqual(len(self.rows("paper_portfolio_snapshots")), 2)

    def test_incomplete_or_ambiguous_evidence_blocks(self):
        self.evidence["pagination"]["pagination_complete"] = False
        with self.assertRaises(ValueError):
            self.run_recovery(execute=True)
        self.evidence["pagination"]["pagination_complete"] = True
        self.evidence["rows"].append(dict(self.evidence["rows"][0]))
        self.evidence["pagination"]["records_returned"] = 2
        with self.assertRaises(ValueError):
            self.run_recovery(execute=True)
        self.assertEqual(self.rows("paper_positions")[0]["qty"], 3)

    def test_existing_accounting_or_changed_cash_blocks(self):
        self.conn.execute("UPDATE paper_portfolio_snapshots SET cash_balance=cash_balance+1")
        self.conn.commit()
        with self.assertRaises(ValueError):
            self.run_recovery(execute=True)
        self.assertEqual(self.rows("paper_positions")[0]["qty"], 3)

    def test_recovery_preserves_snapshot_mark_for_other_holdings(self):
        self.conn.execute(
            "INSERT INTO paper_positions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("005930", "2026-09-08T09:00:00+09:00", "2026-09-08T09:00:00+09:00",
             2, 50000.0, 50000.0, 100000.0, 100000.0, 0.0, 0.0),
        )
        self.conn.execute(
            "UPDATE paper_portfolio_snapshots SET gross_market_value=675000, "
            "net_liquidation_value=cash_balance+675000, unrealized_pnl=-10000"
        )
        self.conn.commit()
        self.account["broker_account"]["positions"] = [{"symbol": "005930", "holding_qty": 2}]
        result = self.run_recovery(execute=True)
        self.assertEqual(result["after_snapshot"]["gross_market_value"], 90900.0)
        self.assertAlmostEqual(result["after_snapshot"]["unrealized_pnl"], -9912.385)

    def test_existing_fill_blocks_duplicate_correction(self):
        self.conn.execute(
            "INSERT INTO paper_fills VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("existing-fill", self.order_id, "2026-09-29T10:48:21+09:00", 194700.0, 3, 87.615, 1168.2),
        )
        self.conn.commit()
        with self.assertRaises(ValueError):
            self.run_recovery(execute=True)
        self.assertEqual(self.rows("paper_orders")[0]["status"], "submission_unknown")

    def test_other_unknown_order_blocks_correction(self):
        self.conn.execute(
            "INSERT INTO paper_orders VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
            ("other-unknown", "005930", "2026-09-29T10:45:00+09:00", "buy", 1, 50000.0, "submission_unknown"),
        )
        self.conn.commit()
        with self.assertRaises(ValueError):
            self.run_recovery(execute=True)

    def test_broker_position_change_blocks_correction(self):
        self.account["broker_account"]["positions"] = [{"symbol": "035420", "holding_qty": 3}]
        with self.assertRaises(ValueError):
            self.run_recovery(execute=True)

    def test_sql_failure_rolls_back_state(self):
        self.conn.execute(
            "CREATE TRIGGER block_snapshot BEFORE INSERT ON paper_portfolio_snapshots "
            "BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
        )
        self.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.run_recovery(execute=True)
        self.assertEqual(self.rows("paper_orders")[0]["status"], "submission_unknown")
        self.assertEqual(self.rows("paper_positions")[0]["qty"], 3)
        self.assertEqual(len(self.rows("paper_portfolio_snapshots")), 1)


if __name__ == "__main__":
    unittest.main()
