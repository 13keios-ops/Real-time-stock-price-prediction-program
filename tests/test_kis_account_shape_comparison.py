import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.services.kis_account_shape_comparison import compare_kis_account_snapshot_checks


def _check(mode: str, *, positions: int = 1, extra: dict | None = None) -> dict:
    details = {
        "mode": mode,
        "shape_status": "ok",
        "required_attributes": [
            "position_row_count",
            "summary_row_count",
            "cash_balance",
            "stock_evaluation_amount",
            "total_asset_amount",
        ],
        "missing_attributes": [],
        "invalid_type_attributes": [],
        "position_row_count": positions,
        "summary_row_count": 1,
        "cash_balance_present": True,
        "stock_evaluation_present": True,
        "total_asset_present": True,
    }
    if extra:
        details.update(extra)
    return {
        "key": "account_snapshot",
        "status": "ok",
        "passed": True,
        "details": details,
        "account_no": "must-not-leak",
        "token": "must-not-leak",
        "cash_balance": 123456789,
    }


class KisAccountShapeComparisonTests(unittest.TestCase):
    def test_matching_shapes_pass_even_when_position_counts_differ(self) -> None:
        payload = compare_kis_account_snapshot_checks(
            _check("paper", positions=3),
            _check("live", positions=0),
            checked_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        )

        encoded = json.dumps(payload)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["shape_differences"], [])
        self.assertEqual(payload["row_count_observation"]["paper_position_row_count"], 3)
        self.assertEqual(payload["row_count_observation"]["live_position_row_count"], 0)
        self.assertNotIn("must-not-leak", encoded)
        self.assertNotIn("123456789", encoded)

    def test_shape_presence_difference_blocks(self) -> None:
        payload = compare_kis_account_snapshot_checks(
            _check("paper"),
            _check("live", extra={"total_asset_present": False}),
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["passed"])
        self.assertIn("paper_live_account_shape_differs", payload["blocking_reasons"])
        self.assertEqual(payload["shape_differences"][0]["field"], "total_asset_present")

    def test_wrong_mode_or_failed_check_blocks(self) -> None:
        live = _check("paper")
        live["status"] = "failed"
        live["passed"] = False
        live["details"]["shape_status"] = "invalid_value_types"

        payload = compare_kis_account_snapshot_checks(_check("paper"), live)

        self.assertFalse(payload["passed"])
        self.assertIn("live_account_snapshot_check_mode_mismatch", payload["blocking_reasons"])
        self.assertIn("live_account_snapshot_check_not_passed", payload["blocking_reasons"])
        self.assertIn("live_account_snapshot_shape_not_ok", payload["blocking_reasons"])

    def test_cli_compares_explicit_repo_local_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        temp_root = root / ".tmp-tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="account-shape-", dir=temp_root) as tmp:
            tmp_path = Path(tmp)
            paper_path = tmp_path / "paper.json"
            live_path = tmp_path / "live.json"
            output_path = tmp_path / "comparison.json"
            paper_path.write_text(json.dumps(_check("paper")), encoding="utf-8")
            live_path.write_text(json.dumps(_check("live")), encoding="utf-8")

            result = subprocess.run(
                [
                    "bash",
                    "scripts/compare_kis_account_snapshot_checks.sh",
                    "--paper-check-path",
                    str(paper_path),
                    "--live-check-path",
                    str(live_path),
                    "--output-path",
                    str(output_path),
                    "--fail-on-blocked",
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["status"], "ok")
            self.assertIn('"passed": true', result.stdout.lower())

    def test_cli_wrapper_help_is_offline(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["bash", "scripts/compare_kis_account_snapshot_checks.sh", "--help"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("--paper-check-path", result.stdout)
        self.assertIn("--live-check-path", result.stdout)
        self.assertIn("--output-path", result.stdout)


if __name__ == "__main__":
    unittest.main()
