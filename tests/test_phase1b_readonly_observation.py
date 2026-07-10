import json
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.brokers.kis_auth import KisAccessToken
from app.config.settings import load_settings
from app.services.phase1b_readonly_observation import (
    build_phase1b_readonly_preflight,
    run_phase1b_readonly_observation,
)


@dataclass
class FakeSnapshot:
    position_row_count: int = 1
    summary_row_count: int = 1
    cash_balance: int = 1000
    stock_evaluation_amount: int = 2000
    total_asset_amount: int = 3000


class FakeReadOnlyClient:
    def __init__(self, snapshot: FakeSnapshot | None = None) -> None:
        self.snapshot = snapshot or FakeSnapshot()
        self._headers = {"date": "Fri, 10 Jul 2026 00:00:00 GMT"}
        self.account_calls = 0
        self.account_max_pages: list[int] = []
        self.quote_calls = 0

    @property
    def last_response_headers(self) -> dict[str, str]:
        return dict(self._headers)

    def get_account_balance(self, *, max_pages: int = 10) -> FakeSnapshot:
        self.account_calls += 1
        self.account_max_pages.append(max_pages)
        return self.snapshot

    def get_current_price(self, *, symbol: str, market_code: str = "J") -> object:
        self.quote_calls += 1
        return object()


class FakeTokenManager:
    def __init__(self, token: KisAccessToken | None = None, raises: Exception | None = None) -> None:
        self.token = token
        self.raises = raises
        self.calls: list[bool] = []

    def get_access_token(self, *, force_refresh: bool = False) -> KisAccessToken:
        self.calls.append(force_refresh)
        if self.raises is not None:
            raise self.raises
        assert self.token is not None
        return self.token


