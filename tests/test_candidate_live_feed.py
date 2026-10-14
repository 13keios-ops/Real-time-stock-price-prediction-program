import importlib.util
from datetime import datetime,timedelta
import unittest


class CandidateLiveFeedTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.fromisoformat('2026-10-15T09:00:10+09:00')
        self.assertIsNotNone(importlib.util.find_spec('app.collectors.candidate_live_feed'),'Actual WS feed bridge missing')
        from app.collectors.candidate_live_feed import CandidateLiveFeed
        self.feed=CandidateLiveFeed(('001440','006800'),clock=lambda:self.now)
        self.cumulative=0

    def trade(self,symbol='001440',qty=10):
        self.cumulative+=qty
        return {'MKSC_SHRN_ISCD':symbol,'BSOP_DATE':self.now.strftime('%Y%m%d'),
                'STCK_CNTG_HOUR':self.now.strftime('%H%M%S'),'STCK_PRPR':'25000',
                'CNTG_VOL':str(qty),'ACML_VOL':str(self.cumulative)}

    def test_actual_business_day_is_required_before_http(self):
        row=self.trade();row.pop('BSOP_DATE')
        with self.assertRaises(ValueError):self.feed.observe_record('H0STCNT0',row)
        with self.assertRaises(ValueError):self.feed.preflight('/uapi/domestic-stock/v1/quotations/inquire-price',{'FID_INPUT_ISCD':'001440'})

    def test_observed_ws_day_verifies_same_symbol_only(self):
        self.feed.observe_record('H0STCNT0',self.trade())
        proof=self.feed('/uapi/domestic-stock/v1/quotations/inquire-price',{'FID_INPUT_ISCD':'001440'},
                        {'output':{'stck_shrn_iscd':'001440'}})
        self.assertEqual(proof['trade_date'],'2026-10-15')
        self.assertEqual(proof['verification_scope'],'same_symbol_ws_business_day')
        with self.assertRaises(ValueError):self.feed.preflight('/uapi/domestic-stock/v1/quotations/inquire-price',{'FID_INPUT_ISCD':'006800'})
        self.now+=timedelta(seconds=21)
        with self.assertRaises(ValueError):self.feed.preflight('/uapi/domestic-stock/v1/quotations/inquire-price',{'FID_INPUT_ISCD':'001440'})

    def test_first_partial_minute_is_not_admitted_and_real_counts_are_preserved(self):
        self.feed.observe_record('H0STCNT0',self.trade())
        for i in range(1,23):
            self.now=datetime.fromisoformat('2026-10-15T09:00:10+09:00')+timedelta(minutes=i)
            self.feed.observe_record('H0STCNT0',self.trade())
        bars=self.feed.bars('001440')
        self.assertEqual(len(bars),21)
        self.assertEqual(bars[0]['bar_time'],'2026-10-15T09:01:00+09:00')
        self.assertEqual(bars[-1]['trade_count'],1)
        self.assertEqual(bars[-1]['volume'],10)

    def test_duplicate_and_missing_execution_restart_warmup(self):
        row=self.trade();self.feed.observe_record('H0STCNT0',row)
        self.assertFalse(self.feed.observe_record('H0STCNT0',row))
        self.now+=timedelta(minutes=1)
        self.feed.observe_record('H0STCNT0',self.trade())
        self.cumulative+=100
        self.now+=timedelta(minutes=1)
        self.feed.observe_record('H0STCNT0',self.trade())
        self.assertGreater(self.feed.gap_count,0)
        self.assertEqual(self.feed.bars('001440'),[])

    def test_quote_day_comes_from_actual_own_ws_day(self):
        self.feed.observe_record('H0STCNT0',self.trade())
        self.feed.observe_record('H0STASP0',{'MKSC_SHRN_ISCD':'001440','BSOP_HOUR':'090010',
            'ASKP1':'25010','BIDP1':'25000','ASKP_RSQN1':'100','BIDP_RSQN1':'100'})
        quote=self.feed.quote('001440')
        self.assertEqual(quote['trade_date'],'2026-10-15')
        self.assertEqual(quote['provider_at'],'2026-10-15T09:00:10+09:00')
        with self.assertRaises(ValueError):self.feed.quote('006800')

    def test_unrelated_records_do_not_extend_universe(self):
        self.assertFalse(self.feed.observe_record('H0STCNT0',self.trade('005930')))
        self.assertEqual(self.feed.bars('005930'),[])
