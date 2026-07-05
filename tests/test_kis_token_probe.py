import json
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.brokers.kis_auth import KisAccessToken
from app.services.kis_probe_errors import build_sanitized_kis_probe_error
from app.services.kis_token_probe import probe_kis_token_refresh_check


class FakeTokenManager:
    def __init__(self, token: KisAccessToken | None = None, raises: Exception | None = None) -> None:
        self.token = token
        self.raises = raises
        self.force_refresh_calls: list[bool] = []

    def get_access_token(self, *, force_refresh: bool = False) -> KisAccessToken:
        self.force_refresh_calls.append(force_refresh)
        if self.raises is not None:
            raise self.raises
        assert self.token is not None
        return self.token


class KisTokenProbeTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_probe_builds_sanitized_token_refresh_check(self) -> None:
        checked_at = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)
        token = KisAccessToken(
            access_token="secret-token",
            token_type="Bearer",
            expires_at=checked_at + timedelta(hours=1),
        )
        manager = FakeTokenManager(token)

        check = probe_kis_token_refresh_check(manager, mode="paper", checked_at=checked_at)

        encoded = json.dumps(check, ensure_ascii=False)
        self.assertEqual(manager.force_refresh_calls, [True])
        self.assertEqual(check["key"], "token_refresh")
        self.assertEqual(check["status"], "ok")
        self.assertTrue(check["passed"])
        self.assertEqual(check["details"]["mode"], "paper")
        self.assertEqual(check["details"]["seconds_to_expiry"], 3600.0)
        self.assertNotIn("secret-token", encoded)

    def test_probe_failure_is_sanitized(self) -> None:
        manager = FakeTokenManager(raises=RuntimeError("secret body should not leak"))

        check = probe_kis_token_refresh_check(manager, mode="paper")

        encoded = json.dumps(check, ensure_ascii=False)
        self.assertEqual(check["status"], "failed")
        self.assertFalse(check["passed"])
        self.assertEqual(check["details"]["error_type"], "RuntimeError")
        self.assertEqual(check["details"]["error_category"], "client_error")
        self.assertNotIn("secret body", encoded)

    def test_probe_failure_classifies_rate_limit_without_raw_body(self) -> None:
        manager = FakeTokenManager(raises=RuntimeError('KIS HTTP error 429: {"message":"EGW00201 secret"}'))

        check = probe_kis_token_refresh_check(manager, mode="paper")

        encoded = json.dumps(check, ensure_ascii=False)
        self.assertEqual(check["details"]["error_category"], "rate_limited")
        self.assertEqual(check["details"]["http_status"], 429)
        self.assertEqual(check["details"]["kis_error_codes"], ["EGW00201"])
        self.assertNotIn("secret", encoded)

    def test_error_classifier_detects_missing_credentials(self) -> None:
        details = build_sanitized_kis_probe_error(
            RuntimeError("KIS app key and secret are required before requesting a token.")
        )

        self.assertEqual(details["error_category"], "missing_quote_credentials")

    def test_cli_wrapper_help_does_not_call_network(self) -> None:
        result = subprocess.run(
            ["bash", "scripts/probe_kis_token_refresh.sh", "--help"],
            cwd=self._root(),
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("--mode", result.stdout)
        self.assertIn("--output-path", result.stdout)


if __name__ == "__main__":
    unittest.main()
