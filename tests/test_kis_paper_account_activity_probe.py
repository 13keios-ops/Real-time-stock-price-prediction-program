import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.brokers.kis_quote_rest import KisDailyOrderFillRecord
from scripts.probe_kis_paper_account_activity import (
    _active_cooldown,
    build_success_report,
    load_probe_scope,
)


def _broker_row(
    *,
    order_date: str,
    branch_no: str,
    order_no: str,
    symbol: str,
    side: str,
    filled_qty: int,
) -> KisDailyOrderFillRecord:
    return KisDailyOrderFillRecord(
        mode="paper",
        order_date=order_date,
        broker_branch_no=branch_no,
        broker_order_no=order_no,
        original_order_no="",
        symbol=symbol,
        symbol_name="",
        side=side,
        side_name="",
        order_type_code="00",
        order_type_name="",
        order_time="100000",
        order_qty=filled_qty,
        order_price=1000.0,
        filled_qty=filled_qty,
        remaining_qty=0,
        avg_fill_price=1000.0,
        filled_amount=1000.0 * filled_qty,
        cancel_confirm_qty=0,
        reject_qty=0,
        cancel_yn=False,
        exchange_id="KRX",
        raw_output={"sensitive": "not serialized"},
    )


def _scope(
    *,
    local_positions: dict[str, int],
    broker_positions: dict[str, int],
) -> dict:
    return {
        "aligned_at": "2026-06-14T05:36:35+09:00",
        "account_as_of": "2026-08-07T16:56:21+09:00",
        "query_start": "20260614",
        "query_end": "20260807",
        "local_submissions": [
            {
                "local_order_id": "local-1",
                "broker_branch_no": "001",
                "broker_order_no": "100",
                "symbol": "005930",
                "event_time": "2026-06-15T10:00:00+09:00",
                "side": "buy",
                "qty": 5,
            }
        ],
        "baseline_positions": {},
        "broker_snapshot_positions": broker_positions,
        "local_positions": local_positions,
        "blocking_reasons": [],
    }


class KisPaperAccountActivityProbeTests(unittest.TestCase):
    def test_load_probe_scope_uses_alignment_to_account_snapshot_period(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "runtime.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE broker_paper_order_submissions (
                    submission_id TEXT,
                    local_order_id TEXT,
                    broker_branch_no TEXT,
                    broker_order_no TEXT,
                    symbol TEXT,
                    event_time TEXT,
                    side TEXT,
                    qty INTEGER
                )
                """
            )
            connection.executemany(
                "INSERT INTO broker_paper_order_submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("old", "old", "001", "099", "005930", "2026-06-13T10:00:00+09:00", "buy", 1),
                    ("new", "new", "001", "100", "005930", "2026-06-15T10:00:00+09:00", "buy", 5),
                ],
            )
            connection.commit()
            connection.close()
            alignment_path = root / "alignment.json"
            account_path = root / "account.json"
            alignment_path.write_text(
                json.dumps({"aligned_at": "2026-06-14T05:36:35+09:00", "baseline_positions": []}),
                encoding="utf-8",
            )
            account_path.write_text(
                json.dumps(
                    {
                        "as_of": "2026-08-07T16:56:21+09:00",
                        "broker_account": {"positions": [{"symbol": "005930", "holding_qty": 5}]},
                        "local_account": {"positions": [{"symbol": "005930", "qty": 5}]},
                    }
                ),
                encoding="utf-8",
            )

            scope = load_probe_scope(
                db_path=db_path,
                alignment_path=alignment_path,
                account_sync_path=account_path,
            )

        self.assertEqual(scope["query_start"], "20260614")
        self.assertEqual(scope["query_end"], "20260807")
        self.assertEqual(len(scope["local_submissions"]), 1)
        self.assertEqual(scope["broker_snapshot_positions"], {"005930": 5})

    def test_external_activity_is_identified_when_full_activity_rebuilds_snapshot(self) -> None:
        scope = _scope(local_positions={"005930": 5}, broker_positions={"005930": 10})
        rows = [
            _broker_row(
                order_date="20260615",
                branch_no="001",
                order_no="100",
                symbol="005930",
                side="02",
                filled_qty=5,
            ),
            _broker_row(
                order_date="20260720",
                branch_no="001",
                order_no="200",
                symbol="005930",
                side="02",
                filled_qty=5,
            ),
        ]

        report = build_success_report(
            scope=scope,
            broker_rows=rows,
            pagination={"pagination_complete": True, "page_limit_reached": False},
            generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(report["status"], "resolved_external_or_unlinked_account_activity")
        self.assertEqual(report["root_cause_scope"], "external_or_unlinked_broker_activity")
        self.assertEqual(report["broker_activity"]["rows_unlinked_to_local_submissions"], 1)
        self.assertTrue(report["position_reconstruction"]["activity_matches_broker_snapshot"])
        self.assertNotIn("001", json.dumps(report))
        self.assertNotIn("200", json.dumps(report))
        self.assertNotIn("sensitive", json.dumps(report))

    def test_local_divergence_is_identified_without_external_activity(self) -> None:
        scope = _scope(local_positions={"005930": 2}, broker_positions={"005930": 5})
        rows = [
            _broker_row(
                order_date="20260615",
                branch_no="001",
                order_no="100",
                symbol="005930",
                side="02",
                filled_qty=5,
            )
        ]

        report = build_success_report(
            scope=scope,
            broker_rows=rows,
            pagination={"pagination_complete": True, "page_limit_reached": False},
            generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(report["status"], "resolved_local_ledger_divergence")
        self.assertEqual(report["root_cause_scope"], "local_ledger_divergence")
        self.assertFalse(report["position_reconstruction"]["local_matches_broker_snapshot"])

    def test_incomplete_pagination_never_resolves_phase0(self) -> None:
        report = build_success_report(
            scope=_scope(local_positions={"005930": 5}, broker_positions={"005930": 5}),
            broker_rows=[
                _broker_row(
                    order_date="20260615",
                    branch_no="001",
                    order_no="100",
                    symbol="005930",
                    side="02",
                    filled_qty=5,
                )
            ],
            pagination={"pagination_complete": False, "page_limit_reached": True},
            generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(report["status"], "blocked_incomplete_pagination")
        self.assertFalse(report["position_reconstruction"]["evidence_complete"])
        self.assertFalse(report["phase0_resolution"]["automatic_alignment_allowed"])

    def test_empty_history_requires_baseline_or_broker_support(self) -> None:
        report = build_success_report(
            scope=_scope(local_positions={"005930": 5}, broker_positions={"005930": 5}),
            broker_rows=[],
            pagination={"pagination_complete": True, "page_limit_reached": False},
            generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(report["status"], "blocked_history_unavailable_or_empty")
        self.assertEqual(
            report["phase0_resolution"]["status"],
            "blocked_requires_clean_baseline_or_broker_support",
        )

    def test_rate_limit_cooldown_survives_cooldown_status_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attempt_path = Path(tmp) / "attempt.json"
            now = datetime(2026, 8, 9, 13, 0, tzinfo=timezone.utc)
            cooldown_until = now + timedelta(hours=2)
            attempt_path.write_text(
                json.dumps(
                    {
                        "status": "cooldown_active",
                        "generated_at": now.isoformat(),
                        "cooldown_until": cooldown_until.isoformat(),
                    }
                ),
                encoding="utf-8",
            )

            active_until = _active_cooldown(attempt_path, now=now + timedelta(minutes=30))

        self.assertEqual(active_until, cooldown_until)


if __name__ == "__main__":
    unittest.main()
