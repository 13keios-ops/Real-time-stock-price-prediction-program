import json
import subprocess
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.market_status_probe import (
    build_market_status_check,
    compute_symbol_set_hash,
    market_status_snapshot_from_payload,
)


class MarketStatusProbeTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _work_dir(self) -> Path:
        return self._root() / ".tmp-tests" / "market-status-probe" / str(uuid.uuid4())

    def _snapshot_payload(self, *, tradable: bool = True) -> dict:
        now = datetime(2026, 5, 21, 9, 5, tzinfo=timezone.utc)
        return {
            "snapshot_id": "market-status-test-1",
            "trading_day": "2026-05-21",
            "created_at": now.isoformat(),
            "source": "manual_operator_snapshot",
            "symbol_set_hash": compute_symbol_set_hash(["005930", "000660"]),
            "stale_after": (now + timedelta(days=2)).isoformat(),
            "status_json": {
                "market_session": "regular",
                "source_generated_at": now.isoformat(),
                "symbols": {
                    "005930": {"tradable": tradable},
                    "000660": {"tradable": True},
                },
            },
        }

    def test_build_market_status_check_passes_for_tradable_symbols(self) -> None:
        snapshot = market_status_snapshot_from_payload(self._snapshot_payload())

        payload = build_market_status_check(
            snapshot,
            symbols=["005930", "000660"],
            checked_at=datetime(2026, 5, 21, 9, 6, tzinfo=timezone.utc),
        )

        self.assertTrue(payload["passed"])
        self.assertEqual(payload["key"], "market_status")
        self.assertEqual(payload["details"]["allowed_count"], 2)
        self.assertEqual(payload["details"]["blocked_symbols"], {})

    def test_build_market_status_check_blocks_flagged_symbol(self) -> None:
        snapshot = market_status_snapshot_from_payload(self._snapshot_payload(tradable=False))

        payload = build_market_status_check(
            snapshot,
            symbols=["005930", "000660"],
            checked_at=datetime(2026, 5, 21, 9, 6, tzinfo=timezone.utc),
        )

        self.assertFalse(payload["passed"])
        self.assertIn("not_tradable", payload["details"]["blocked_symbols"]["005930"])

    def test_snapshot_requires_timezone(self) -> None:
        payload = self._snapshot_payload()
        payload["created_at"] = "2026-05-21T09:05:00"

        with self.assertRaises(ValueError):
            market_status_snapshot_from_payload(payload)

    def test_snapshot_rejects_unknown_source(self) -> None:
        payload = self._snapshot_payload()
        payload["source"] = "free_form_source"

        with self.assertRaisesRegex(ValueError, "source must be one of"):
            market_status_snapshot_from_payload(payload)

    def test_snapshot_rejects_symbol_set_hash_mismatch(self) -> None:
        payload = self._snapshot_payload()
        payload["symbol_set_hash"] = "symbols-sha256-wrong"

        with self.assertRaisesRegex(ValueError, "symbol_set_hash must match"):
            market_status_snapshot_from_payload(payload)

    def test_compute_symbol_set_hash_is_order_independent(self) -> None:
        self.assertEqual(
            compute_symbol_set_hash(["005930", "000660", "005930"]),
            compute_symbol_set_hash(["000660", "005930"]),
        )

    def test_script_generates_check_from_snapshot_file(self) -> None:
        root = self._root()
        work_dir = self._work_dir()
        work_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = work_dir / "snapshot.json"
        output_path = work_dir / "check.json"
        snapshot_path.write_text(
            json.dumps(self._snapshot_payload(), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                "bash",
                "scripts/probe_market_status_snapshot.sh",
                "--snapshot-path",
                str(snapshot_path),
                "--output-path",
                str(output_path),
                "--symbols",
                "005930,000660",
                "--checked-at",
                "2026-05-21T09:06:00+00:00",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["probe_context"]["access"], "local-file")
        self.assertTrue(output_path.exists())

    def test_script_can_print_symbol_set_hash_without_valid_existing_hash(self) -> None:
        root = self._root()
        work_dir = self._work_dir()
        work_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = work_dir / "snapshot.json"
        payload = self._snapshot_payload()
        payload["symbol_set_hash"] = "placeholder"
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

        result = subprocess.run(
            [
                "bash",
                "scripts/probe_market_status_snapshot.sh",
                "--snapshot-path",
                str(snapshot_path),
                "--print-symbol-set-hash",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), compute_symbol_set_hash(["005930", "000660"]))


if __name__ == "__main__":
    unittest.main()
