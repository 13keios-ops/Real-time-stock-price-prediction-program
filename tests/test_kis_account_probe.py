import json
import subprocess
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.services.kis_account_probe import probe_kis_account_snapshot_check


@dataclass
class FakeAccountSnapshot:
    position_row_count: int = 1
    summary_row_count: int = 1
    cash_balance: int | None = 1000
    stock_evaluation_amount: int | None = 2000
    total_asset_amount: int | None = 3000
    account_no_masked: str = "1234****"
    product_code: str = "01"


class FakeReadOnlyClient:
    def __init__(self, snapshot: FakeAccountSnapshot | None = None, raises: Exception | None = None) -> None:
        self.snapshot = snapshot or FakeAccountSnapshot()
        self.raises = raises
        self.calls = 0

    def get_account_balance(self) -> FakeAccountSnapshot:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.snapshot


@dataclass
class ShapeDriftAccountSnapshot:
    position_row_count: int = 1
    summary_row_count: int = 1


@dataclass
class TypeDriftAccountSnapshot:
    position_row_count: int = 1
    summary_row_count: int = 1
    cash_balance: str = "1000"
    stock_evaluation_amount: int = 2000
    total_asset_amount: int = 3000


class KisAccountProbeTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_probe_builds_sanitized_account_snapshot_check(self) -> None:
        checked_at = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)
        client = FakeReadOnlyClient()

        check = probe_kis_account_snapshot_check(client, mode="paper", checked_at=checked_at)

        encoded = json.dumps(check, ensure_ascii=False)
        self.assertEqual(client.calls, 1)
        self.assertEqual(check["key"], "account_snapshot")
        self.assertEqual(check["status"], "ok")
        self.assertTrue(check["passed"])
        self.assertEqual(check["details"]["mode"], "paper")
        self.assertEqual(check["details"]["shape_status"], "ok")
        self.assertEqual(check["details"]["missing_attributes"], [])
        self.assertEqual(check["details"]["invalid_type_attributes"], [])
        self.assertEqual(check["details"]["position_row_count"], 1)
        self.assertNotIn("1234", encoded)
        self.assertNotIn("product_code", encoded)
        self.assertNotIn("cash_balance\": 1000", encoded)

    def test_probe_blocks_when_required_shape_attributes_are_missing(self) -> None:
        client = FakeReadOnlyClient(ShapeDriftAccountSnapshot())

        check = probe_kis_account_snapshot_check(client, mode="live")

        self.assertEqual(check["status"], "failed")
        self.assertFalse(check["passed"])
        self.assertEqual(check["summary"], "KIS account snapshot shape invalid")
        self.assertEqual(check["details"]["shape_status"], "missing_required_attributes")
        self.assertIn("cash_balance", check["details"]["missing_attributes"])
        self.assertEqual(check["details"]["invalid_type_attributes"], [])

    def test_probe_blocks_when_required_value_types_drift(self) -> None:
        client = FakeReadOnlyClient(TypeDriftAccountSnapshot())

        check = probe_kis_account_snapshot_check(client, mode="paper")

        encoded = json.dumps(check, ensure_ascii=False)
        self.assertEqual(check["status"], "failed")
        self.assertFalse(check["passed"])
        self.assertEqual(check["summary"], "KIS account snapshot value type invalid")
        self.assertEqual(check["details"]["shape_status"], "invalid_value_types")
        self.assertIn(
            {
                "attribute": "cash_balance",
                "expected": "number",
                "actual_type": "str",
            },
            check["details"]["invalid_type_attributes"],
        )
        self.assertNotIn("1000", encoded)

    def test_probe_blocks_when_summary_row_is_missing(self) -> None:
        client = FakeReadOnlyClient(FakeAccountSnapshot(summary_row_count=0))

        check = probe_kis_account_snapshot_check(client, mode="paper")

        self.assertEqual(check["status"], "failed")
        self.assertFalse(check["passed"])

    def test_probe_failure_is_sanitized(self) -> None:
        client = FakeReadOnlyClient(raises=RuntimeError("secret body should not leak"))

        check = probe_kis_account_snapshot_check(client, mode="paper")

        encoded = json.dumps(check, ensure_ascii=False)
        self.assertEqual(check["status"], "failed")
        self.assertFalse(check["passed"])
        self.assertEqual(check["details"]["error_type"], "RuntimeError")
        self.assertNotIn("secret body", encoded)

    def test_cli_wrapper_help_does_not_call_network(self) -> None:
        result = subprocess.run(
            ["bash", "scripts/probe_kis_account_snapshot.sh", "--help"],
            cwd=self._root(),
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("--mode", result.stdout)
        self.assertIn("--output-path", result.stdout)


if __name__ == "__main__":
    unittest.main()
