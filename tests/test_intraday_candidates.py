import unittest
from datetime import datetime, timedelta, timezone

from app.universe.intraday_candidates import scan_candidates


class IntradayCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 14, 10, 0, tzinfo=timezone(timedelta(hours=9)))
        self.row = dict(symbol="123456", market="KOSDAQ",
                        instrument_type="common_stock", market_status="normal",
                        price=25000, bid=24950, ask=25000,
                        trading_value=2_000_000_000, return_pct=3,
                        market_return_pct=1, sector_return_pct=2,
                        volume_ratio=2, observed_at=self.now.isoformat(),
                        quote_at=self.now.isoformat(), theme="fixture_theme",
                        bars=[dict(bar_time=(self.now-timedelta(minutes=21-i)).isoformat(),
                                   available_at=(self.now-timedelta(minutes=20-i)).isoformat(),
                                   open=24500, high=24700, low=24400, close=24600,
                                   volume=1000) for i in range(20)] +
                             [dict(bar_time=(self.now-timedelta(minutes=1)).isoformat(),
                                   available_at=self.now.isoformat(), open=24800,
                                   high=25100, low=24700, close=25000, volume=2000)])

    def scan(self, rows=None):
        return scan_candidates(rows or [self.row], as_of=self.now)

    def test_breakout_is_signal_not_order(self):
        report = self.scan()
        self.assertEqual(report["selected"][0]["signals"], ["breakout"])
        self.assertFalse(report["execution_enabled"])
        self.assertEqual(report["network_calls"], 0)

    def test_price_band(self):
        self.row["price"] = 31000
        self.assertIn("price_band", self.scan()["rejected"][0]["reasons"])

    def test_unknown_market_status_is_not_safe(self):
        self.row.pop("market_status")
        self.assertIn("market_status_unverified", self.scan()["rejected"][0]["reasons"])

    def test_warning_excluded(self):
        self.row["market_status"] = "investment_warning"
        self.assertEqual(len(self.scan()["selected"]), 0)

    def test_stale_and_future_quotes(self):
        for delta in (-21, 1):
            self.row["quote_at"] = (self.now+timedelta(seconds=delta)).isoformat()
            self.assertIn("quote_stale_or_future", self.scan()["rejected"][0]["reasons"])

    def test_duplicate_symbol_blocks_batch(self):
        with self.assertRaises(ValueError):
            self.scan([self.row, dict(self.row)])

    def test_nan_rejected(self):
        self.row["price"] = float("nan")
        self.assertEqual(len(self.scan()["selected"]), 0)

    def test_no_future_bar(self):
        self.row["bars"][-1]["available_at"] = (self.now+timedelta(seconds=1)).isoformat()
        self.assertIn("bar_evidence_invalid", self.scan()["rejected"][0]["reasons"])

    def test_rank_deterministic(self):
        other = dict(self.row, symbol="654321", return_pct=4)
        self.assertEqual(self.scan([self.row, other])["selected"],
                         self.scan([other, self.row])["selected"])
        self.assertEqual(self.scan([self.row, other])["selected"][0]["symbol"], "654321")

    def test_gap_blocks_signal(self):
        self.row["bars"][0]["bar_time"] = (self.now-timedelta(minutes=22)).isoformat()
        self.assertIn("bar_evidence_invalid", self.scan()["rejected"][0]["reasons"])

    def test_secrets_not_echoed(self):
        self.row["app_secret"] = "should_not_appear"
        self.assertNotIn("should_not_appear", str(self.scan()))

    def test_relative_strength_required(self):
        self.row["sector_return_pct"] = 5
        self.assertIn("relative_strength", self.scan()["rejected"][0]["reasons"])

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            scan_candidates([self.row], as_of=self.now.replace(tzinfo=None))
