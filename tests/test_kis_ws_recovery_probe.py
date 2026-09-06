import json
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.kis_ws_recovery_probe import build_synthetic_ws_recovery_check
from app.services.ws_recovery_evidence import build_ws_recovery_check_from_data_quality


class KisWsRecoveryProbeTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_synthetic_ws_recovery_check_passes_without_network(self) -> None:
        check = build_synthetic_ws_recovery_check(
            checked_at=datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc),
        )

        encoded = json.dumps(check, ensure_ascii=False)
        self.assertEqual(check["key"], "ws_recovery")
        self.assertEqual(check["status"], "ok")
        self.assertTrue(check["passed"])
        self.assertEqual(check["details"]["evidence_type"], "synthetic_fault_injection")
        self.assertFalse(check["details"]["network_called"])
        self.assertEqual(check["details"]["stable"]["state"], "stable")
        self.assertEqual(check["details"]["stable"]["consecutive_reconnects"], 0)
        self.assertNotIn("synthetic_drop", encoded)

    def test_cli_wrapper_help_does_not_call_network(self) -> None:
        result = subprocess.run(
            ["bash", "scripts/probe_kis_ws_recovery.sh", "--help"],
            cwd=self._root(),
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("--output-path", result.stdout)
        self.assertIn("--stable-frame-reset-threshold", result.stdout)

    def test_real_recovery_check_uses_complete_data_quality_lineage(self) -> None:
        check = build_ws_recovery_check_from_data_quality(
            self._data_quality_report(),
            evaluated_at=datetime(2026, 9, 4, 15, 31, tzinfo=ZoneInfo("Asia/Seoul")),
        )

        self.assertIsNotNone(check)
        assert check is not None
        self.assertTrue(check["passed"])
        self.assertEqual(check["details"]["evidence_type"], "real_kis_ws_recovery")
        self.assertFalse(check["details"]["network_called"])
        self.assertTrue(check["details"]["source_network_observed"])
        self.assertEqual(check["details"]["checked_at"], "2026-09-04T15:30:00+09:00")
        self.assertEqual(check["details"]["subscription_restore_count"], 2)
        self.assertEqual(check["details"]["first_frame_after_restore_count"], 2)

    def test_real_recovery_check_fails_when_first_frame_lineage_is_incomplete(self) -> None:
        report = self._data_quality_report()
        report["latest_session_observability"]["websocket_reconnects"][
            "first_frame_after_restore_count"
        ] = 1

        check = build_ws_recovery_check_from_data_quality(
            report,
            evaluated_at=datetime(2026, 9, 4, 15, 31, tzinfo=ZoneInfo("Asia/Seoul")),
        )

        self.assertIsNotNone(check)
        assert check is not None
        self.assertFalse(check["passed"])
        self.assertIn(
            "ws_first_frame_after_restore_incomplete",
            check["details"]["blocking_reasons"],
        )

    def test_real_recovery_check_fails_closed_when_evidence_is_stale(self) -> None:
        check = build_ws_recovery_check_from_data_quality(
            self._data_quality_report(),
            evaluated_at=datetime(2026, 9, 4, 16, 1, tzinfo=ZoneInfo("Asia/Seoul")),
        )

        self.assertIsNotNone(check)
        assert check is not None
        self.assertFalse(check["passed"])
        self.assertIn("ws_recovery_evidence_stale", check["details"]["blocking_reasons"])

    @staticmethod
    def _data_quality_report() -> dict[str, object]:
        return {
            "completed_at": "2026-09-04T20:39:41+09:00",
            "latest_trade_date": "2026-09-04",
            "latest_intraday_coverage": {
                "status": "ok",
                "trade_date": "2026-09-04",
                "latest_raw_minute": "2026-09-04T15:30:00+09:00",
            },
            "latest_session_observability": {
                "websocket_reconnects": {
                    "status": "observed_no_storm",
                    "trade_date": "2026-09-04",
                    "count": 2,
                    "storm_count": 0,
                    "connected_count": 3,
                    "subscription_restore_count": 2,
                    "first_frame_after_restore_count": 2,
                    "last_first_frame_after_restore_at": "2026-09-04 15:00:13,612",
                    "reasons": {"no close frame received or sent": 2},
                },
                "raw_minute_gaps": {
                    "status": "gaps_detected",
                    "trade_date": "2026-09-04",
                    "unexpected_common_gaps_detected": False,
                },
            },
        }


if __name__ == "__main__":
    unittest.main()
