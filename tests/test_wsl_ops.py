import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from argparse import Namespace
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import wsl_ops


class WslOpsPaperDualAccountMatchTests(unittest.TestCase):
    def test_parse_args_keeps_powershell_style_verify_aliases(self) -> None:
        argv = [
            "wsl_ops.py",
            "verify-paper-dual-account-match",
            "-SyncInitialCash",
            "-AlignToBroker",
            "-RefreshDashboard",
            "-FailOnMismatch",
            "-AsJson",
        ]
        with patch.object(sys, "argv", argv):
            args = wsl_ops.parse_args()

        self.assertTrue(args.sync_initial_cash)
        self.assertTrue(args.align_to_broker)
        self.assertTrue(args.refresh_dashboard)
        self.assertTrue(args.fail_on_mismatch)
        self.assertTrue(args.as_json)

    def test_account_position_count_prefers_reported_count_and_falls_back_to_positions(self) -> None:
        self.assertEqual(wsl_ops.account_position_count({"position_row_count": "2", "positions": []}), 2)
        self.assertEqual(wsl_ops.account_position_count({"positions": [{"symbol": "005930", "qty": 1}]}), 1)

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

    def _write_broken_account(self, runtime: Path) -> None:
        report_dir = runtime / "reports" / "kis-account"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "latest-account-paper.json").write_text(
            json.dumps({"ok": True, "account_snapshot": None}),
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
                next(i for i, text in enumerate(flat) if "--sync-broker-paper-orders" in text),
            )
            self.assertLess(
                next(i for i, text in enumerate(flat) if "--sync-broker-paper-orders" in text),
                next(i for i, text in enumerate(flat) if "--reconcile-paper-accounts" in text),
            )
            payload = json.loads((runtime / "reports" / "reconciliation" / "latest-paper-dual-account-match.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "matched_waiting_first_submission")
            self.assertFalse(payload["env"]["initial_cash_check_required"])

    def test_align_failure_propagates_and_skips_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime-data"
            (root / ".env").write_text("ENABLE_BROKER_PAPER_MIRRORING=true\nPAPER_INITIAL_CASH=1000000\n", encoding="utf-8")
            calls: list[list[str]] = []

            def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                calls.append(cmd)
                if "--kis-account-balance" in cmd:
                    self._write_account(runtime, cash=900_000.0, positions=[{"symbol": "005930", "qty": 1}])
                if "--align-local-paper-to-broker" in cmd:
                    raise subprocess.CalledProcessError(1, cmd)
                return subprocess.CompletedProcess(cmd, 0)

            with patch("scripts.wsl_ops.subprocess.run", side_effect=fake_run):
                with self.assertRaises(subprocess.CalledProcessError):
                    with redirect_stdout(StringIO()):
                        wsl_ops.verify_paper_dual_account_match(self._args(root, runtime, align_to_broker=True))

            flat = " ".join(" ".join(cmd) for cmd in calls)
            self.assertIn("--align-local-paper-to-broker", flat)
            self.assertNotIn("--sync-broker-paper-orders", flat)
            self.assertFalse((runtime / "reports" / "reconciliation" / "latest-paper-dual-account-match.json").exists())

    def test_missing_env_file_fails_before_kis_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime-data"
            calls: list[list[str]] = []

            def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0)

            with patch("scripts.wsl_ops.subprocess.run", side_effect=fake_run):
                with self.assertRaises(SystemExit):
                    with redirect_stdout(StringIO()):
                        wsl_ops.verify_paper_dual_account_match(self._args(root, runtime))

            self.assertEqual(calls, [])

    def test_missing_account_snapshot_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime-data"
            (root / ".env").write_text("PAPER_INITIAL_CASH=1000000\n", encoding="utf-8")
            calls: list[list[str]] = []

            def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                calls.append(cmd)
                if "--kis-account-balance" in cmd:
                    self._write_broken_account(runtime)
                return subprocess.CompletedProcess(cmd, 0)

            with patch("scripts.wsl_ops.subprocess.run", side_effect=fake_run):
                with self.assertRaises(SystemExit):
                    with redirect_stdout(StringIO()):
                        wsl_ops.verify_paper_dual_account_match(self._args(root, runtime))

            flat = " ".join(" ".join(cmd) for cmd in calls)
            self.assertIn("--kis-account-balance", flat)
            self.assertNotIn("--sync-broker-paper-orders", flat)

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

    def test_sync_initial_cash_refuses_missing_or_zero_cash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime-data"
            (root / ".env").write_text("PAPER_INITIAL_CASH=1000000\n", encoding="utf-8")
            calls: list[list[str]] = []

            def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                calls.append(cmd)
                if "--kis-account-balance" in cmd:
                    self._write_account(runtime, cash=0.0, positions=[])
                return subprocess.CompletedProcess(cmd, 0)

            with patch("scripts.wsl_ops.subprocess.run", side_effect=fake_run):
                with self.assertRaises(SystemExit):
                    with redirect_stdout(StringIO()):
                        wsl_ops.verify_paper_dual_account_match(self._args(root, runtime, sync_initial_cash=True))

            flat = " ".join(" ".join(cmd) for cmd in calls)
            self.assertIn("--kis-account-balance", flat)
            self.assertNotIn("--sync-broker-paper-orders", flat)
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

    def test_fail_on_mismatch_exits_after_writing_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime-data"
            (root / ".env").write_text("ENABLE_BROKER_PAPER_MIRRORING=true\nPAPER_INITIAL_CASH=1000000\n", encoding="utf-8")

            def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                if "--kis-account-balance" in cmd:
                    self._write_account(runtime, cash=1_000_000.0, positions=[])
                if "--reconcile-paper-accounts" in cmd:
                    report_dir = runtime / "reports" / "reconciliation"
                    report_dir.mkdir(parents=True, exist_ok=True)
                    (report_dir / "latest-paper-account-sync.json").write_text(
                        json.dumps(
                            {
                                "ok": False,
                                "comparison": {
                                    "mismatch_count": 1,
                                    "cash_gap": 50.0,
                                    "total_asset_gap": 50.0,
                                    "balance_match": False,
                                    "total_asset_match": False,
                                    "order_mirroring_enabled": True,
                                    "mirrored_order_count": 1,
                                },
                                "local_account": {"cash_balance": 950_000.0, "net_liquidation_value": 950_000.0, "positions": []},
                                "broker_account": {"cash_balance": 1_000_000.0, "total_asset_amount": 1_000_000.0, "positions": []},
                            }
                        ),
                        encoding="utf-8",
                    )
                return subprocess.CompletedProcess(cmd, 0)

            with patch("scripts.wsl_ops.subprocess.run", side_effect=fake_run):
                with self.assertRaises(SystemExit):
                    with redirect_stdout(StringIO()):
                        wsl_ops.verify_paper_dual_account_match(self._args(root, runtime, fail_on_mismatch=True))

            payload = json.loads((runtime / "reports" / "reconciliation" / "latest-paper-dual-account-match.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
