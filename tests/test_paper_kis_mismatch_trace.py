import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.trace_paper_kis_mismatch import build_trace_report


class PaperKisMismatchTraceTests(unittest.TestCase):
    def test_account_sync_mismatches_override_stale_dual_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "trace.db"
            sqlite3.connect(db_path).close()
            dual_path = tmp_path / "dual.json"
            account_path = tmp_path / "account.json"
            broker_path = tmp_path / "broker.json"
            dual_path.write_text(
                json.dumps(
                    {
                        "comparison": {
                            "status": "needs_review",
                            "mismatch_rows": [
                                {"symbol": "005930", "status": "only_local", "local_qty": 2},
                                {"symbol": "373220", "status": "only_local", "local_qty": 1},
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            account_path.write_text(
                json.dumps(
                    {
                        "comparison": {
                            "status": "needs_review",
                            "mismatch_rows": [
                                {"symbol": "373220", "status": "only_local", "local_qty": 1},
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            broker_path.write_text(json.dumps({"status": "rate_limited"}), encoding="utf-8")

            report = build_trace_report(
                db_path=db_path,
                dual_match_path=dual_path,
                account_sync_path=account_path,
                broker_sync_path=broker_path,
                limit_per_table=3,
                include_auxiliary=False,
            )

        self.assertEqual(report["mismatch_source_report"], "paper_account_sync")
        self.assertEqual(report["symbols"], ["373220"])
        self.assertEqual(report["mismatch_count"], 1)

    def test_dual_report_is_fallback_when_account_sync_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "trace.db"
            sqlite3.connect(db_path).close()
            dual_path = tmp_path / "dual.json"
            account_path = tmp_path / "missing-account.json"
            broker_path = tmp_path / "broker.json"
            dual_path.write_text(
                json.dumps(
                    {
                        "comparison": {
                            "status": "needs_review",
                            "mismatch_rows": [
                                {"symbol": "005930", "status": "only_local", "local_qty": 2},
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            broker_path.write_text(json.dumps({"status": "rate_limited"}), encoding="utf-8")

            report = build_trace_report(
                db_path=db_path,
                dual_match_path=dual_path,
                account_sync_path=account_path,
                broker_sync_path=broker_path,
                limit_per_table=3,
                include_auxiliary=False,
            )

        self.assertEqual(report["mismatch_source_report"], "dual_account_match")
        self.assertEqual(report["symbols"], ["005930"])


    def test_classifies_kis_account_snapshot_vs_order_fill_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "trace.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                create table broker_paper_order_status_snapshots (
                    sync_id text,
                    local_order_id text,
                    broker_mode text,
                    symbol text,
                    synced_at text,
                    side text,
                    order_qty real,
                    filled_qty real,
                    applied_fill_qty real,
                    status text
                )
                """
            )
            conn.executemany(
                """
                insert into broker_paper_order_status_snapshots
                (sync_id, local_order_id, broker_mode, symbol, synced_at, side, order_qty, filled_qty, applied_fill_qty, status)
                values (?, ?, 'paper', ?, '2026-07-03T16:49:28+09:00', ?, ?, ?, ?, 'filled')
                """,
                [
                    ("sync-1", "local-buy", "035420", "buy", 2, 2, 2),
                    ("sync-2", "local-buy-2", "247540", "buy", 5, 5, 5),
                    ("sync-3", "local-sell-2", "247540", "sell", 5, 5, 5),
                ],
            )
            conn.commit()
            conn.close()
            dual_path = tmp_path / "dual.json"
            account_path = tmp_path / "account.json"
            broker_path = tmp_path / "broker.json"
            dual_path.write_text(json.dumps({"comparison": {"status": "ok", "mismatch_rows": []}}), encoding="utf-8")
            account_path.write_text(
                json.dumps(
                    {
                        "comparison": {
                            "status": "needs_review",
                            "mismatch_rows": [
                                {"symbol": "035420", "status": "only_local", "local_qty": 2, "broker_qty": 0},
                                {"symbol": "247540", "status": "only_broker", "local_qty": 0, "broker_qty": 5},
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            broker_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "open_order_count": 0,
                        "broker_rows_unlinked_to_submissions": 1,
                        "fallback_matched_orders": 0,
                        "ambiguous_fallback_key_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            report = build_trace_report(
                db_path=db_path,
                dual_match_path=dual_path,
                account_sync_path=account_path,
                broker_sync_path=broker_path,
                limit_per_table=3,
                include_auxiliary=False,
            )

        by_symbol = {row["symbol"]: row for row in report["symbol_summaries"]}
        self.assertEqual(report["broker_sync"]["broker_rows_unlinked_to_submissions"], 1)
        self.assertEqual(report["broker_sync"]["fallback_matched_orders"], 0)
        self.assertEqual(report["broker_sync"]["ambiguous_fallback_key_count"], 0)
        self.assertEqual(
            by_symbol["035420"]["likely_issue"],
            "broker_account_flat_but_order_fill_net_positive",
        )
        self.assertEqual(by_symbol["035420"]["broker_order_fill_net_qty"], 2)
        self.assertEqual(
            by_symbol["247540"]["likely_issue"],
            "broker_account_has_residual_qty_not_in_order_fill_net",
        )
        self.assertEqual(by_symbol["247540"]["broker_order_fill_net_qty"], 0)
        self.assertEqual(
            by_symbol["035420"]["root_cause_scope"],
            "kis_account_snapshot_vs_order_fill_ledger_divergence",
        )
        self.assertIn("2 symbol(s)", report["assessment"]["summary"])


    def test_marks_out_of_lookback_mirrored_history_as_incomplete_account_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "trace.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                create table broker_paper_order_status_snapshots (
                    sync_id text,
                    local_order_id text,
                    broker_mode text,
                    symbol text,
                    synced_at text,
                    side text,
                    order_qty real,
                    filled_qty real,
                    applied_fill_qty real,
                    status text
                )
                """
            )
            conn.executemany(
                """
                insert into broker_paper_order_status_snapshots
                values (?, ?, 'paper', '035420', ?, ?, ?, ?, ?, 'filled')
                """,
                [
                    ("sync-1", "buy-1", "2026-07-01T16:00:00+09:00", "buy", 2, 2, 2),
                    ("sync-2", "sell-1", "2026-07-02T16:00:00+09:00", "sell", 1, 1, 1),
                    ("sync-3", "buy-1", "2026-07-03T16:00:00+09:00", "buy", 2, 2, 2),
                ],
            )
            conn.commit()
            conn.close()
            dual_path = tmp_path / "dual.json"
            account_path = tmp_path / "account.json"
            broker_path = tmp_path / "broker.json"
            dual_path.write_text(json.dumps({"comparison": {"status": "ok", "mismatch_rows": []}}), encoding="utf-8")
            account_path.write_text(
                json.dumps(
                    {
                        "comparison": {
                            "status": "needs_review",
                            "mismatch_rows": [
                                {"symbol": "035420", "status": "only_local", "local_qty": 1, "broker_qty": 0}
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            broker_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "total_submissions": 2,
                        "order_fill_lookback_days": 3,
                        "broker_rows_returned": 0,
                    }
                ),
                encoding="utf-8",
            )

            report = build_trace_report(
                db_path=db_path,
                dual_match_path=dual_path,
                account_sync_path=account_path,
                broker_sync_path=broker_path,
                limit_per_table=3,
                include_auxiliary=False,
            )

        summary = report["symbol_summaries"][0]
        self.assertEqual(summary["broker_order_fill_net_qty"], 1)
        self.assertEqual(
            summary["likely_issue"],
            "account_snapshot_differs_from_out_of_lookback_mirrored_ledger",
        )
        self.assertEqual(
            summary["root_cause_scope"],
            "current_account_vs_historical_mirrored_order_ledger_unresolved",
        )
        self.assertEqual(report["broker_ledger_coverage"]["status"], "historical_mirrored_orders_only")
        self.assertFalse(report["broker_ledger_coverage"]["complete_account_activity_ledger"])
        self.assertFalse(report["phase0_resolution"]["automatic_alignment_allowed"])


    def test_applies_paper_alignment_cutoff_to_mirrored_order_net(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "dev.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                create table broker_paper_order_status_snapshots (
                    sync_id text, local_order_id text, broker_mode text, symbol text,
                    synced_at text, side text, order_qty real, filled_qty real,
                    applied_fill_qty real, status text
                );
                create table broker_paper_order_submissions (
                    local_order_id text, event_time text
                );
                """
            )
            conn.executemany(
                "insert into broker_paper_order_status_snapshots values (?, ?, 'paper', '035420', ?, 'buy', ?, ?, ?, 'filled')",
                [
                    ("sync-pre", "pre-alignment", "2026-07-03T16:00:00+09:00", 10, 10, 10),
                    ("sync-post", "post-alignment", "2026-07-03T16:00:00+09:00", 2, 2, 2),
                ],
            )
            conn.executemany(
                "insert into broker_paper_order_submissions values (?, ?)",
                [
                    ("pre-alignment", "2026-07-01T10:00:00+09:00"),
                    ("post-alignment", "2026-07-02T10:00:00+09:00"),
                ],
            )
            conn.commit()
            conn.close()
            marker_dir = tmp_path / "reports" / "broker-paper"
            marker_dir.mkdir(parents=True)
            marker_dir.joinpath("latest-alignment.json").write_text(
                json.dumps({"aligned_at": "2026-07-02T00:00:00+09:00"}),
                encoding="utf-8",
            )
            dual_path = tmp_path / "dual.json"
            account_path = tmp_path / "account.json"
            broker_path = tmp_path / "broker.json"
            dual_path.write_text(json.dumps({"comparison": {"status": "ok", "mismatch_rows": []}}), encoding="utf-8")
            account_path.write_text(
                json.dumps(
                    {
                        "comparison": {
                            "status": "needs_review",
                            "mismatch_rows": [
                                {"symbol": "035420", "status": "only_local", "local_qty": 2, "broker_qty": 0}
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            broker_path.write_text(
                json.dumps({"status": "ok", "total_submissions": 2, "order_fill_lookback_days": 3, "broker_rows_returned": 0}),
                encoding="utf-8",
            )

            report = build_trace_report(
                db_path=db_path,
                dual_match_path=dual_path,
                account_sync_path=account_path,
                broker_sync_path=broker_path,
                limit_per_table=3,
                include_auxiliary=False,
            )

        self.assertEqual(report["paper_alignment_cutoff"], "2026-07-02T00:00:00+09:00")
        self.assertEqual(report["symbol_summaries"][0]["broker_order_fill_net_qty"], 2)


    def test_separates_rejected_close_history_from_active_retry_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "trace.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                create table paper_orders (
                    order_id text, symbol text, event_time text, side text, qty integer,
                    limit_price real, status text
                );
                create table broker_paper_order_status_snapshots (
                    sync_id text, local_order_id text, broker_mode text, symbol text,
                    synced_at text, side text, order_qty real, filled_qty real,
                    applied_fill_qty real, status text
                );
                """
            )
            conn.executemany(
                "insert into paper_orders values (?, '005930', ?, 'sell', 1, 70000, 'rejected')",
                [
                    ("old-close", "2026-07-01T15:19:00+09:00"),
                    ("active-close", "2026-07-03T15:18:00+09:00"),
                ],
            )
            conn.execute(
                "insert into broker_paper_order_status_snapshots values (?, ?, 'paper', '005930', ?, 'buy', 1, 1, 1, 'filled')",
                ("sync-1", "local-buy", "2026-07-03T16:00:00+09:00"),
            )
            conn.commit()
            conn.close()
            dual_path = tmp_path / "dual.json"
            account_path = tmp_path / "account.json"
            broker_path = tmp_path / "broker.json"
            dual_path.write_text(
                json.dumps({"comparison": {"status": "ok", "mismatch_rows": []}}),
                encoding="utf-8",
            )
            account_path.write_text(
                json.dumps(
                    {
                        "comparison": {
                            "status": "needs_review",
                            "mismatch_rows": [
                                {"symbol": "005930", "status": "only_local", "local_qty": 1, "broker_qty": 0}
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            broker_path.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
            report = build_trace_report(
                db_path=db_path,
                dual_match_path=dual_path,
                account_sync_path=account_path,
                broker_sync_path=broker_path,
                limit_per_table=3,
                include_auxiliary=False,
            )

        summary = report["symbol_summaries"][0]
        activity = summary["rejected_close_order_activity"]
        self.assertEqual(activity["lifetime_count"], 2)
        self.assertEqual(activity["recent_count"], 1)
        self.assertEqual(activity["recent_unique_minutes"], 1)
        self.assertIn("active_rejected_local_close_retry", summary["likely_issue"])

    def test_exposes_sanitized_account_snapshot_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "trace.db"
            sqlite3.connect(db_path).close()
            dual_path = tmp_path / "dual.json"
            account_path = tmp_path / "account.json"
            broker_path = tmp_path / "broker.json"
            dual_path.write_text(json.dumps({"comparison": {"status": "ok", "mismatch_rows": []}}), encoding="utf-8")
            account_path.write_text(
                json.dumps(
                    {
                        "as_of": "2026-07-31T16:55:06+09:00",
                        "comparison": {
                            "status": "needs_review",
                            "latest_broker_fetch_time": "2026-07-31T16:55:05+09:00",
                            "order_mirroring_enabled": True,
                            "mirrored_order_count": 320,
                            "mismatch_rows": [
                                {"symbol": "005930", "status": "only_local", "local_qty": 1, "broker_qty": 0}
                            ],
                        },
                        "broker_account": {
                            "mode": "paper",
                            "product_code": "01",
                            "cash_balance": 1000000,
                            "stock_evaluation_amount": 0,
                            "total_asset_amount": 1000000,
                            "position_row_count": 0,
                            "summary_row_count": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )
            broker_path.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
            report = build_trace_report(
                db_path=db_path,
                dual_match_path=dual_path,
                account_sync_path=account_path,
                broker_sync_path=broker_path,
                limit_per_table=3,
                include_auxiliary=False,
            )

        evidence = report["account_snapshot_evidence"]
        self.assertTrue(evidence["available"])
        self.assertEqual(evidence["mode"], "paper")
        self.assertEqual(evidence["product_code"], "01")
        self.assertTrue(evidence["shape_complete"])
        self.assertNotIn("account_no_masked", evidence)


if __name__ == "__main__":
    unittest.main()
