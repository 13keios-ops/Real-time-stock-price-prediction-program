import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests import test_intraday_candidates as fixtures
from app.universe.intraday_candidates import ScanPolicy, scan_candidates


class ScannerEdgeTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.IntradayCandidatesTests()
        fixture.setUp()
        self.now, self.row = fixture.now, fixture.row

    def test_pullback_not_breakout(self):
        bars = self.row["bars"]
        bars[-3].update(open=25200, high=25500, low=25100, close=25400)
        bars[-2].update(open=25300, high=25400, low=24700, close=24800)
        bars[-1].update(open=24800, high=25100, low=24700, close=25000)
        signals = scan_candidates([self.row], as_of=self.now)["selected"][0]["signals"]
        self.assertEqual(signals, ["trend_pullback"])

    def test_wide_spread(self):
        self.row["bid"] = 24000
        self.assertIn("wide_spread", scan_candidates([self.row], as_of=self.now)["rejected"][0]["reasons"])

    def test_missing_benchmark(self):
        self.row.pop("market_return_pct")
        self.assertEqual(scan_candidates([self.row], as_of=self.now)["selected"], [])

    def test_shortlist_cap_and_no_signal(self):
        self.row["bars"][-1].update(open=24500, high=24700, low=24400, close=24600, volume=1000)
        rows = [dict(self.row, symbol=f"{i:06d}") for i in range(6)]
        report = scan_candidates(rows, as_of=self.now)
        self.assertEqual(len(report["selected"]), 5)
        self.assertEqual(report["selected"][0]["signals"], [])
        self.assertEqual(report["rejected"][0]["reasons"], ["shortlist_limit"])

    def test_invalid_policy(self):
        for kwargs in (dict(min_price=40000), dict(max_candidates=1.5), dict(min_volume_ratio=True)):
            with self.assertRaises(ValueError):
                ScanPolicy(**kwargs)

    def test_cli_emits_only_sanitized_result(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root / ".tmp-tests") as folder:
            snapshot = Path(folder) / "snapshot.json"
            self.row["token"] = "SECRET_FIXTURE"
            snapshot.write_text(json.dumps([self.row]), encoding="utf-8")
            result = subprocess.run([sys.executable, str(root / "scripts/scan_intraday_candidates.py"),
                                     "--snapshot", str(snapshot), "--as-of", self.now.isoformat()],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("SECRET_FIXTURE", result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)["execution_enabled"])

    def test_cli_invalid_does_not_echo_input(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root / ".tmp-tests") as folder:
            snapshot = Path(folder) / "snapshot.json"
            snapshot.write_text("SECRET_FIXTURE", encoding="utf-8")
            result = subprocess.run([sys.executable, str(root / "scripts/scan_intraday_candidates.py"),
                                     "--snapshot", str(snapshot), "--as-of", self.now.isoformat()],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("SECRET_FIXTURE", result.stdout + result.stderr)
