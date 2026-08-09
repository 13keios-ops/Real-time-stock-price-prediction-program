from __future__ import annotations

import unittest

from scripts.trace_paper_kis_mismatch import (
    _apply_full_account_activity_resolution,
    _full_account_activity_summary,
)


class Phase0FullAccountActivityTraceTests(unittest.TestCase):
    def test_rate_limit_blocks_alignment_and_preserves_cooldown(self) -> None:
        trace = {"mismatch_count": 4}
        activity = {
            "status": "cooldown_active",
            "cooldown_until": "2026-08-10T00:48:27+09:00",
        }

        _apply_full_account_activity_resolution(trace, activity)

        resolution = trace["phase0_resolution"]
        self.assertEqual(resolution["status"], "blocked_full_account_history_rate_limited")
        self.assertFalse(resolution["automatic_alignment_allowed"])
        self.assertEqual(resolution["cooldown_until"], activity["cooldown_until"])

    def test_empty_history_requires_baseline_or_broker_support(self) -> None:
        trace = {"mismatch_count": 4}

        _apply_full_account_activity_resolution(
            trace,
            {"status": "blocked_history_unavailable_or_empty"},
        )

        resolution = trace["phase0_resolution"]
        self.assertEqual(resolution["status"], "blocked_requires_clean_baseline_or_broker_support")
        self.assertFalse(resolution["automatic_alignment_allowed"])

    def test_completed_probe_summary_excludes_unapproved_fields(self) -> None:
        completed = {
            "generated_at": "2026-08-10T00:50:00+09:00",
            "status": "resolved_external_or_unlinked_account_activity",
            "phase0_resolution": {"automatic_alignment_allowed": False},
            "account_number": "must-not-leak",
            "raw_response": {"secret": "must-not-leak"},
        }

        summary = _full_account_activity_summary(completed, {})

        self.assertEqual(summary["source"], "completed_probe")
        self.assertEqual(summary["status"], completed["status"])
        self.assertNotIn("account_number", summary)
        self.assertNotIn("raw_response", summary)

    def test_incomplete_pagination_cannot_resolve_phase0(self) -> None:
        trace = {"mismatch_count": 4}

        _apply_full_account_activity_resolution(
            trace,
            {"status": "blocked_incomplete_pagination"},
        )

        resolution = trace["phase0_resolution"]
        self.assertEqual(
            resolution["status"],
            "blocked_requires_complete_full_account_activity_evidence",
        )
        self.assertFalse(resolution["automatic_alignment_allowed"])


if __name__ == "__main__":
    unittest.main()
