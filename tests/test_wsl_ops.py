import json
import datetime as dt
import subprocess
import sys
import tarfile
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from argparse import Namespace
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import wsl_ops


class BrokerPaperMirroringHealthTests(unittest.TestCase):
    def test_paper_mode_mirroring_is_informational_when_live_orders_disabled(self) -> None:
        result = wsl_ops.broker_paper_mirroring_health(
            {
                "TRADING_MODE": "paper",
                "ALLOW_LIVE_ORDERS": "false",
                "ENABLE_BROKER_PAPER_MIRRORING": "true",
            }
        )
        self.assertTrue(result["enabled"])
        self.assertEqual(result["level"], "info")
        self.assertEqual(result["status"], "expected_phase0_paper_mirroring")

    def test_mirroring_outside_phase0_profile_requires_review(self) -> None:
        result = wsl_ops.broker_paper_mirroring_health(
            {
                "TRADING_MODE": "live",
                "ALLOW_LIVE_ORDERS": "false",
                "ENABLE_BROKER_PAPER_MIRRORING": "true",
            }
        )
        self.assertTrue(result["enabled"])
        self.assertEqual(result["level"], "warning")
        self.assertEqual(result["status"], "review_required")


class WslOpsMarketSettingsTests(unittest.TestCase):
    def _status_at(self, timestamp_text: str, *, pre_open_warmup_minutes: int = 60) -> tuple[str, bool, bool]:
        class FixedDateTime(dt.datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                value = dt.datetime.fromisoformat(timestamp_text)
                if tz is not None:
                    return value.replace(tzinfo=tz)
                return value

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config"
            config.mkdir()
            (config / "market_calendar.toml").write_text(
                "session_open = '09:00'\nsession_close = '15:30'\nholidays = []\n",
                encoding="utf-8",
            )
            with patch("scripts.wsl_ops.dt.datetime", FixedDateTime):
                return wsl_ops.market_settings(root, pre_open_warmup_minutes=pre_open_warmup_minutes)

    def test_market_settings_distinguishes_overnight_from_pre_open_warmup(self) -> None:
        self.assertEqual(self._status_at("2026-05-21T00:30:00"), ("overnight", False, False))
        self.assertEqual(self._status_at("2026-05-21T07:59:59"), ("overnight", False, False))
        self.assertEqual(self._status_at("2026-05-21T08:00:00"), ("pre-open", False, True))
        self.assertEqual(self._status_at("2026-05-21T09:00:00"), ("regular-session", True, True))
        self.assertEqual(self._status_at("2026-05-21T15:31:00"), ("post-close", False, False))

    def test_market_settings_uses_configured_warmup_minutes(self) -> None:
        self.assertEqual(
            self._status_at("2026-05-21T07:30:00", pre_open_warmup_minutes=120),
            ("pre-open", False, True),
        )
        self.assertEqual(
            self._status_at("2026-05-21T08:30:00", pre_open_warmup_minutes=0),
            ("overnight", False, False),
        )


class WslOpsRecoveryExportTests(unittest.TestCase):
    def test_export_recovery_includes_live_ops_paths_and_excludes_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            dest = Path(tmp) / "exports"
            (root / "app/services").mkdir(parents=True)
            (root / "runtime-data/reports/alerts/local").mkdir(parents=True)
            (root / "runtime-data/reports/live-risk").mkdir(parents=True)
            (root / "runtime-data/reports/live-approvals").mkdir(parents=True)
            (root / "runtime-data/ops/2026-05-18").mkdir(parents=True)
            (root / "runtime-data/ml/registry-backups").mkdir(parents=True)
            (root / "runtime-data/logs/app").mkdir(parents=True)
            (root / "runtime-data/cache/kis").mkdir(parents=True)

            (root / "app/services/example.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "runtime-data/reports/alerts/local/alerts-2026-05-18.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "runtime-data/reports/live-risk/kill-switch.json").write_text("{}", encoding="utf-8")
            (root / "runtime-data/reports/live-approvals/latest-approval.json").write_text("{}", encoding="utf-8")
            (root / "runtime-data/ops/2026-05-18/live_audit_events.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "runtime-data/ml/registry-backups/registry-1.json").write_text("{}", encoding="utf-8")
            (root / "runtime-data/logs/app/app.log").write_text("secret-ish log\n", encoding="utf-8")
            (root / "runtime-data/cache/kis/token.json").write_text("token\n", encoding="utf-8")
            (root / ".env").write_text("KIS_APP_SECRET=secret\n", encoding="utf-8")
            (root / ".env.local").write_text("KIS_APP_SECRET=secret\n", encoding="utf-8")
            (root / ".env.example").write_text("KIS_APP_SECRET=example\n", encoding="utf-8")
            (root / "private.key").write_text("key\n", encoding="utf-8")
            (root / "id_ed25519").write_text("key\n", encoding="utf-8")

            args = Namespace(
                repo_root=str(root),
                destination_root=str(dest),
                package_prefix="recovery-test",
                keep_count=0,
                dry_run=False,
                include_artifacts=False,
                backup_mode="Manual",
                backup_reason="unit-test",
            )
            with redirect_stdout(StringIO()):
                wsl_ops.export_recovery(args)

            archives = list(dest.glob("recovery-test-*.tar.gz"))
            self.assertEqual(len(archives), 1)
            with tarfile.open(archives[0], "r:gz") as archive:
                names = set(archive.getnames())

            self.assertIn("runtime-data/reports/alerts/local/alerts-2026-05-18.jsonl", names)
            self.assertIn("runtime-data/reports/live-risk/kill-switch.json", names)
            self.assertIn("runtime-data/reports/live-approvals/latest-approval.json", names)
            self.assertIn("runtime-data/ops/2026-05-18/live_audit_events.jsonl", names)
            self.assertIn("runtime-data/ml/registry-backups/registry-1.json", names)
            self.assertNotIn(".env", names)
            self.assertNotIn(".env.local", names)
            self.assertNotIn(".env.example", names)
            self.assertNotIn("runtime-data/logs/app/app.log", names)
            self.assertNotIn("runtime-data/cache/kis/token.json", names)
            self.assertNotIn("private.key", names)
            self.assertNotIn("id_ed25519", names)



class WslOpsProcessMemoryTests(unittest.TestCase):
    def test_process_memory_status_reads_proc_kilobytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc_root = Path(tmp)
            status_dir = proc_root / "123"
            status_dir.mkdir()
            (status_dir / "status").write_text(
                "Name:\tpython\nVmSize:\t204800 kB\nVmHWM:\t153600 kB\nVmRSS:\t102400 kB\n",
                encoding="utf-8",
            )
            result = wsl_ops.process_memory_status(123, proc_root=proc_root)

        self.assertTrue(result["available"])
        self.assertEqual(result["rss_kb"], 102400)
        self.assertEqual(result["peak_rss_kb"], 153600)
        self.assertEqual(result["rss_mib"], 100.0)
        self.assertEqual(result["peak_rss_mib"], 150.0)


class WslOpsWatchdogRestartBackoffTests(unittest.TestCase):
    def test_restart_backoff_grows_and_is_capped(self) -> None:
        self.assertEqual(wsl_ops.live_runtime_restart_backoff_seconds(1, 60), 120)
        self.assertEqual(wsl_ops.live_runtime_restart_backoff_seconds(2, 60), 240)
        self.assertEqual(wsl_ops.live_runtime_restart_backoff_seconds(4, 60), 900)

    def test_restart_is_deferred_until_backoff_elapses(self) -> None:
        now = dt.datetime(2026, 7, 20, 9, 1, tzinfo=dt.timezone.utc)
        due, delay = wsl_ops.live_runtime_restart_is_due(
            consecutive_attempts=1,
            last_attempt_at="2026-07-20 09:00:00 +0000",
            now=now,
            interval_seconds=60,
        )
        self.assertFalse(due)
        self.assertEqual(delay, 120)

        due, delay = wsl_ops.live_runtime_restart_is_due(
            consecutive_attempts=1,
            last_attempt_at="2026-07-20 09:00:00 +0000",
            now=now + dt.timedelta(minutes=1),
            interval_seconds=60,
        )
        self.assertTrue(due)
        self.assertEqual(delay, 120)


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

    def test_aligned_marker_skips_initial_cash_mismatch_after_flat_realign(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime-data"
            (root / ".env").write_text("ENABLE_BROKER_PAPER_MIRRORING=true\nPAPER_INITIAL_CASH=500000\n", encoding="utf-8")
            alignment_dir = runtime / "reports" / "broker-paper"
            alignment_dir.mkdir(parents=True, exist_ok=True)
            (alignment_dir / "latest-alignment.json").write_text(
                json.dumps(
                    {
                        "ok": True,
                        "status": "aligned_to_broker_marker",
                        "aligned_at": "2026-06-09T19:45:39+09:00",
                        "broker_position_count": 0,
                        "baseline_snapshot": {
                            "cash_balance": 9301757.0,
                            "net_liquidation_value": 9301757.0,
                            "gross_market_value": 0.0,
                        },
                        "baseline_positions": [],
                    }
                ),
                encoding="utf-8",
            )

            def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                if "--kis-account-balance" in cmd:
                    self._write_account(runtime, cash=8_009_590.0, positions=[])
                if "--reconcile-paper-accounts" in cmd:
                    report_dir = runtime / "reports" / "reconciliation"
                    report_dir.mkdir(parents=True, exist_ok=True)
                    (report_dir / "latest-paper-account-sync.json").write_text(
                        json.dumps(
                            {
                                "ok": True,
                                "comparison": {
                                    "status": "aligned_waiting_first_submission",
                                    "mismatch_count": 0,
                                    "cash_gap": 0.0,
                                    "raw_cash_gap": 1_292_167.0,
                                    "total_asset_gap": 0.0,
                                    "balance_match": True,
                                    "total_asset_match": True,
                                    "order_mirroring_enabled": True,
                                    "mirrored_order_count": 0,
                                },
                                "local_account": {
                                    "cash_balance": 9_301_757.0,
                                    "net_liquidation_value": 9_301_757.0,
                                    "positions": [],
                                },
                                "broker_account": {
                                    "cash_balance": 8_009_590.0,
                                    "stock_evaluation_amount": 0.0,
                                    "total_asset_amount": 9_301_757.0,
                                    "positions": [],
                                },
                            }
                        ),
                        encoding="utf-8",
                    )
                return subprocess.CompletedProcess(cmd, 0)

            with patch("scripts.wsl_ops.subprocess.run", side_effect=fake_run):
                with redirect_stdout(StringIO()):
                    wsl_ops.verify_paper_dual_account_match(self._args(root, runtime))

            self.assertIn("PAPER_INITIAL_CASH=500000", (root / ".env").read_text(encoding="utf-8"))
            payload = json.loads((runtime / "reports" / "reconciliation" / "latest-paper-dual-account-match.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "matched_waiting_first_submission")
            self.assertFalse(payload["env"]["initial_cash_check_required"])
            self.assertEqual(payload["env"]["initial_cash_check_skipped_reason"], "broker_alignment_marker_active")

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
