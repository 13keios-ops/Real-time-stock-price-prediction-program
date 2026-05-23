import json
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.services.system_clock_probe import build_system_clock_reference_comparison, probe_kis_system_clock_check


class FakeReadOnlyClient:
    def __init__(self, headers: dict[str, str], *, raises: Exception | None = None) -> None:
        self._headers = headers
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    @property
    def last_response_headers(self) -> dict[str, str]:
        return dict(self._headers)

    def get_current_price(self, *, symbol: str, market_code: str = "J") -> object:
        self.calls.append((symbol, market_code))
        if self._raises is not None:
            raise self._raises
        return object()


class KisClockReferenceProbeTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_probe_builds_sanitized_system_clock_check_from_readonly_quote_header(self) -> None:
        client = FakeReadOnlyClient({"date": "Wed, 20 May 2026 00:00:00 GMT"})

        check = probe_kis_system_clock_check(
            client,
            symbol="005930",
            market_code="J",
            local_time=datetime(2026, 5, 20, 0, 0, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(client.calls, [("005930", "J")])
        self.assertEqual(check["key"], "system_clock")
        self.assertEqual(check["status"], "ok")
        self.assertTrue(check["passed"])
        self.assertEqual(check["details"]["source"], "kis_rest_http_date")
        self.assertEqual(check["details"]["skew_seconds"], 1.0)
        self.assertEqual(check["details"]["reference_precision_seconds"], 1.0)
        self.assertEqual(check["details"]["probe"], "kis_readonly_current_price")
        self.assertNotIn("Wed, 20 May 2026", json.dumps(check, ensure_ascii=False))

    def test_probe_marks_missing_date_header_not_verified(self) -> None:
        client = FakeReadOnlyClient({"tr_cont": ""})

        check = probe_kis_system_clock_check(
            client,
            local_time=datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(check["status"], "not_verified")
        self.assertFalse(check["passed"])
        self.assertEqual(check["details"]["probe"], "kis_readonly_current_price")

    def test_probe_rejects_invalid_date_header_without_exposing_raw_header(self) -> None:
        client = FakeReadOnlyClient({"date": "secret-invalid-date"})

        check = probe_kis_system_clock_check(
            client,
            local_time=datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc),
        )

        encoded = json.dumps(check, ensure_ascii=False)
        self.assertEqual(check["status"], "invalid_fixture")
        self.assertFalse(check["passed"])
        self.assertNotIn("secret-invalid-date", encoded)

    def test_probe_failure_is_sanitized(self) -> None:
        client = FakeReadOnlyClient({}, raises=RuntimeError("secret body should not leak"))

        check = probe_kis_system_clock_check(client)

        encoded = json.dumps(check, ensure_ascii=False)
        self.assertEqual(check["status"], "failed")
        self.assertFalse(check["passed"])
        self.assertEqual(check["details"]["error_type"], "RuntimeError")
        self.assertNotIn("secret body", encoded)

    def test_paper_live_reference_comparison_uses_sanitized_reference_times(self) -> None:
        paper_check = {
            "key": "system_clock",
            "status": "ok",
            "passed": True,
            "details": {
                "source": "kis_rest_http_date_paper",
                "reference_time": "2026-05-20T00:00:00+00:00",
                "reference_precision_seconds": 1.0,
            },
        }
        live_check = {
            "key": "system_clock",
            "status": "ok",
            "passed": True,
            "details": {
                "source": "kis_rest_http_date_live",
                "reference_time": "2026-05-20T00:00:00+00:00",
                "reference_precision_seconds": 1.0,
            },
        }

        comparison = build_system_clock_reference_comparison(paper_check, live_check)

        encoded = json.dumps(comparison, ensure_ascii=False)
        self.assertEqual(comparison["key"], "system_clock_reference_comparison")
        self.assertEqual(comparison["status"], "ok")
        self.assertTrue(comparison["passed"])
        self.assertEqual(comparison["details"]["reference_delta_seconds"], 0.0)
        self.assertNotIn("Wed, 20 May 2026", encoded)

    def test_paper_live_reference_comparison_blocks_large_delta(self) -> None:
        paper_check = {
            "key": "system_clock",
            "status": "ok",
            "passed": True,
            "details": {"reference_time": "2026-05-20T00:00:00+00:00"},
        }
        live_check = {
            "key": "system_clock",
            "status": "ok",
            "passed": True,
            "details": {"reference_time": "2026-05-20T00:00:03+00:00"},
        }

        comparison = build_system_clock_reference_comparison(paper_check, live_check)

        self.assertEqual(comparison["status"], "blocked")
        self.assertFalse(comparison["passed"])
        self.assertIn("paper_live_reference_delta_too_large", comparison["details"]["blocking_reasons"])

    def test_cli_wrapper_help_does_not_call_network(self) -> None:
        result = subprocess.run(
            ["bash", "scripts/probe_kis_clock_reference.sh", "--help"],
            cwd=self._root(),
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("--mode", result.stdout)
        self.assertIn("--compare-paper-live", result.stdout)
        self.assertIn("--output-path", result.stdout)


if __name__ == "__main__":
    unittest.main()
