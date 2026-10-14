from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.universe.kis_candidate_provenance import make_master_reference, DatedMinuteVerifier
from app.universe.kis_candidate_sources import build_metadata
from app.services.candidate_pipeline import make_capture_cycle, replay_comparison, prepare_candidate_context
from app.paper_trading.daily_mission import MissionContract
from tests import test_kis_candidate_provenance as provenance_fixtures
from tests import test_kis_candidate_sources as source_fixtures
from tests import test_kis_candidate_snapshot as capture_fixtures


class SourceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.fromisoformat('2026-10-14T10:00:10+09:00')
        self.raw=provenance_fixtures.ProvenanceTests().master()
        self.minute={'request_symbol':'001440','received_at':self.now.isoformat(),
            'payload':{'rt_cd':'0','output2':[{'stck_bsop_date':'20261014','stck_cntg_hour':'100000'}]}}

    def reference(self):
        data=bytearray(self.raw.rstrip(b'\r\n'));data[len(data)-227+22]=32
        return make_master_reference(bytes(data)+b'\n',market='KOSPI',symbol='001440',
            acquired_at=self.now-timedelta(minutes=30))

    def quote(self):
        f=source_fixtures.CandidateSourceTests();f.setUp()
        return {**f.quote,'observed_at':self.now.isoformat(),
            'output':{**f.quote['output'],'stck_shrn_iscd':'001440'}}

    def test_explicit_acquisition_reference_not_effective_date(self):
        ref=self.reference();self.assertIsNone(ref['reference_date'])
        self.assertFalse(ref['effective_day_verified'])
        m=build_metadata(ref,self.quote(),as_of=self.now)
        self.assertEqual(m['master_reference_basis'],'same_day_acquired_snapshot')
        self.assertTrue(all(v is False for v in m['flags'].values()))
        self.assertEqual(m['master_etp_raw'],'')

    def test_stale_future_and_unknown_reference_blocked(self):
        for value in [self.now-timedelta(days=1),self.now-timedelta(hours=9),self.now+timedelta(seconds=1)]:
            ref=self.reference();ref['acquired_at']=value.isoformat()
            with self.assertRaises(ValueError):build_metadata(ref,self.quote(),as_of=self.now)
        ref=self.reference();ref.pop('layout_version')
        with self.assertRaises(ValueError):build_metadata(ref,self.quote(),as_of=self.now)

    def test_blank_not_missing_or_unknown_etp_and_equity_identity(self):
        for field,value in [('etp_prod_cls_code',None),('etp_prod_cls_code','9'),('scrt_grp_cls_code','EF'),('prst_cls_code','1')]:
            ref=self.reference();ref['output'][field]=value
            with self.assertRaises(ValueError):build_metadata(ref,self.quote(),as_of=self.now)

    def verifier(self, records=None):
        return DatedMinuteVerifier(records or {'001440':self.minute},market_anchor_symbol='001440',clock=lambda:self.now)

    def test_same_symbol_quote_day_and_reported_hour(self):
        proof=self.verifier()('/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn',
            {'FID_INPUT_ISCD':'001440'},{'output1':{'aspr_acpt_hour':'100005'}})
        self.assertEqual(proof['provider_at'],'2026-10-14T10:00:05+09:00')
        self.assertEqual(proof['verification_scope'],'same_symbol_dated_minute')

    def test_ranking_day_context_does_not_certify_other_symbol_quote(self):
        v=self.verifier()
        p=v('/uapi/domestic-stock/v1/quotations/volume-rank',{}, {'output':[]})
        self.assertEqual(p['verification_scope'],'market_trading_day_context_only')
        with self.assertRaises(ValueError):
            v('/uapi/domestic-stock/v1/quotations/inquire-price',{'FID_INPUT_ISCD':'006800'}, {'output':{'stck_shrn_iscd':'006800'}})

    def test_index_uses_day_context_not_fake_provider_timestamp(self):
        p=self.verifier()('/uapi/domestic-stock/v1/quotations/inquire-index-price',{'FID_INPUT_ISCD':'0001'},{'output':{'bstp_nmix_prdy_ctrt':'1'}})
        self.assertEqual(p['verification_scope'],'index_market_day_context_only')
        self.assertNotIn('provider_at',p)

    def test_context_assembler_binds_actual_sector_without_network(self):
        q=self.quote();q.update(rt_cd='0',received_at=q['observed_at'])
        def index(code):return {'rt_cd':'0','trade_date':'2026-10-14','received_at':self.now.isoformat(),
            'index_code':code,'output':{'bstp_nmix_prdy_ctrt':'1'}}
        c=prepare_candidate_context(self.reference(),q,index('0001'),index('0021'),[],as_of=self.now)
        self.assertEqual(c['benchmark']['metadata_source_hash'],c['metadata']['source_hash'])
        with self.assertRaises(ValueError):
            prepare_candidate_context(self.reference(),q,index('0001'),index('2001'),[],as_of=self.now)

    def test_wrong_symbol_stale_book_and_wrong_anchor_owner(self):
        v=self.verifier()
        with self.assertRaises(ValueError):
            v('/uapi/domestic-stock/v1/quotations/inquire-price',{'FID_INPUT_ISCD':'001440'}, {'output':{'stck_shrn_iscd':'006800'}})
        with self.assertRaises(ValueError):
            v('/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn',{'FID_INPUT_ISCD':'001440'}, {'output1':{'aspr_acpt_hour':'200000'}})
        self.minute['request_symbol']='006800'
        with self.assertRaises(ValueError):
            v('/uapi/domestic-stock/v1/quotations/volume-rank',{}, {'output':[]})

    def test_pipeline_factory_dry_run_never_requests(self):
        profile=SimpleNamespace(mode='paper',rest_url='https://openapivts.koreainvestment.com:29443')
        manager=SimpleNamespace(load_cached_token=lambda:None)
        with patch('app.brokers.kis_readonly.KisRestQuoteClient') as client:
            cycle=make_capture_cycle(profile,manager,minute_responses={'001440':self.minute},
                market_anchor_symbol='001440',clock=lambda:self.now)
            self.assertEqual(cycle.collect(evidence={})['status'],'dry_run')
            client.return_value._request_response.assert_not_called()

    def test_missing_dated_anchor_blocks_before_http(self):
        profile=SimpleNamespace(mode='paper',rest_url='https://openapivts.koreainvestment.com:29443')
        manager=SimpleNamespace(load_cached_token=lambda:SimpleNamespace(is_expired=False))
        with patch('app.brokers.kis_readonly.KisRestQuoteClient') as client:
            cycle=make_capture_cycle(profile,manager,minute_responses={},market_anchor_symbol='001440',clock=lambda:self.now)
            r=cycle.collect(evidence={},execute=True,budget_authorized=True)
            self.assertEqual(r['status'],'failed_no_retry')
            client.return_value._request_response.assert_not_called()

    def test_refresh_replaces_stale_anchor_without_mutating_caller_record(self):
        v=self.verifier()
        self.minute['received_at']=(self.now-timedelta(seconds=21)).isoformat()
        with self.assertRaises(ValueError):v.preflight('/uapi/domestic-stock/v1/quotations/inquire-price',{'FID_INPUT_ISCD':'001440'})
        self.assertTrue(hasattr(v,'refresh'), 'Validated anchor refresh port missing')
        fresh={'request_symbol':'001440','received_at':self.now.isoformat(),
               'payload':{'rt_cd':'0','output2':[{'stck_bsop_date':'20261014','stck_cntg_hour':'100000','appsecret':'SECRET_FIXTURE'}]}}
        v.refresh('001440',fresh)
        fresh['payload']['output2'][0]['stck_bsop_date']='20261013'
        _,anchor,_=v.preflight('/uapi/domestic-stock/v1/quotations/inquire-price',{'FID_INPUT_ISCD':'001440'})
        self.assertEqual(anchor['trade_date'],'2026-10-14')
        self.assertNotIn('SECRET_FIXTURE',str(v.responses['001440']))

    def test_failed_refresh_does_not_replace_verified_anchor(self):
        v=self.verifier()
        self.assertTrue(hasattr(v,'refresh'), 'Validated anchor refresh port missing')
        with self.assertRaises(ValueError):v.refresh('001440',{'request_symbol':'006800','payload':{},'received_at':self.now.isoformat()})
        self.assertEqual(v.preflight('/uapi/domestic-stock/v1/quotations/inquire-price',{'FID_INPUT_ISCD':'001440'})[1]['trade_date'],'2026-10-14')

    def test_reader_has_validated_no_network_refresh_port(self):
        from app.brokers.kis_candidate_reader import CandidateRestReader
        profile=SimpleNamespace(mode='paper',rest_url='https://openapivts.koreainvestment.com:29443')
        manager=SimpleNamespace(load_cached_token=lambda:None)
        with patch('app.brokers.kis_readonly.KisRestQuoteClient') as network:
            reader=CandidateRestReader(profile,manager,verifier=self.verifier(),clock=lambda:self.now)
            self.assertTrue(hasattr(reader,'refresh_minute_anchor'),'Reader refresh port missing')
            self.assertEqual(reader.refresh_minute_anchor('001440',self.minute)['trade_date'],'2026-10-14')
            network.return_value._request_response.assert_not_called()


