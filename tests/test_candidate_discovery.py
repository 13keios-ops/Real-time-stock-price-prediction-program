from datetime import datetime,timedelta
import importlib.util
import unittest


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('app.universe.candidate_discovery'),'50-symbol discovery missing')
        from app.universe import candidate_discovery
        self.module=candidate_discovery
        self.now=datetime.fromisoformat('2026-10-16T10:00:00+09:00')

    def snapshots(self,duplicate=False):
        result={}
        for market,offset in [('KOSPI',0),('KOSDAQ',0 if duplicate else 30)]:
            result[market]=dict(rt_cd='0',trade_date='2026-10-16',received_at=self.now.isoformat(),
                verification_scope='market_trading_day_context_only',output=[dict(
                    mksc_shrn_iscd=f'{i+offset+1:06d}',hts_kor_isnm='sample',stck_prpr='25000',
                    prdy_ctrt='3.5',acml_vol='200000',prdy_vol='100000',acml_tr_pbmn=str(5000000000-i)) for i in range(30)])
        return result

    def test_fifty_unique_screened_is_not_fifty_trade_ready(self):
        report=self.module.screen_rankings(self.snapshots(),as_of=self.now)
        self.assertEqual(report['inspected_count'],50)
        self.assertEqual(report['unique_returned_count'],60)
        self.assertTrue(report['coverage_met'])
        self.assertEqual(report['trade_ready_count'],0)
        self.assertEqual({r['market'] for r in report['candidates']},{'KOSPI','KOSDAQ'})
        self.assertTrue(all(r['stage']=='rank_screen_only' for r in report['candidates']))

    def test_repeated_or_small_responses_never_claim_fifty(self):
        report=self.module.screen_rankings(self.snapshots(duplicate=True),as_of=self.now)
        self.assertFalse(report['coverage_met'])
        self.assertEqual(report['unique_returned_count'],30)
        self.assertLess(report['inspected_count'],50)

    def test_stale_or_wrong_day_and_missing_market_fail_closed(self):
        for key,value in [('trade_date','2026-10-15'),('received_at',(self.now-timedelta(minutes=1)).isoformat())]:
            snapshots=self.snapshots();snapshots['KOSPI'][key]=value
            with self.assertRaises(ValueError):self.module.screen_rankings(snapshots,as_of=self.now)
        snapshots=self.snapshots();snapshots.pop('KOSDAQ')
        with self.assertRaises(ValueError):self.module.screen_rankings(snapshots,as_of=self.now)

    def test_numeric_evidence_and_secret_redaction(self):
        snapshots=self.snapshots();row=snapshots['KOSPI']['output'][0]
        row['app_secret']='SECRET_SENTINEL';row['prdy_vol']='0'
        report=self.module.screen_rankings(snapshots,as_of=self.now)
        self.assertNotIn('SECRET_SENTINEL',str(report))
        match=next(r for r in report['candidates'] if r['symbol']==row['mksc_shrn_iscd'])
        self.assertIsNone(match['volume_ratio'])
        row['stck_prpr']='nan'
        report=self.module.screen_rankings(snapshots,as_of=self.now)
        self.assertEqual(report['invalid_row_count'],1)

    def test_price_band_is_explicit_not_silently_relaxed_entry_policy(self):
        snapshots=self.snapshots();snapshots['KOSPI']['output'][0]['stck_prpr']='100000'
        report=self.module.screen_rankings(snapshots,as_of=self.now)
        row=next(r for r in report['candidates'] if r['symbol']=='000001')
        self.assertFalse(row['preferred_price_band'])
        self.assertEqual(row['entry_blocking_reason'],'outside_existing_price_band')