class Phase1bReadOnlyObservationTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _settings(self, runtime_root: Path, *, live_credentials: bool = True):
        env = {
            "TRADING_MODE": "paper",
            "ALLOW_LIVE_ORDERS": "false",
            "RUNTIME_DATA_DIR": str(runtime_root),
            "KIS_APP_KEY_PAPER": "paper-key",
            "KIS_APP_SECRET_PAPER": "paper-secret",
            "KIS_ACCOUNT_NO_PAPER": "12345678",
            "KIS_PRODUCT_CODE_PAPER": "",
        }
        if live_credentials:
            env.update(
                {
                    "KIS_APP_KEY_LIVE": "live-key",
                    "KIS_APP_SECRET_LIVE": "live-secret",
                    "KIS_ACCOUNT_NO_LIVE": "87654321",
                    "KIS_PRODUCT_CODE_LIVE": "01",
                }
            )
        return load_settings(project_root=self._root(), env=env)

    def test_preflight_blocks_missing_live_credentials_without_leaking_values(self) -> None:
        with tempfile.TemporaryDirectory(dir=self._root() / ".tmp-tests") as tmp:
            settings = self._settings(Path(tmp), live_credentials=False)
            client = FakeReadOnlyClient()
            payload = build_phase1b_readonly_preflight(
                settings,
                readonly_client_factory=lambda *_args, **_kwargs: client,
            )

        encoded = json.dumps(payload)
        self.assertFalse(payload["passed"])
        self.assertIn("live_quote_credentials_present", payload["blocking_reasons"])
        self.assertIn("live_account_credentials_present", payload["blocking_reasons"])
        self.assertEqual(payload["detail"]["network_calls_executed"], 0)
        self.assertNotIn("paper-key", encoded)
        self.assertNotIn("paper-secret", encoded)

    def test_observation_runs_bounded_readonly_checks(self) -> None:
        checked_at = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=self._root() / ".tmp-tests") as tmp:
            settings = self._settings(Path(tmp))
            paper_client = FakeReadOnlyClient(FakeSnapshot(position_row_count=2))
            live_client = FakeReadOnlyClient(FakeSnapshot(position_row_count=0))
            factory_calls: list[str] = []

            def readonly_factory(_settings, *, mode: str, timeout_seconds: int):
                factory_calls.append(mode)
                return paper_client if mode == "paper" else live_client

            token = KisAccessToken(
                access_token="secret-token",
                token_type="Bearer",
                expires_at=checked_at + timedelta(hours=1),
            )
            manager = FakeTokenManager(token)
            clock_times: list[datetime] = []

            def clock_time_factory() -> datetime:
                self.assertEqual(paper_client.account_calls, 1)
                self.assertEqual(live_client.account_calls, 1)
                clock_times.append(checked_at)
                return checked_at

            payload = run_phase1b_readonly_observation(
                settings,
                checked_at=checked_at,
                readonly_client_factory=readonly_factory,
                profile_factory=lambda *_args: object(),
                token_manager_factory=lambda _profile: manager,
                clock_time_factory=clock_time_factory,
            )

        encoded = json.dumps(payload)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(factory_calls, ["live", "paper", "live"])
        self.assertEqual(manager.calls, [True])
        self.assertEqual(paper_client.account_calls, 1)
        self.assertEqual(live_client.account_calls, 1)
        self.assertEqual(paper_client.account_max_pages, [1])
        self.assertEqual(live_client.account_max_pages, [1])
        self.assertEqual(live_client.quote_calls, 1)
        self.assertEqual(clock_times, [checked_at])
        self.assertEqual(payload["safety"]["account_snapshot_max_pages_per_mode"], 1)
        self.assertEqual(payload["safety"]["order_method_calls"], 0)
        self.assertTrue(all(payload["checks"].values()))
        self.assertNotIn("secret-token", encoded)
        self.assertNotIn("live-secret", encoded)

    def test_token_failure_stops_before_account_and_quote_network_calls(self) -> None:
        checked_at = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=self._root() / ".tmp-tests") as tmp:
            settings = self._settings(Path(tmp))
            client = FakeReadOnlyClient()
            factory_calls: list[str] = []

            def readonly_factory(_settings, *, mode: str, timeout_seconds: int):
                factory_calls.append(mode)
                return client

            manager = FakeTokenManager(raises=RuntimeError("secret failure body"))
            payload = run_phase1b_readonly_observation(
                settings,
                checked_at=checked_at,
                readonly_client_factory=readonly_factory,
                profile_factory=lambda *_args: object(),
                token_manager_factory=lambda _profile: manager,
            )

        encoded = json.dumps(payload)
        self.assertFalse(payload["passed"])
        self.assertEqual(factory_calls, ["live"])
        self.assertEqual(client.account_calls, 0)
        self.assertEqual(client.quote_calls, 0)
        self.assertEqual(payload["artifacts"]["token_refresh_live"]["details"]["error_category"], "client_error")
        self.assertNotIn("secret failure body", encoded)

    def test_token_client_creation_failure_is_sanitized_and_fail_closed(self) -> None:
        checked_at = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=self._root() / ".tmp-tests") as tmp:
            settings = self._settings(Path(tmp))
            client = FakeReadOnlyClient()
            factory_calls: list[str] = []

            def readonly_factory(_settings, *, mode: str, timeout_seconds: int):
                factory_calls.append(mode)
                return client

            payload = run_phase1b_readonly_observation(
                settings,
                checked_at=checked_at,
                readonly_client_factory=readonly_factory,
                profile_factory=lambda *_args: (_ for _ in ()).throw(
                    RuntimeError("credential detail must not leak")
                ),
            )

        encoded = json.dumps(payload)
        self.assertFalse(payload["passed"])
        self.assertTrue(payload["execution_started"])
        self.assertEqual(factory_calls, ["live"])
        self.assertEqual(client.account_calls, 0)
        self.assertEqual(client.quote_calls, 0)
        self.assertEqual(
            payload["artifacts"]["token_refresh_live"]["details"]["error_type"],
            "RuntimeError",
        )
        self.assertNotIn("credential detail must not leak", encoded)

    def test_observation_does_not_start_when_preflight_is_blocked(self) -> None:
        checked_at = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=self._root() / ".tmp-tests") as tmp:
            settings = self._settings(Path(tmp), live_credentials=False)
            client = FakeReadOnlyClient()
            profile_calls = 0

            def profile_factory(*_args):
                nonlocal profile_calls
                profile_calls += 1
                return object()

            payload = run_phase1b_readonly_observation(
                settings,
                checked_at=checked_at,
                readonly_client_factory=lambda *_args, **_kwargs: client,
                profile_factory=profile_factory,
            )

        self.assertFalse(payload["passed"])
        self.assertFalse(payload["execution_started"])
        self.assertEqual(payload["checks"], {})
        self.assertEqual(payload["artifacts"], {})
        self.assertEqual(profile_calls, 0)
        self.assertEqual(client.account_calls, 0)
        self.assertEqual(client.quote_calls, 0)
        self.assertEqual(
            payload["blocking_reasons"],
            [
                "live_quote_credentials_present",
                "live_account_credentials_present",
                "phase1b_preflight_blocked",
            ],
        )

    def test_execute_blocks_protected_session_before_network_calls(self) -> None:
        checked_at = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=self._root() / ".tmp-tests") as tmp:
            settings = self._settings(Path(tmp))
            client = FakeReadOnlyClient()
            profile_calls = 0

            def profile_factory(*_args):
                nonlocal profile_calls
                profile_calls += 1
                return object()

            payload = run_phase1b_readonly_observation(
                settings,
                checked_at=checked_at,
                session_status="regular-session",
                readonly_client_factory=lambda *_args, **_kwargs: client,
                profile_factory=profile_factory,
            )

        self.assertFalse(payload["passed"])
        self.assertFalse(payload["execution_started"])
        self.assertEqual(payload["blocking_reasons"], ["protected_market_session"])
        self.assertEqual(
            payload["preflight"]["detail"]["market_session_status"],
            "regular-session",
        )
        self.assertEqual(profile_calls, 0)
        self.assertEqual(client.account_calls, 0)
        self.assertEqual(client.quote_calls, 0)

    def test_service_source_has_no_order_submission_calls(self) -> None:
        source = (
            self._root() / "app" / "services" / "phase1b_readonly_observation.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn(".submit_cash_order(", source)
        self.assertNotIn(".cancel_order(", source)

    def test_cli_default_is_network_free_preflight(self) -> None:
        root = self._root()
        temp_root = root / ".tmp-tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="phase1b-cli-", dir=temp_root) as tmp:
            result = subprocess.run(
                [
                    "bash",
                    "scripts/run_phase1b_readonly_observation.sh",
                    "--output-dir",
                    tmp,
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            report = json.loads(
                (Path(tmp) / "latest-phase1b-readonly-preflight.json").read_text(encoding="utf-8")
            )

        self.assertEqual(payload["execution_mode"], "network-free-preflight")
        self.assertEqual(payload["network_calls_executed"], 0)
        self.assertEqual(report["report_path"], payload["report_path"])


if __name__ == "__main__":
    unittest.main()
