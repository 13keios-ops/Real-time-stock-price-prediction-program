from __future__ import annotations

import unittest

from scripts.summarize_broker_order_backlog import build_backlog_analysis, project_backlog_status


class BrokerOrderBacklogAnalysisTests(unittest.TestCase):
    def test_project_prior_day_unmatched_open_order_as_expired(self) -> None:
        status, reason = project_backlog_status(
            current_status="pending_lookup",
            order_date="20260610",
            synced_at="2026-06-14T05:00:00+09:00",
            order_qty=3,
            filled_qty=0,
            remaining_qty=3,
            applied_fill_qty=0,
        )

        self.assertEqual(status, "expired")
        self.assertEqual(reason, "prior_day_open_unfilled")

    def test_project_applied_fill_qty_as_filled_when_broker_row_dropped(self) -> None:
        status, reason = project_backlog_status(
            current_status="pending_lookup",
            order_date="20260610",
            synced_at="2026-06-14T05:00:00+09:00",
            order_qty=3,
            filled_qty=0,
            remaining_qty=3,
            applied_fill_qty=3,
        )

        self.assertEqual(status, "filled")
        self.assertEqual(reason, "applied_fill_qty_covers_order")

    def test_build_analysis_recommends_sync_when_all_open_rows_would_close(self) -> None:
        payload = build_backlog_analysis(
            rows=[
                {
                    "local_order_id": "order-1",
                    "symbol": "005930",
                    "submission_time": "2026-06-10T09:30:00+09:00",
                    "current_status": "pending_lookup",
                    "order_date": "20260610",
                    "order_qty": 3,
                    "filled_qty": 0,
                    "remaining_qty": 3,
                    "applied_fill_qty": 3,
                    "synced_at": "2026-06-14T05:00:00+09:00",
                },
                {
                    "local_order_id": "order-2",
                    "symbol": "005930",
                    "submission_time": "2026-06-10T09:31:00+09:00",
                    "current_status": "pending_lookup",
                    "order_date": "20260610",
                    "order_qty": 1,
                    "filled_qty": 0,
                    "remaining_qty": 1,
                    "applied_fill_qty": 0,
                    "synced_at": "2026-06-14T05:00:00+09:00",
                },
            ],
            latest_sync={"status": "ok", "open_order_count": 2, "final_order_count": 0},
            alignment={"aligned_at": "2026-06-09T19:45:00+09:00"},
            generated_at="2026-06-14T05:00:00+09:00",
        )

        self.assertEqual(payload["summary"]["current_open_order_count"], 2)
        self.assertEqual(payload["summary"]["projected_open_order_count"], 0)
        self.assertEqual(payload["summary"]["would_close_count"], 2)
        self.assertEqual(payload["recommendation"]["next_action"], "run_broker_paper_sync_after_fix")

    def test_build_analysis_marks_backlog_cleared_when_no_open_rows_remain(self) -> None:
        payload = build_backlog_analysis(
            rows=[
                {
                    "local_order_id": "order-1",
                    "symbol": "005930",
                    "submission_time": "2026-06-10T09:30:00+09:00",
                    "current_status": "filled",
                    "order_date": "20260610",
                    "order_qty": 3,
                    "filled_qty": 3,
                    "remaining_qty": 0,
                    "applied_fill_qty": 3,
                    "synced_at": "2026-06-14T05:00:00+09:00",
                },
            ],
            latest_sync={"status": "ok", "open_order_count": 0, "final_order_count": 1},
            alignment={"aligned_at": "2026-06-09T19:45:00+09:00"},
            generated_at="2026-06-14T05:00:00+09:00",
        )

        self.assertEqual(payload["summary"]["current_open_order_count"], 0)
        self.assertEqual(payload["summary"]["projected_open_order_count"], 0)
        self.assertEqual(payload["recommendation"]["next_action"], "backlog_cleared_no_action")


if __name__ == "__main__":
    unittest.main()
