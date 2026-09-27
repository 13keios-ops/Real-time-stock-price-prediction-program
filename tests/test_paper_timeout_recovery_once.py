"""Checks for the owner-approved September paper correction."""

import json
import sqlite3
import unittest
import uuid
from pathlib import Path

from app.storage.sqlite_store import SQLiteRuntimeStore


class PaperTimeoutRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / ".tmp-tests" / "timeout-recovery" / str(uuid.uuid4())
        self.root.mkdir(parents=True)
        self.db = self.root / "dev.db"
        SQLiteRuntimeStore(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.order_id = "paper-order-close-online-20260908080016-138040-11b61ad7-081914"
        self.conn.execute("INSERT INTO paper_orders VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
                          (self.order_id, "373220", "2026-09-08T15:01:00+09:00", "sell", 1, 349500., "rejected"))
        self.conn.execute("INSERT INTO paper_order_events VALUES (?, ?, ?, ?, ?)",
                          ("original-rejection", self.order_id, "2026-09-08T15:01:00+09:00", "rejected", "timeout"))
        failure = {"local_order_id": self.order_id, "failure": {"category": "broker_network_error", "network_attempted": True}}
        self.conn.execute("INSERT INTO ops_risk_events VALUES (?, ?, ?, ?, ?)",
                          ("original-risk", "373220", "2026-09-08T15:01:00+09:00", "broker_paper_mirroring", json.dumps(failure)))
        self.conn.execute("INSERT INTO paper_positions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          ("373220", "2026-09-08T14:40:44+09:00", "2026-09-08T14:40:44+09:00", 1, 351052.65, 351000., 351000., 351052.65, -5363.15, -52.65))
        self.conn.execute("INSERT INTO paper_portfolio_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          ("original-snapshot", "2026-09-21T14:48:59+09:00", 7248387.22, 351000., 7599387.22, 1, -92017.795, -52.65))
        self.conn.commit()
        self.account = {"as_of": "2026-09-24T16:40:13+09:00", "ok": True,
                        "local_account": {"latest_snapshot_time": "2026-09-21T14:48:59+09:00", "cash_balance": 7248387.22},
                        "broker_account": {"mode": "paper", "positions": [], "cash_balance": 7598981., "total_asset_amount": 7598981., "stock_evaluation_amount": 0.}}
        self.alignment = {"aligned_at": "2026-09-06T07:10:53+09:00"}
        self.activity = {"pagination": {"pagination_complete": True},
                         "scope": {"alignment_at": self.alignment["aligned_at"], "account_snapshot_as_of": self.account["as_of"]},
                         "position_reconstruction": {"evidence_complete": True, "activity_matches_broker_snapshot": True,
                            "rows": [{"symbol": "373220", "local_qty": 1, "broker_snapshot_qty": 0, "full_activity_qty": 0}]}}

    def tearDown(self):
        self.conn.close()

    def run_recovery(self, *, execute=False):
        from scripts.recover_paper_timeout_sell_once import recover
        return recover(self.conn, account=self.account, activity=self.activity, alignment=self.alignment,
                       applied_at="2026-09-27T22:00:00+09:00", execute=execute,
                       backup_path=self.root / "before.json")

    def rows(self, table):
        return [dict(r) for r in self.conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]

    def test_dry_run_is_read_only(self):
        before = self.rows("paper_positions")
        result = self.run_recovery()
        self.assertEqual(result["status"], "ready_dry_run")
        self.assertAlmostEqual(result["cash_delta"], 348748.575)
        self.assertEqual(self.rows("paper_positions"), before)
        self.assertFalse((self.root / "before.json").exists())

    def test_preserves_history_without_fabricating_fills(self):
        old_order = self.rows("paper_orders")
        old_event = self.rows("paper_order_events")[0]
        old_snapshot = self.rows("paper_portfolio_snapshots")[0]
        result = self.run_recovery(execute=True)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.rows("paper_orders"), old_order)
        self.assertEqual(self.rows("paper_order_events")[0], old_event)
        self.assertEqual(self.rows("paper_portfolio_snapshots")[0], old_snapshot)
        self.assertEqual(self.rows("paper_fills"), [])
        self.assertEqual(self.rows("broker_paper_order_submissions"), [])
        self.assertEqual(self.rows("paper_positions")[0]["qty"], 0)
        self.assertAlmostEqual(self.rows("paper_portfolio_snapshots")[-1]["cash_balance"], 7597135.795)
        audit = json.loads(self.rows("paper_order_events")[-1]["detail"])
        self.assertEqual(audit["broker_identity_link"], "inferred_owner_approved_not_exact")
        self.assertEqual(audit["cost_basis"], "research_assumption_not_broker_statement")
        self.assertFalse(audit["official_phase0_pass"])
        self.assertTrue((self.root / "before.json").exists())

    def test_second_execution_cannot_apply_twice(self):
        self.run_recovery(execute=True)
        before = self.rows("paper_portfolio_snapshots")
        self.assertEqual(self.run_recovery(execute=True)["status"], "already_applied")
        self.assertEqual(self.rows("paper_portfolio_snapshots"), before)

    def test_sql_failure_rolls_back_all_changes(self):
        self.conn.execute("CREATE TRIGGER block_snapshot BEFORE INSERT ON paper_portfolio_snapshots BEGIN SELECT RAISE(ABORT, 'forced failure'); END")
        self.conn.commit()
        before = self.rows("paper_positions")
        with self.assertRaises(sqlite3.IntegrityError):
            self.run_recovery(execute=True)
        self.assertEqual(self.rows("paper_positions"), before)
        self.assertEqual(len(self.rows("paper_order_events")), 1)
        self.assertEqual(len(self.rows("paper_portfolio_snapshots")), 1)

    def test_incomplete_evidence_blocks_execution(self):
        self.activity["pagination"]["pagination_complete"] = False
        with self.assertRaises(ValueError):
            self.run_recovery(execute=True)
        self.assertEqual(self.rows("paper_positions")[0]["qty"], 1)

    def test_changed_cash_blocks_stale_plan(self):
        self.conn.execute("UPDATE paper_portfolio_snapshots SET cash_balance=cash_balance+1")
        self.conn.commit()
        with self.assertRaises(ValueError):
            self.run_recovery(execute=True)

    def test_existing_fill_blocks_duplicate_accounting(self):
        self.conn.execute("INSERT INTO paper_fills VALUES (?, ?, ?, ?, ?, ?, ?)",
                          ("already-filled", self.order_id, "2026-09-08T15:03:22+09:00", 349500., 1, 52.425, 699.))
        self.conn.commit()
        with self.assertRaises(ValueError):
            self.run_recovery(execute=True)

    def test_newer_unchanged_account_observation_is_allowed(self):
        self.account["as_of"] = "2026-09-25T08:20:08+09:00"
        self.assertEqual(self.run_recovery()["status"], "ready_dry_run")

    def test_newer_changed_broker_position_blocks(self):
        self.account["as_of"] = "2026-09-25T08:20:08+09:00"
        self.account["broker_account"]["positions"] = [{"symbol": "373220", "holding_qty": 1}]
        with self.assertRaises(ValueError):
            self.run_recovery(execute=True)

    def test_existing_backup_blocks_without_mutation(self):
        (self.root / "before.json").touch()
        before = self.rows("paper_positions")
        with self.assertRaises(FileExistsError):
            self.run_recovery(execute=True)
        self.assertEqual(self.rows("paper_positions"), before)

    def test_old_epoch_position_is_preserved_but_excluded(self):
        self.conn.execute("INSERT INTO paper_positions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          ("207940", "2026-04-28T11:30:00+09:00", "2026-04-28T11:30:00+09:00", 1, 1515454.5, 1515454.5, 1515454.5, 1515454.5, 0., 0.))
        self.conn.commit()
        old = self.rows("paper_positions")[1]
        result = self.run_recovery(execute=True)
        self.assertEqual(result["after_snapshot"]["gross_market_value"], 0)
        self.assertEqual(result["after_snapshot"]["open_positions"], 0)
        self.assertEqual(self.rows("paper_positions")[1], old)


if __name__ == "__main__":
    unittest.main()
