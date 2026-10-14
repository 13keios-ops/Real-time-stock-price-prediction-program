from datetime import datetime, timedelta
import unittest

from app.services import candidate_pipeline as pipeline
from app.storage.contracts import MarketTickEvent


class CandidateSupplyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat('2026-10-14T10:00:10+09:00')
        self.minutes = []
        for i in range(21):
            stamp = self.now.replace(second=0) - timedelta(minutes=21-i)
            self.minutes.append({'sealed': True, 'available_at': stamp+timedelta(minutes=1),
                'ticks': [MarketTickEvent('001440', stamp+timedelta(seconds=5), 25000, 2, 'kis-ws'),
                          MarketTickEvent('001440', stamp+timedelta(seconds=45), 25100, 3, 'kis-ws')]})

    def build(self, **kwargs):
        self.assertTrue(hasattr(pipeline, 'build_candidate_bars'), 'WS supply bridge missing')
        return pipeline.build_candidate_bars('001440', self.minutes, as_of=self.now, **kwargs)

    def test_real_ws_records_build_closed_bars(self):
        bars = self.build()
        self.assertEqual(len(bars), 21)
        self.assertEqual(bars[-1]['volume'], 5)
        self.assertEqual(bars[-1]['trade_count'], 2)
        self.assertEqual(bars[-1]['trade_count_scope'], 'captured_ws_records_only')
        self.assertEqual((bars[-1]['open'], bars[-1]['close']), (25000, 25100))

    def test_rest_accumulated_volume_cannot_be_trade_input(self):
        self.minutes[-1]['ticks'][0].source = 'kis-rest'
        with self.assertRaises(ValueError): self.build()

    def test_wrong_symbol_and_cross_minute_tick_are_rejected(self):
        self.minutes[-1]['ticks'][0].symbol = '006800'
        with self.assertRaises(ValueError): self.build()
        self.minutes[-1]['ticks'][0].symbol = '001440'
        self.minutes[-1]['ticks'][0].event_time -= timedelta(minutes=1)
        with self.assertRaises(ValueError): self.build()

    def test_unsealed_or_early_available_minute_is_rejected(self):
        self.minutes[-1]['sealed'] = False
        with self.assertRaises(ValueError): self.build()
        self.minutes[-1]['sealed'] = True
        self.minutes[-1]['available_at'] -= timedelta(seconds=1)
        with self.assertRaises(ValueError): self.build()

    def test_missing_minute_stale_holiday_and_future_receipt_are_rejected(self):
        with self.assertRaises(ValueError): self.build(holidays=('2026-10-14',))
        self.minutes[-1]['available_at'] = self.now+timedelta(seconds=1)
        with self.assertRaises(ValueError): self.build()
        self.minutes.pop()
        with self.assertRaises(ValueError): self.build()

    def test_invalid_price_volume_and_naive_time_are_rejected(self):
        for key, value in [('price', float('nan')), ('volume', -1), ('event_time', datetime(2026,10,14,9,59))]:
            tick = self.minutes[-1]['ticks'][0]
            previous = getattr(tick, key);setattr(tick, key, value)
            with self.assertRaises(ValueError): self.build()
            setattr(tick, key, previous)


class CandidateBudgetTests(unittest.TestCase):
    def plan(self, **kwargs):
        self.assertTrue(hasattr(pipeline, 'candidate_budget_preflight'), 'Whole-source budget preflight missing')
        return pipeline.candidate_budget_preflight(**kwargs)

    def test_upstream_requests_are_not_hidden_in_capture_budget(self):
        r = self.plan(symbol_count=5, market_count=2, sector_count=5)
        self.assertEqual(r['capture_requests'], 11)
        self.assertEqual(r['upstream_requests'], 17)
        self.assertEqual(r['total_requests'], 28)
        self.assertIn('whole_context_timeout_budget_exceeds_freshness', r['blocking_reasons'])
        self.assertIn('capture_timeout_budget_exceeds_deadline', r['blocking_reasons'])
        self.assertFalse(r['activation_allowed']);self.assertEqual(r['network_calls'], 0)

    def test_small_plan_still_requires_shared_coordinator_and_approval(self):
        r = self.plan(symbol_count=1, market_count=1, sector_count=1)
        self.assertEqual(r['total_requests'], 7)
        self.assertNotIn('capture_timeout_budget_exceeds_deadline', r['blocking_reasons'])
        self.assertIn('account_wide_coordinator_not_connected', r['blocking_reasons'])
        self.assertIn('standing_collection_not_authorized', r['blocking_reasons'])
        self.assertIn('dated_anchor_timeout_budget_exceeds_freshness', r['blocking_reasons'])
        self.assertFalse(r['activation_allowed'])

    def test_budget_counts_are_bounded_and_not_booleans(self):
        for counts in [(0,1,1),(6,1,1),(1,3,1),(1,1,2),(True,1,1)]:
            with self.assertRaises(ValueError):
                self.plan(symbol_count=counts[0], market_count=counts[1], sector_count=counts[2])

    def test_cli_prints_blocked_plan_without_settings_or_network(self):
        import importlib.util
        import io
        import json
        from contextlib import redirect_stdout
        self.assertIsNotNone(importlib.util.find_spec('scripts.preflight_candidate_collection'),
                             'No-network budget CLI missing')
        from scripts.preflight_candidate_collection import main
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--symbol-count','1','--market-count','1','--sector-count','1']),0)
        report = json.loads(output.getvalue())
        self.assertFalse(report['activation_allowed'])
        self.assertEqual(report['total_requests'],7)
        self.assertEqual(report['network_calls'],0)
