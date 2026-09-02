import json
import unittest
from pathlib import Path

from app.config.settings import load_settings
from app.services.kis_paper_account_lifecycle import build_kis_paper_account_lifecycle


class KisPaperAccountLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.settings = load_settings(project_root=root, env={})

    @staticmethod
    def _history(baseline_at: str) -> dict:
        return {"phase0_epoch": {"baseline_at": baseline_at}}

    def test_current_account_dates_and_warning_windows(self) -> None:
        payload = build_kis_paper_account_lifecycle(
            self.settings,
            phase0_history=self._history("2026-09-03T00:00:00+09:00"),
            as_of="2026-09-03",
        )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["account"]["epoch_id"], "paper-2026-09-03")
        self.assertEqual(payload["account"]["expires_on"], "2026-12-03")
        self.assertEqual(payload["renewal"]["warning_start_on"], "2026-11-03")
        self.assertEqual(payload["renewal"]["urgent_start_on"], "2026-11-26")
        self.assertEqual(payload["renewal"]["days_until_expiry"], 91)
        self.assertFalse(payload["account"]["identifier_in_report"])

    def test_old_phase0_baseline_blocks_current_epoch(self) -> None:
        payload = build_kis_paper_account_lifecycle(
            self.settings,
            phase0_history=self._history("2026-08-15T00:20:42+09:00"),
            as_of="2026-09-03",
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["passed"])
        self.assertEqual(
            payload["phase0_baseline"]["status"],
            "baseline_predates_current_account",
        )
        self.assertIn(
            "phase0_baseline_predates_current_account",
            payload["blocking_reasons"],
        )

    def test_renewal_warning_urgent_and_expired_states(self) -> None:
        for as_of, expected_status, expected_overall in (
            ("2026-11-03", "renewal_due", "attention"),
            ("2026-11-26", "renewal_urgent", "attention"),
            ("2026-12-03", "expired", "blocked"),
        ):
            with self.subTest(as_of=as_of):
                payload = build_kis_paper_account_lifecycle(
                    self.settings,
                    phase0_history=self._history("2026-09-03T00:00:00+09:00"),
                    as_of=as_of,
                )
                self.assertEqual(payload["renewal"]["status"], expected_status)
                self.assertEqual(payload["status"], expected_overall)

    def test_report_shape_contains_no_secret_or_account_number(self) -> None:
        payload = build_kis_paper_account_lifecycle(
            self.settings,
            phase0_history=self._history("2026-09-03T00:00:00+09:00"),
            as_of="2026-09-03",
        )
        serialized = json.dumps(payload).lower()

        for forbidden in ("app_secret", "app_key", "access_token", "account_no"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(payload["safety"]["network_calls"], 0)
        self.assertEqual(payload["safety"]["order_calls"], 0)
        self.assertEqual(payload["safety"]["cancel_calls"], 0)


if __name__ == "__main__":
    unittest.main()
