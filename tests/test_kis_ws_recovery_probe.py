import json
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.services.kis_ws_recovery_probe import build_synthetic_ws_recovery_check


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


if __name__ == "__main__":
    unittest.main()
