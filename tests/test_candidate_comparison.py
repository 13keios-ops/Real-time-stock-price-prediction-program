from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from app.paper_trading.candidate_comparison import CandidateComparison
from app.paper_trading.daily_mission import DailyProfitMission, MissionContract
from app.storage.contracts import MinuteBar
from tests import test_kis_candidate_snapshot as fixtures


class CandidateComparisonTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.KisCandidateSnapshotTests()
        fixture.setUp()
        self.now, self.capture = fixture.now, fixture.snapshot
        root = Path(__file__).resolve().parents[1] / ".tmp-tests"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "comparison"
        self.contract = MissionContract(symbols=("123456", "654321"))
        self.comparison = CandidateComparison(self.folder, self.contract)
        self.addCleanup(self.comparison.close)

    def bar(self, row):
        return MinuteBar(symbol="123456", bar_time=datetime.fromisoformat(row["bar_time"]),
                         **{k: row[k] for k in ("open", "high", "low", "close", "volume")}, trade_count=50)

    def warmup(self):
        for row in self.capture["observations"]["123456"]["bars"][:-1]:
            bar = self.bar(row)
            self.comparison.observe(bar, observed_at=bar.bar_time+timedelta(minutes=1), quote_spread_bps=20)

    def trigger(self):
        self.warmup()
        row = self.capture["observations"]["123456"]["bars"][-1]
        bar = self.bar(row)
        self.comparison.observe(bar, observed_at=self.now, quote_spread_bps=20, capture=self.capture)
        return bar

    def test_two_wallets_not_shared_capital(self):
        report = self.comparison.report(as_of=self.now)
        self.assertEqual([r["cash_balance"] for r in report["wallets"].values()], [300000, 300000])
        self.assertEqual(report["order_calls"], 0)
        self.assertFalse(report["runtime_attached"])

    def test_breakout_only_wallet_pending(self):
        self.trigger()
        self.assertIsNotNone(self.comparison.wallets["breakout"].state["pending"])
        self.assertIsNone(self.comparison.wallets["trend_pullback"].state["pending"])

    def test_pullback_only_wallet_pending(self):
        bars = self.capture["observations"]["123456"]["bars"]
        bars[-3].update(open=25200, high=25500, low=25100, close=25400)
        bars[-2].update(open=25300, high=25400, low=24700, close=24800)
        self.trigger()
        self.assertIsNone(self.comparison.wallets["breakout"].state["pending"])
        self.assertIsNotNone(self.comparison.wallets["trend_pullback"].state["pending"])

    def test_future_fill_and_costs(self):
        bar = self.trigger()
        pending = self.comparison.wallets["breakout"].state["pending"]
        self.assertGreater(datetime.fromisoformat(pending["execute_at"]), self.now)
        future = MinuteBar(symbol="123456", bar_time=datetime.fromisoformat(pending["execute_at"]),
                           open=25000, high=25050, low=24950, close=25000, volume=1000, trade_count=50)
        self.comparison.observe(future, observed_at=future.bar_time+timedelta(minutes=1), quote_spread_bps=20)
        wallet = self.comparison.wallets["breakout"]
        self.assertEqual(wallet.state["fill_count"], 1)
        self.assertGreater(wallet.state["commission"], 0)
        self.assertEqual(self.comparison.wallets["trend_pullback"].state["cash"], 300000)

    def test_lineage_and_unique_strategy_ids(self):
        self.trigger()
        pending = self.comparison.wallets["breakout"].state["pending"]
        self.assertIn(":breakout:", pending["decision_id"])
        self.assertEqual(len(pending["candidate_id"]), 64)
        self.assertEqual(len(pending["capture_hash"]), 64)

    def test_capture_bar_mismatch_rejected_before_writing(self):
        self.warmup()
        bar = self.bar(self.capture["observations"]["123456"]["bars"][-1])
        bar.close = 24999
        with self.assertRaises(ValueError):
            self.comparison.observe(bar, observed_at=self.now, quote_spread_bps=20, capture=self.capture)
        self.assertIsNone(self.comparison.wallets["breakout"].state["pending"])

    def test_duplicate_no_extra_events(self):
        bar = self.trigger()
        counts = [w.state["source_bar_count"] for w in self.comparison.wallets.values()]
        self.comparison.observe(bar, observed_at=self.now, quote_spread_bps=20, capture=self.capture)
        self.assertEqual(counts, [w.state["source_bar_count"] for w in self.comparison.wallets.values()])

    def test_restart_and_contract_change_blocked(self):
        self.trigger()
        self.comparison.close()
        reopened = CandidateComparison(self.folder, self.contract)
        self.addCleanup(reopened.close)
        self.assertIsNotNone(reopened.wallets["breakout"].state["pending"])
        with self.assertRaises(ValueError):
            CandidateComparison(self.folder, MissionContract(symbols=("654321",)))

    def test_original_contract_hash_unchanged(self):
        known = MissionContract(symbols=("005930",))
        self.assertNotIn("strategy", known.to_dict())
        self.assertTrue(callable(getattr(DailyProfitMission, "_entry_reason", None)))

    def test_other_symbol_cannot_cancel_pending_entry(self):
        wallet = self.comparison.wallets["breakout"]
        wallet.context = dict(blocked=True, signals=[])
        state = dict(pending=dict(side="buy", symbol="654321", decision_id="other"))
        bar = self.bar(self.capture["observations"]["123456"]["bars"][-1])
        wallet._fill_pending(state, bar, None, [], 20)
        self.assertIsNotNone(state["pending"])

    def test_allocation_uses_top_signal_not_input_arrival(self):
        self.capture["rows"].append(dict(mksc_shrn_iscd="654321", acml_vol="2000", prdy_vol="1000"))
        import copy
        other = copy.deepcopy(self.capture["observations"]["123456"])
        other["price"]["output"]["prdy_ctrt"] = "4"
        self.capture["observations"]["654321"] = other
        self.trigger()
        self.assertIsNone(self.comparison.wallets["breakout"].state["pending"])
