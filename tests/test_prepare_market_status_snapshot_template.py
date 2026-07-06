import json
import subprocess
import unittest
import uuid
from pathlib import Path

from app.services.market_status_probe import compute_symbol_set_hash


class PrepareMarketStatusSnapshotTemplateTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _work_dir(self) -> Path:
        return self._root() / ".tmp-tests" / "market-status-template" / str(uuid.uuid4())

    def test_template_is_fail_closed_and_probe_blocks(self) -> None:
        root = self._root()
        work_dir = self._work_dir()
        watchlist = work_dir / "watchlist.txt"
        snapshot = work_dir / "market-status-snapshot.json"
        check = work_dir / "market-status-check.json"
        watchlist.parent.mkdir(parents=True, exist_ok=True)
        watchlist.write_text("005930\n000660\n", encoding="utf-8")

        result = subprocess.run(
            [
                "bash",
                "scripts/prepare_market_status_snapshot_template.sh",
                "--watchlist-file",
                str(watchlist),
                "--output-path",
                str(snapshot),
                "--trading-day",
                "2026-07-07",
                "--stale-after",
                "2026-07-07T08:45:00+09:00",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)

        self.assertEqual(payload["source"], "manual_operator_snapshot")
        self.assertEqual(payload["symbol_set_hash"], compute_symbol_set_hash(["005930", "000660"]))
        self.assertTrue(payload["status_json"]["template_fail_closed"])
        self.assertIsNone(payload["status_json"]["symbols"]["005930"]["tradable"])
        self.assertFalse(payload["status_json"]["symbols"]["005930"]["operator_checked"])

        probe = subprocess.run(
            [
                "bash",
                "scripts/probe_market_status_snapshot.sh",
                "--snapshot-path",
                str(snapshot),
                "--output-path",
                str(check),
                "--symbols-file",
                str(watchlist),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        check_payload = json.loads(probe.stdout)

        self.assertEqual(check_payload["status"], "failed")
        self.assertFalse(check_payload["passed"])
        self.assertEqual(check_payload["details"]["symbol_count"], 2)
        self.assertEqual(check_payload["details"]["allowed_count"], 0)
        self.assertIn("tradable_unknown", check_payload["details"]["blocked_symbols"]["005930"])


if __name__ == "__main__":
    unittest.main()