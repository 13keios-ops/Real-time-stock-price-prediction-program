import copy
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from app.collectors.candidate_capture_cycle import CaptureCycle
from tests import test_kis_candidate_snapshot as fixtures


class Clock:
    def __init__(self, now):
        self.value = now
        self.delays = []

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.delays.append(seconds)
        self.value += timedelta(seconds=seconds)


class FakeReader:
    def __init__(self, clock, capture):
        self.clock, self.capture, self.calls = clock, capture, []
        self.failure = None

    def get(self, path, tr_id, params, *, timeout_seconds, allow_retry):
        self.calls.append(dict(path=path, tr_id=tr_id, params=params, allow_retry=allow_retry))
        if self.failure:
            return dict(rt_cd="1", msg_cd=self.failure, appsecret="SECRET_FIXTURE")
        envelope = dict(rt_cd="0", trade_date=self.clock.now().date().isoformat())
        if path.endswith("volume-rank"):
            envelope["output"] = self.capture["rows"]
        else:
            symbol = params["FID_INPUT_ISCD"]
            obs = self.capture["observations"][symbol]
            if path.endswith("inquire-price"):
                envelope["output"] = obs["price"]["output"]
            else:
                envelope["output1"] = obs["orderbook"]["output1"]
                envelope["provider_at"] = self.clock.now().isoformat()
        return envelope


class CaptureCycleTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.KisCandidateSnapshotTests()
        fixture.setUp()
        self.capture = fixture.snapshot
        for row in self.capture["rows"]:
            row.update(stck_prpr="25000", prdy_ctrt="3", acml_tr_pbmn="2000000000")
        for b in self.capture["observations"]["123456"]["bars"]:
            b["trade_count"] = 50
        self.clock = Clock(fixture.now)
        self.reader = FakeReader(self.clock, self.capture)
        self.cycle = CaptureCycle(self.reader, clock=self.clock.now, sleep=self.clock.sleep)

    def collect(self, **kwargs):
        return self.cycle.collect(evidence=self.capture["observations"], **kwargs)

    def test_default_dry_run_no_requests(self):
        self.assertEqual(self.collect()["status"], "dry_run")
        self.assertEqual(self.reader.calls, [])

    def test_execute_without_explicit_budget_authorization_blocked(self):
        self.assertEqual(self.collect(execute=True)["status"], "network_authorization_required")
        self.assertEqual(self.reader.calls, [])

    def test_complete_cycle_and_pacing(self):
        report = self.collect(execute=True, budget_authorized=True)
        self.assertEqual(report["status"], "captured")
        self.assertEqual(len(self.reader.calls), 3)
        self.assertEqual(self.clock.delays, [1.1, 1.1])
        self.assertTrue(all(c["allow_retry"] is False for c in self.reader.calls))
        self.assertEqual(len(report["scan"]["scanner"]["selected"]), 1)

    def test_rate_limit_stops_without_retry(self):
        self.reader.failure = "EGW00201"
        result = self.collect(execute=True, budget_authorized=True)
        self.assertEqual(result["status"], "failed_no_retry")
        self.assertEqual(result["failure_taxonomy"], "broker_rate_limited")
        self.assertEqual(len(self.reader.calls), 1)
        self.assertNotIn("SECRET_FIXTURE", str(result))

    def test_missing_context_blocks_price_calls(self):
        self.capture["observations"]["123456"].pop("benchmark")
        result = self.collect(execute=True, budget_authorized=True)
        self.assertEqual(len(self.reader.calls), 1)
        self.assertEqual(result["status"], "blocked_missing_evidence")

    def test_warning_is_not_assumed_normal(self):
        self.capture["observations"]["123456"]["metadata"]["flags"]["investment_warning"] = True
        result = self.collect(execute=True, budget_authorized=True)
        self.assertEqual(len(self.reader.calls), 1)
        self.assertEqual(result["scan"]["scanner"]["selected"], [])

    def test_new_price_warning_stops_before_book_call(self):
        self.capture['observations']['123456']['price']['output']['mrkt_warn_cls_code']='02'
        r=self.collect(execute=True,budget_authorized=True)
        self.assertEqual(r['status'],'failed_no_retry')
        self.assertEqual(len(self.reader.calls),2)

    def test_missing_source_chain_stops_price_call(self):
        self.capture['observations']['123456']['metadata'].pop('source_version')
        r=self.collect(execute=True,budget_authorized=True)
        self.assertEqual(r['status'],'blocked_missing_evidence')
        self.assertEqual(len(self.reader.calls),1)

    def test_cooldown_after_failure(self):
        self.reader.failure = "EGW00201"
        self.collect(execute=True, budget_authorized=True)
        self.assertEqual(self.collect(execute=True, budget_authorized=True)["status"], "cycle_cooldown")
        self.assertEqual(len(self.reader.calls), 1)

    def test_off_session_no_calls(self):
        self.clock.value = self.clock.value.replace(hour=8)
        self.assertEqual(self.collect(execute=True, budget_authorized=True)["status"], "outside_entry_window")
        self.assertEqual(self.reader.calls, [])

    def test_unknown_provider_date_does_not_use_receipt_date(self):
        original = self.reader.get
        def get(*args, **kwargs):
            result = original(*args, **kwargs)
            result.pop("trade_date", None)
            return result
        self.reader.get = get
        result = self.collect(execute=True, budget_authorized=True)
        self.assertEqual(result["status"], "failed_no_retry")
        self.assertEqual(len(self.reader.calls), 1)

    def test_missing_trade_count_is_not_fabricated(self):
        self.capture["observations"]["123456"]["bars"][-1].pop("trade_count")
        result = self.collect(execute=True, budget_authorized=True)
        self.assertEqual(result["status"], "blocked_missing_evidence")
        self.assertEqual(len(self.reader.calls), 1)

    def test_duplicate_ranking_blocks_whole_cycle(self):
        self.capture["rows"].append(copy.deepcopy(self.capture["rows"][0]))
        result = self.collect(execute=True, budget_authorized=True)
        self.assertEqual(result["status"], "failed_no_retry")
        self.assertEqual(len(self.reader.calls), 1)

    def test_secrets_not_in_sanitized_capture(self):
        self.capture["rows"][0]["appsecret"] = "SECRET_FIXTURE"
        self.capture["observations"]["123456"]["price"]["output"]["token"] = "SECRET_FIXTURE"
        self.assertNotIn("SECRET_FIXTURE", str(self.collect(execute=True, budget_authorized=True)))

    def test_at_most_five_symbols(self):
        row = self.capture["rows"][0]
        context = self.capture["observations"]["123456"]
        self.capture["rows"] = [dict(row, mksc_shrn_iscd=f"{i:06d}") for i in range(6)]
        self.capture["observations"] = {r["mksc_shrn_iscd"]: copy.deepcopy(context) for r in self.capture["rows"]}
        report = self.collect(execute=True, budget_authorized=True)
        self.assertEqual(report["request_attempts"], 11)
        self.assertEqual(len(report["capture"]["observations"]), 5)

    def test_weak_rank_does_not_consume_quote_budget(self):
        other = dict(self.capture["rows"][0], mksc_shrn_iscd="654321")
        self.capture["observations"]["654321"] = copy.deepcopy(self.capture["observations"]["123456"])
        self.capture["rows"][0]["prdy_ctrt"] = "-3"
        self.capture["rows"].append(other)
        report = self.collect(execute=True, budget_authorized=True)
        self.assertEqual(list(report["capture"]["observations"]), ["654321"])
        self.assertEqual(len(self.reader.calls), 3)

    def test_slow_response_stops_cycle(self):
        original = self.reader.get
        def slow(*args, **kwargs):
            self.clock.value += timedelta(seconds=19)
            return original(*args, **kwargs)
        self.reader.get = slow
        report = self.collect(execute=True, budget_authorized=True)
        self.assertEqual(report["status"], "failed_no_retry")
        self.assertEqual(report["failure_taxonomy"], "capture_deadline_exceeded")
        self.assertEqual(len(self.reader.calls), 1)

    def test_last_response_also_respects_deadline(self):
        original = self.reader.get
        def slow_last(*args, **kwargs):
            if len(self.reader.calls) == 2:
                self.clock.value += timedelta(seconds=19)
            return original(*args, **kwargs)
        self.reader.get = slow_last
        report = self.collect(execute=True, budget_authorized=True)
        self.assertEqual(report["status"], "failed_no_retry")
        self.assertEqual(report["failure_taxonomy"], "capture_deadline_exceeded")

    def test_captured_cycle_drives_separate_wallets(self):
        from datetime import datetime
        from app.paper_trading.candidate_comparison import CandidateComparison
        from app.paper_trading.daily_mission import MissionContract
        from app.storage.contracts import MinuteBar
        root = Path(__file__).resolve().parents[1] / ".tmp-tests"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            comparison = CandidateComparison(Path(folder)/"comparison", MissionContract(symbols=("123456",)))
            try:
                def bar(record):
                    return MinuteBar(symbol="123456", bar_time=datetime.fromisoformat(record["bar_time"]),
                                     **{k: record[k] for k in ("open","high","low","close","volume","trade_count")})
                rows = self.capture["observations"]["123456"]["bars"]
                for record in rows[:-1]:
                    observation = bar(record)
                    comparison.observe(observation, observed_at=observation.bar_time+timedelta(minutes=1),
                                       quote_spread_bps=20)
                captured = self.collect(execute=True, budget_authorized=True)
                comparison.observe(bar(rows[-1]), observed_at=self.clock.now(), capture=captured["capture"])
                self.assertIsNotNone(comparison.wallets["breakout"].state["pending"])
                self.assertIsNone(comparison.wallets["trend_pullback"].state["pending"])
                self.assertEqual([w.state["cash"] for w in comparison.wallets.values()], [300000, 300000])
            finally:
                comparison.close()