class ComparisonReplayTests(unittest.TestCase):
    def setUp(self):
        f=capture_fixtures.KisCandidateSnapshotTests();f.setUp();self.now,self.capture=f.now,f.snapshot
        self.contract=MissionContract(symbols=('123456',))
        self.events=[]
        for row in self.capture['observations']['123456']['bars']:
            stamp=datetime.fromisoformat(row['bar_time'])
            self.events.append({'bar':{'symbol':'123456',**{k:row[k] for k in ('bar_time','open','high','low','close','volume')},'trade_count':50},
                'observed_at':(stamp+timedelta(minutes=1)).isoformat(),'quote_spread_bps':20})
        self.events[-1]['observed_at']=self.now.isoformat();self.events[-1]['capture']=self.capture
        root=Path(__file__).resolve().parents[1]/'.tmp-tests';root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/'comparison'

    def test_default_replay_is_validation_only(self):
        r=replay_comparison(self.events,self.folder,self.contract)
        self.assertEqual(r['status'],'validated_no_execution')
        self.assertFalse(self.folder.exists());self.assertEqual(r['network_calls'],0)

    def test_explicit_replay_keeps_independent_wallets(self):
        r=replay_comparison(self.events,self.folder,self.contract,execute_paper=True)
        self.assertEqual(r['status'],'consistent')
        self.assertEqual(r['wallets']['breakout']['cash_balance'],300000)
        self.assertEqual(r['wallets']['trend_pullback']['cash_balance'],300000)
        self.assertEqual(r['order_calls'],0);self.assertFalse(r['runtime_attached'])

    def test_invalid_source_before_wallet_write(self):
        self.events[-1]['bar']['trade_count']=0
        with self.assertRaises(ValueError):replay_comparison(self.events,self.folder,self.contract,execute_paper=True)
        self.assertFalse(self.folder.exists())

    def test_legacy_capture_rejected_before_wallet_write(self):
        self.events[-1]['capture']['source_binding_version']='legacy'
        with self.assertRaises(ValueError):
            replay_comparison(self.events,self.folder,self.contract,execute_paper=True)
        self.assertFalse(self.folder.exists())

    def test_cli_symlink_target_is_not_resolved_away(self):
        import json
        from scripts.run_candidate_comparison import main
        p=Path(self.temp.name)/'events.json';p.write_text(json.dumps(self.events),encoding='utf-8')
        target=Path(self.temp.name)/'target';target.mkdir()
        link=Path(self.temp.name)/'linked';link.symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):
            main(['--events-file',str(p),'--symbols','123456','--start-date','2026-10-14','--output-dir',str(link)])
        self.assertEqual(list(target.iterdir()),[])

    def test_future_open_bar_and_invalid_ohlc_blocked_before_write(self):
        for key,value in [('observed_at',self.events[-1]['bar']['bar_time']),('high',1)]:
            if key=='observed_at':
                original=self.events[-1][key];self.events[-1][key]=value
            else:
                original=self.events[-1]['bar'][key];self.events[-1]['bar'][key]=value
            with self.assertRaises(ValueError):replay_comparison(self.events,self.folder,self.contract,execute_paper=True)
            self.assertFalse(self.folder.exists())
            if key=='observed_at':self.events[-1][key]=original
            else:self.events[-1]['bar'][key]=original

    def test_cli_default_does_not_create_accounts(self):
        import json,io
        from contextlib import redirect_stdout
        from scripts.run_candidate_comparison import main
        p=Path(self.temp.name)/'events.json';p.write_text(json.dumps(self.events),encoding='utf-8')
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['--events-file',str(p),'--symbols','123456','--start-date','2026-10-14','--output-dir',str(self.folder)]),0)
        self.assertFalse(self.folder.exists())
        self.assertEqual(json.loads(out.getvalue())['status'],'validated_no_execution')
