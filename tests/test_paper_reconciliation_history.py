import json
import tempfile
import unittest
from pathlib import Path

from app.services.paper_reconciliation_history import (
    build_paper_reconciliation_history_entry,
    load_paper_reconciliation_history,
    record_paper_reconciliation_history,
    summarize_paper_reconciliation_history,
)


def _payload(day: str, *, matched: bool = True) -> dict:
    mismatch_rows = [] if matched else [{"symbol": "005930", "local_qty": 1, "broker_qty": 0}]
    return {
        "ok": True,
        "as_of": f"{day}T17:00:00+09:00",
        "comparison": {
            "status": "aligned" if matched else "needs_review",
            "mismatch_count": 0 if matched else 1,
            "mismatch_rows": mismatch_rows,
            "positions_match": matched,
            "balance_match": matched,
            "total_asset_match": matched,
            "cash_gap": 0.0 if matched else 10000.0,
            "total_asset_gap": 0.0 if matched else 12000.0,
            "order_mirroring_enabled": True,
            "mirrored_order_count": 2,
        },
        "broker_account": {"account_no_masked": "1234****", "positions": mismatch_rows},
    }


class PaperReconciliationHistoryTests(unittest.TestCase):
    def test_entry_is_sanitized_and_requires_post_close_alignment(self) -> None:
        entry = build_paper_reconciliation_history_entry(
            _payload("2026-07-01"),
            market_session_status="post-close",
        )
        self.assertTrue(entry["eligible_for_phase0_gate"])
        self.assertTrue(entry["matched"])
        serialized = json.dumps(entry)
        self.assertNotIn("account_no", serialized)
        self.assertNotIn("broker_account", entry)

        pre_open = build_paper_reconciliation_history_entry(
            _payload("2026-07-02"),
            market_session_status="pre-open",
        )
        self.assertFalse(pre_open["eligible_for_phase0_gate"])

        no_submission_payload = _payload("2026-07-03")
        no_submission_payload["comparison"]["mirrored_order_count"] = 0
        no_submission = build_paper_reconciliation_history_entry(
            no_submission_payload,
            market_session_status="post-close",
        )
        self.assertFalse(no_submission["eligible_for_phase0_gate"])

        unavailable_payload = _payload("2026-07-04")
        unavailable_payload["ok"] = False
        unavailable = build_paper_reconciliation_history_entry(
            unavailable_payload,
            market_session_status="post-close",
        )
        self.assertFalse(unavailable["eligible_for_phase0_gate"])

        invalid_date_payload = _payload("2026-07-05")
        invalid_date_payload["as_of"] = "../../bad-path"
        invalid_date = build_paper_reconciliation_history_entry(
            invalid_date_payload,
            market_session_status="post-close",
        )
        self.assertIsNone(invalid_date["trade_date"])
        self.assertFalse(invalid_date["eligible_for_phase0_gate"])

    def test_summary_requires_ten_aligned_post_close_days(self) -> None:
        short_mismatch = summarize_paper_reconciliation_history([
            build_paper_reconciliation_history_entry(
                _payload("2026-06-30", matched=False),
                market_session_status="post-close",
            )
        ])
        self.assertEqual(short_mismatch["status"], "needs_review")

        entries = [
            build_paper_reconciliation_history_entry(
                _payload(f"2026-07-{day:02d}"),
                market_session_status="post-close",
            )
            for day in range(1, 11)
        ]
        summary = summarize_paper_reconciliation_history(entries)
        self.assertEqual(summary["status"], "ready")
        self.assertTrue(summary["ready"])
        self.assertEqual(summary["matched_days"], 10)
        self.assertEqual(summary["consecutive_matched_days"], 10)

        entries[-1] = build_paper_reconciliation_history_entry(
            _payload("2026-07-10", matched=False),
            market_session_status="post-close",
        )
        summary = summarize_paper_reconciliation_history(entries)
        self.assertEqual(summary["status"], "needs_review")
        self.assertFalse(summary["ready"])
        self.assertEqual(summary["latest_mismatch_symbols"], ["005930"])

    def test_record_overwrites_same_day_and_loads_latest_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_data_dir = Path(tmp)
            for day in range(1, 10):
                record_paper_reconciliation_history(
                    runtime_data_dir,
                    _payload(f"2026-07-{day:02d}"),
                    market_session_status="post-close",
                )
            first = record_paper_reconciliation_history(
                runtime_data_dir,
                _payload("2026-07-10"),
                market_session_status="post-close",
            )
            self.assertEqual(first["summary"]["status"], "ready")

            second = record_paper_reconciliation_history(
                runtime_data_dir,
                _payload("2026-07-10", matched=False),
                market_session_status="post-close",
            )
            self.assertEqual(second["summary"]["days_available"], 10)
            self.assertEqual(second["summary"]["status"], "needs_review")
            loaded = load_paper_reconciliation_history(runtime_data_dir)
            self.assertEqual(loaded["status"], "needs_review")
            self.assertTrue(Path(second["summary_markdown_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
