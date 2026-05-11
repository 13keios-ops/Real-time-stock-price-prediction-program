import json
import subprocess
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from argparse import Namespace
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import wsl_ops


class WslOpsPaperDualAccountMatchTests(unittest.TestCase):
    def _args(self, root: Path, runtime: Path, **overrides: object) -> Namespace:
        values = {
            "workspace_root": str(root),
            "runtime_data_dir": str(runtime),
            "sync_initial_cash": False,
            "align_to_broker": False,
            "refresh_dashboard": False,
            "fail_on_mismatch": False,
            "as_json": False,
        }
        values.update(overrides)
        return Namespace(**values)

    def _write_account(self, runtime: Path, *, cash: float = 1_000_000.0, positions: list[dict[str, object]] | None = None) -> None:
        positions = positions or []
        report_dir = runtime / "reports" / "kis-account"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "latest-account-paper.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "account_snapshot": {
                        "cash_balance": cash,
                        "position_row_count": len(positions),
                        "positions": positions,
                    },
                }
            ),
            encoding="utf-8",
        )

    def _write_reconciliation(
        self,
        runtime: Path,
        *,
        positions: list[dict[str, object]] | None = None,
        cash: float = 1_000_000.0,
        total: float = 1_000_000.0,
    ) -> None:
        positions = positions or []
        report_dir = runtime / "reports" / "reconciliation"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "latest-paper-account-sync.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "comparison": {
                        "mismatch_count": 0,
                        "cash_gap": 0.0,
                        "total_asset_gap": 0.0,
                        "balance_match": True,
                        "total_asset_match": True,
                        "order_mirroring_enabled": True,
                        "mirrored_order_count": 0,
                    },
                    "local_account": {
                        "cash_balance": cash,
                        "net_liquidation_value": total,
                        "positions": positions,
                    },
                    "broker_account": {
                        "cash_balance": cash,
                        "total_asset_amount": total,
                        "positions": positions,
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_align_to_broker_invokes_app_alignment_before_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime-data"
            (root / ".env").write_text("ENABLE_BROKER_PAPER_MIRRORING=true\nPAPER_INITIAL_CASH=1000000\n", encoding="utf-8")
            position = {"symbol": "005930", "qty": 1}
            calls: list[list[str]] = []

            def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                calls.append(cmd)
                if "--kis-account-balance" in cmd:
                    self._write_account(runtime, cash=900_000.0, positions=[position])
                if "--reconcile-paper-accounts" in cmd:
                    self._write_reconciliation(runtime, positions=[position], cash=900_000.0, total=1_000_000.0)
                return subprocess.CompletedProcess(cmd, 0)

            with patch("scripts.wsl_ops.subprocess.run", side_effect=fake_run):
                with redirect_stdout(StringIO()):
                    wsl_ops.verify_paper_dual_account_match(self._args(root, runtime, align_to_broker=True))

            flat = [" ".join(cmd) for cmd in calls]
            self.assertIn("--align-local-paper-to-broker", " ".join(flat))
            self.assertLess(
                next(i for i, text in enumerate(flat) if "--align-local-paper-to-broker" in text),
                next(i for i, text in enumerate(flat) if "--reconcile-paper-accounts" in text),
            )
            payload = json.loads((runtime / "reports" / "reconciliation" / "latest-paper-dual-account-match.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "matched_waiting_first_submission")
            self.assertFalse(payload["env"]["initial_cash_check_required"])

    def test_sync_initial_cash_refuses_open_broker_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime-data"
            (root / ".env").write_text("PAPER_INITIAL_CASH=1000000\n", encoding="utf-8")
            calls: list[list[str]] = []

            def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                calls.append(cmd)
                if "--kis-account-balance" in cmd:
                    self._write_account(runtime, cash=900_000.0, positions=[{"symbol": "005930", "qty": 1}])
                return subprocess.CompletedProcess(cmd, 0)

            with patch("scripts.wsl_ops.subprocess.run", side_effect=fake_run):
                with self.assertRaises(SystemExit):
                    with redirect_stdout(StringIO()):
                        wsl_ops.verify_paper_dual_account_match(
                            self._args(root, runtime, sync_initial_cash=True, align_to_broker=True)
                        )

            self.assertNotIn("--align-local-paper-to-broker", " ".join(" ".join(cmd) for cmd in calls))
            self.assertIn("PAPER_INITIAL_CASH=1000000", (root / ".env").read_text(encoding="utf-8"))

    def test_sync_initial_cash_updates_env_when_broker_has_no_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime-data"
            (root / ".env").write_text("PAPER_INITIAL_CASH=1000000\n", encoding="utf-8")

            def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                if "--kis-account-balance" in cmd:
                    self._write_account(runtime, cash=1_234_567.0, positions=[])
                if "--reconcile-paper-accounts" in cmd:
                    self._write_reconciliation(runtime, positions=[], cash=1_234_567.0, total=1_234_567.0)
                return subprocess.CompletedProcess(cmd, 0)

            with patch("scripts.wsl_ops.subprocess.run", side_effect=fake_run):
                with redirect_stdout(StringIO()):
                    wsl_ops.verify_paper_dual_account_match(self._args(root, runtime, sync_initial_cash=True))

            self.assertIn("PAPER_INITIAL_CASH=1234567", (root / ".env").read_text(encoding="utf-8"))
            payload = json.loads((runtime / "reports" / "reconciliation" / "latest-paper-dual-account-match.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["env"]["initial_cash_check_required"])
            self.assertTrue(payload["env"]["initial_cash_matches_broker_cash"])


if __name__ == "__main__":
    unittest.main()
