from datetime import datetime
import importlib.util
import json
from pathlib import Path
from queue import Queue
import tempfile
import unittest
from unittest.mock import Mock, patch
from copy import deepcopy
import io
import zipfile
import asyncio

from app.config.settings import load_settings
from app.brokers.kis_auth import get_kis_profile, KisTokenManager
from app.brokers.kis_paper_coordinator import PaperCoordinatorBusy
from app.storage.contracts import MinuteBar
from app.services import streaming


class CandidateRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('app.services.candidate_runtime'),
                             'Approved candidate runtime is not connected')
        from app.services import candidate_runtime
        self.module = candidate_runtime
        root = Path(__file__).resolve().parents[1]
        root.joinpath('.tmp-tests').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root/'.tmp-tests')
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        self.settings = load_settings(project_root=root, env={
            'TRADING_MODE':'paper', 'RUNTIME_DATA_DIR':str(self.runtime),
            'DATABASE_URL':f"sqlite:///{self.runtime/'never-open.db'}",
            'KIS_APP_KEY_PAPER':'fixture', 'KIS_APP_SECRET_PAPER':'fixture'})
        self.now = datetime.fromisoformat('2026-10-15T10:00:10+09:00')

    def initialize(self):
        return self.module.initialize_candidate_runtime(self.settings, start_date='2026-10-15')

    def runner(self):
        self.initialize()
        runner=self.module.load_candidate_runtime(self.settings,primary_symbols=['005930'],clock=lambda:self.now)
        self.assertIsNotNone(runner)
        self.addCleanup(runner.close)
        return runner

    def test_activation_is_offline_two_wallets_and_never_root_db(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('offline activation')):
            report=self.initialize()
        self.assertEqual(report['status'],'armed_awaiting_market_session')
        self.assertEqual(report['symbols'],['001440','006800'])
        self.assertEqual([r['cash_balance'] for r in report['comparison']['wallets'].values()],[300000,300000])
        self.assertFalse((self.runtime/'never-open.db').exists())
        self.assertEqual(report['order_calls'],0)
        self.assertEqual(self.initialize()['spec_hash'],report['spec_hash'])

    def discovery_runner(self):
        self.initialize()
        self.module.enable_candidate_discovery(self.settings)
        runner=self.module.load_candidate_runtime(self.settings,primary_symbols=['005930'],clock=lambda:self.now)
        self.assertIsNotNone(runner);self.addCleanup(runner.close)
        self.source_fixture(runner)
        def response(path,tr_id,params,**kwargs):
            offset=0 if params['FID_INPUT_ISCD']=='0001' else 30
            return dict(rt_cd='0',trade_date=self.now.date().isoformat(),received_at=self.now.isoformat(),
                verification_scope='market_trading_day_context_only',output=[dict(mksc_shrn_iscd=f'{offset+i+1:06d}',
                    stck_prpr='25000',prdy_ctrt='3',acml_vol='20000',prdy_vol='10000',acml_tr_pbmn='5000000000') for i in range(30)])
        runner.reader.get.side_effect=response
        runner.feed.bars.return_value=[];runner.feed.bars.side_effect=None
        return runner

    def test_discovery_precedes_warmup_and_uses_two_shared_budget_reads(self):
        runner=self.discovery_runner();runner.step()
        report=runner.report()
        self.assertEqual(report['discovery']['inspected_count'],50)
        self.assertEqual(report['discovery']['trade_ready_count'],0)
        self.assertEqual(runner.request_count,2)
        runner.step();self.assertEqual(runner.request_count,2)
        for wallet in runner.comparison.wallets.values():
            self.assertEqual(wallet.state['source_bar_count'],0)
        self.assertTrue(list((runner.folder/'discovery').rglob('*.json')))

    def test_actual_reader_waits_for_first_ws_without_poisoning_session(self):
        self.initialize();self.module.enable_candidate_discovery(self.settings)
        runner=self.module.load_candidate_runtime(self.settings,primary_symbols=['005930'],clock=lambda:self.now)
        self.assertIsNotNone(runner);self.addCleanup(runner.close)
        transport=Mock();runner.reader._client=transport
        runner.step()
        self.assertFalse(runner.http_blocked)
        self.assertEqual(runner.request_count,0)
        self.assertEqual(runner.report()['discovery']['status'],'awaiting_ws_date_evidence')
        transport.get_candidate_response.assert_not_called()
        for symbol in runner.symbols:
            runner.observe_record('H0STCNT0',dict(MKSC_SHRN_ISCD=symbol,
                BSOP_DATE=self.now.strftime('%Y%m%d'),STCK_CNTG_HOUR=self.now.strftime('%H%M%S'),
                STCK_PRPR='25000',CNTG_VOL='10',ACML_VOL='1000'))
        def response(**kwargs):
            offset=0 if kwargs['query_params']['FID_INPUT_ISCD']=='0001' else 30
            return dict(rt_cd='0',output=[dict(mksc_shrn_iscd=f'{offset+i+1:06d}',stck_prpr='25000',
                prdy_ctrt='3',acml_vol='20000',prdy_vol='10000',acml_tr_pbmn='5000000000') for i in range(30)]),{}
        transport.get_candidate_response.side_effect=response
        runner.step()
        self.assertEqual(runner.report()['discovery']['inspected_count'],50)
        self.assertFalse(runner.http_blocked)
        self.assertEqual(runner.request_count,2)

    def test_reader_preflight_failure_is_not_http_failure(self):
        runner=self.runner();transport=Mock();runner.reader._client=transport
        with self.assertRaises(ValueError):runner.read(self.module.PREFIX+'volume-rank',dict(self.module.RANK_QUERY))
        self.assertFalse(runner.http_blocked)
        self.assertEqual(runner.request_count,0)
        transport.get_candidate_response.assert_not_called()

    def test_mid_capture_source_expiry_does_not_disable_local_wallets(self):
        from app.brokers.kis_candidate_reader import CandidateSourceNotReady
        runner=self.runner();self.source_fixture(runner)
        runner.reader.get.side_effect=CandidateSourceNotReady('WS source pending')
        runner.step()
        self.assertFalse(runner.http_blocked)
        self.assertEqual(runner.request_count,0)
        for wallet in runner.comparison.wallets.values():self.assertGreater(wallet.state['source_bar_count'],0)

    def test_discovery_error_never_retries_or_resets_wallet(self):
        runner=self.discovery_runner();runner.reader.get.side_effect=ValueError('SECRET_SENTINEL')
        runner.step();runner.step()
        self.assertEqual(runner.reader.get.call_count,1)
        self.assertTrue(runner.http_blocked)
        self.assertEqual(runner.report()['discovery']['status'],'blocked')
        self.assertNotIn('SECRET_SENTINEL',str(runner.report()))
        self.assertEqual(runner.comparison.report()['wallets']['breakout']['cash_balance'],300000)

    def test_discovery_priority_deferral_and_daily_budget_are_preserved(self):
        runner=self.discovery_runner();runner.reader.get.side_effect=PaperCoordinatorBusy('priority')
        runner.step()
        self.assertEqual(runner.request_count,0)
        self.assertFalse(runner.http_blocked)
        self.assertEqual(runner.report()['discovery']['status'],'deferred_primary_priority')

    def test_discovery_interval_survives_restart(self):
        runner=self.discovery_runner();runner.step();runner.close()
        reopened=self.module.load_candidate_runtime(self.settings,primary_symbols=['005930'],clock=lambda:self.now)
        self.assertIsNotNone(reopened);self.addCleanup(reopened.close)
        reopened.reader=Mock()
        reopened.discover_if_due()
        reopened.reader.get.assert_not_called()
        self.assertEqual(reopened.request_count,2)

    def test_discovery_cannot_exceed_daily_budget(self):
        runner=self.discovery_runner();runner.request_count=2499;runner.step()
        self.assertEqual(runner.reader.get.call_count,1)
        self.assertEqual(runner.request_count,2500)
        self.assertEqual(runner.report()['discovery']['inspected_count'],0)

    def test_new_day_clears_prior_day_diagnostic_counts(self):
        from datetime import timedelta
        runner=self.discovery_runner();runner.record_rejections=100;runner.rejection_reasons['missing_field']=100
        runner.step();self.now=(self.now+timedelta(days=1)).replace(hour=8)
        runner.step()
        report=runner.report()
        self.assertEqual(report['record_rejections'],0)
        self.assertEqual(report['rejection_reasons'],{})
        self.assertEqual(report['discovery']['inspected_count'],0)

    def test_discovery_registration_never_changes_existing_account_contract(self):
        self.initialize();folder=self.runtime/self.module.SUBDIRECTORY
        before=(folder/'wallets/comparison.json').read_bytes()
        self.module.enable_candidate_discovery(self.settings)
        self.assertEqual((folder/'wallets/comparison.json').read_bytes(),before)
        from app.universe.candidate_discovery import read_discovery_registration
        self.assertTrue(read_discovery_registration(folder))
        flag=folder/'discovery-enabled.json';value=json.loads(flag.read_text());value['spec']['target_count']=2
        flag.write_text(json.dumps(value))
        self.assertFalse(read_discovery_registration(folder))

    def test_drift_disabled_and_subscription_limit_preserve_primary(self):
        self.assertIsNone(self.module.load_candidate_runtime(self.settings,primary_symbols=['005930']))
        self.initialize()
        self.assertIsNone(self.module.load_candidate_runtime(self.settings,primary_symbols=[f'{i:06d}' for i in range(20)]))
        flag=self.runtime/self.module.SUBDIRECTORY/'enabled.json'
        value=json.loads(flag.read_text());value['spec']['symbols'].append('005930')
        flag.write_text(json.dumps(value))
        self.assertIsNone(self.module.load_candidate_runtime(self.settings,primary_symbols=['005930']))
        self.assertIsNone(KisTokenManager(get_kis_profile(self.settings)).request_coordinator)

    def test_primary_auth_rest_and_low_priority_reader_share_registration(self):
        self.initialize()
        profile=get_kis_profile(self.settings);manager=KisTokenManager(profile)
        self.assertIsNotNone(manager.request_coordinator)
        from app.brokers.kis_quote_rest import KisRestQuoteClient
        self.assertIsNotNone(KisRestQuoteClient(profile,manager)._request_coordinator)
        from app.brokers.kis_readonly import get_kis_paper_candidate_client
        self.assertTrue(get_kis_paper_candidate_client(profile,manager)._client._low_priority)

    def test_extra_records_never_reach_primary_candidate_error_contained(self):
        queue=Queue();primary=Mock();candidate=Mock()
        candidate.observe_record.side_effect=ValueError('invalid date')
        queue.put({'tr_id':'H0STCNT0','records':[{'MKSC_SHRN_ISCD':'001440'},{'MKSC_SHRN_ISCD':'005930'}]})
        queue.put(streaming._PIPELINE_QUEUE_STOP)
        streaming._consume_kis_ws_frames(primary,queue,candidate_runtime=candidate,primary_symbols={'005930'})
        primary.process_trade_record.assert_called_once_with({'MKSC_SHRN_ISCD':'005930'})

    def test_http_error_blocks_session_redacts_and_does_not_retry(self):
        runner=self.runner();runner.reader=Mock()
        runner.reader.get.side_effect=ValueError('secret-token-must-not-leak')
        with self.assertRaises(ValueError):runner.read('/uapi/domestic-stock/v1/quotations/volume-rank',{})
        self.assertTrue(runner.http_blocked)
        count=runner.request_count
        with self.assertRaises(ValueError):runner.read('/uapi/domestic-stock/v1/quotations/volume-rank',{})
        self.assertEqual(runner.request_count,count)
        self.assertNotIn('secret-token',json.dumps(runner.report()))

    def test_busy_defers_without_permanent_failure_and_budget_blocks(self):
        runner=self.runner();runner.reader=Mock()
        runner.reader.get.side_effect=PaperCoordinatorBusy('primary priority')
        with self.assertRaises(PaperCoordinatorBusy):runner.read('/uapi/domestic-stock/v1/quotations/volume-rank',{})
        self.assertFalse(runner.http_blocked)
        runner.reader.reset_mock();runner.request_count=2500
        with self.assertRaises(ValueError):runner.read('/uapi/domestic-stock/v1/quotations/volume-rank',{})
        runner.reader.get.assert_not_called()

    def test_http_block_preserves_local_marks_and_exit_path(self):
        runner=self.runner();runner.http_blocked=True
        bar=MinuteBar(symbol='001440',bar_time=self.now.replace(hour=9,minute=59,second=0),
            open=25000,high=25010,low=24990,close=25000,volume=1000,trade_count=5)
        runner.deliver(bar,quote_spread_bps=20,capture=None)
        for wallet in runner.comparison.wallets.values():self.assertEqual(wallet.state['source_bar_count'],1)

    def source_fixture(self, runner):
        from tests import test_kis_candidate_snapshot as snapshot_fixtures
        from tests import test_kis_candidate_sources as source_fixtures
        snapshot=snapshot_fixtures.KisCandidateSnapshotTests();snapshot.setUp()
        source=source_fixtures.CandidateSourceTests();source.setUp()
        self.now=snapshot.now.replace(day=15)
        runner.day=self.now.date().isoformat()
        # Explicit source day belongs to this isolated fixture, never receipt-date fabrication.
        runner.master={};quotes={};bars={}
        for symbol,sector in zip(runner.symbols,('0027','0021')):
            master=deepcopy(source.master);master['output']['mksc_shrn_iscd']=symbol
            master['reference_date']=self.now.date().isoformat()
            master['output']['bstp_larg_div_code']=sector;runner.master[symbol]=master
            quote=deepcopy(source.quote)
            quote['output'].update(stck_shrn_iscd=symbol,stck_prpr='25000',prdy_ctrt='5',acml_tr_pbmn='2000000000')
            quote.update(rt_cd='0',received_at=self.now.isoformat(),trade_date=self.now.date().isoformat())
            quotes[symbol]=quote
            bars[symbol]=deepcopy(snapshot.snapshot['observations']['123456']['bars'])
            for row in bars[symbol]:
                row['trade_count']=50
                for key in ('bar_time','available_at'):
                    row[key]=datetime.fromisoformat(row[key]).replace(day=15).isoformat()
        runner.feed=Mock()
        runner.feed.gap_count=0
        runner.feed.cumulative_jump_count=0
        runner.feed.bars.side_effect=lambda symbol:bars[symbol]
        runner.feed.quote.side_effect=lambda symbol:dict(rt_cd='0',trade_date=self.now.date().isoformat(),
            received_at=self.now.isoformat(),provider_at=self.now.isoformat(),output1={'askp1':25010,'bidp1':25000})
        rows=[]
        for symbol in runner.symbols:
            row=deepcopy(snapshot.snapshot['rows'][0]);row['mksc_shrn_iscd']=symbol;rows.append(row)
        def get(path,tr_id,params,**kwargs):
            envelope=dict(rt_cd='0',trade_date=self.now.date().isoformat(),received_at=self.now.isoformat())
            if path.endswith('volume-rank'):return dict(**envelope,output=rows)
            if path.endswith('inquire-index-price'):return dict(**envelope,index_code=params['FID_INPUT_ISCD'],output={'bstp_nmix_prdy_ctrt':'1'})
            return quotes[params['FID_INPUT_ISCD']]
        runner.reader=Mock();runner.reader.get.side_effect=get
        runner.stop=Mock();runner.stop.is_set.return_value=False;runner.stop.wait.return_value=False
        return bars

    def test_actual_capture_uses_six_reads_and_preserves_previous_volume(self):
        runner=self.runner();self.source_fixture(runner)
        capture=runner.capture()
        self.assertEqual(runner.reader.get.call_count,6)
        self.assertEqual(runner.request_count,6)
        self.assertIn('prdy_vol',capture['rows'][0])
        self.assertEqual(set(capture['observations']),{'001440','006800'})
        self.assertIsNotNone(runner.last_scan)
        self.assertEqual(runner.cycle_count,1)

    def test_actual_sampled_feed_reaches_wallets_without_fabricating_volume(self):
        from datetime import timedelta
        from app.collectors.candidate_live_feed import CandidateLiveFeed
        runner=self.runner();self.source_fixture(runner)
        runner.feed=CandidateLiveFeed(runner.symbols,clock=lambda:self.now)
        beginning=self.now.replace(hour=9,minute=9,second=10)
        for minute in range(23):
            self.now=beginning+timedelta(minutes=minute)
            for symbol in runner.symbols:
                runner.observe_record('H0STCNT0',dict(MKSC_SHRN_ISCD=symbol,BSOP_DATE='20261015',
                    STCK_CNTG_HOUR=self.now.strftime('%H%M%S'),STCK_PRPR='25000',CNTG_VOL='10',ACML_VOL=str(1000+minute*100)))
                runner.observe_record('H0STASP0',dict(MKSC_SHRN_ISCD=symbol,
                    BSOP_HOUR=self.now.strftime('%H%M%S'),ASKP1='25010',BIDP1='25000'))
        runner.step()
        self.assertEqual(runner.reader.get.call_count,6)
        self.assertEqual(runner.feed.gap_count,0)
        self.assertGreater(runner.feed.cumulative_jump_count,0)
        for wallet in runner.comparison.wallets.values():self.assertGreater(wallet.state['source_bar_count'],0)
        for symbol in runner.symbols:
            self.assertTrue(all(row['volume']==10 for row in runner.feed.bars(symbol)))
        report=json.loads((runner.folder/'days/2026-10-15.json').read_text())
        self.assertEqual(report['volume_scope'],'captured_ws_records_only')

    def test_rejection_evidence_is_numeric_allowlisted_and_primary_continues(self):
        runner=self.runner()
        runner.observe_record('H0STCNT0',dict(MKSC_SHRN_ISCD='001440',BSOP_DATE='bad-date',
            STCK_CNTG_HOUR='100010',STCK_PRPR='SECRET_SENTINEL',app_secret='SECRET_SENTINEL'))
        runner.write_report()
        report=json.loads((runner.folder/'days/2026-10-15.json').read_text())
        self.assertEqual(report['rejection_reasons'],{'source_validation_failed':1})
        self.assertNotIn('SECRET_SENTINEL',json.dumps(report))
        self.assertFalse(runner.http_blocked)

    def test_report_diagnostics_are_detached_from_receiving_thread(self):
        runner=self.runner();report=runner.report()
        runner.symbol_progress['001440']['accepted_trade_records']=2
        self.assertEqual(report['symbol_progress']['001440']['accepted_trade_records'],0)

    def test_response_failure_stops_remaining_cycle_calls_and_survives_restart(self):
        runner=self.runner();self.source_fixture(runner)
        runner.reader.get.side_effect=[{'rt_cd':'1','msg_cd':'EGW00201'}]
        with self.assertRaises(ValueError):runner.capture()
        self.assertEqual(runner.reader.get.call_count,1)
        self.assertTrue(runner.http_blocked)
        runner.close()
        reopened=self.module.load_candidate_runtime(self.settings,primary_symbols=['005930'],clock=lambda:self.now)
        self.addCleanup(reopened.close)
        self.assertTrue(reopened.http_blocked)
        self.assertEqual(reopened.request_count,1)

    def test_cycle_busy_still_delivers_closed_bars_to_both_wallets(self):
        runner=self.runner();self.source_fixture(runner)
        runner.reader.get.side_effect=PaperCoordinatorBusy('primary')
        runner.step()
        for wallet in runner.comparison.wallets.values():self.assertGreater(wallet.state['source_bar_count'],0)
        self.assertFalse(runner.http_blocked)
        self.assertEqual(runner.request_count,0)

    def test_public_master_exact_member_tls_and_source_hash(self):
        from tests import test_kis_candidate_provenance as fixture
        # A bounded documented fixed-width byte record, not a fabricated parsed metadata row.
        width=227;tail=[' ']*width
        fields={'scrt_grp_cls_code':'ST','bstp_larg_div_code':'0027','etpr_undt_objt_co_yn':'N',
            'short_over_cls_code':'0','trht_yn':'N','sltr_yn':'N','mang_issu_yn':'N',
            'mrkt_alrm_cls_code':'00','prst_cls_code':'0'}
        from app.universe.kis_candidate_provenance import SCHEMAS
        for key,value in fields.items():
            offset,size=SCHEMAS['KOSPI'][1][key];tail[offset:offset+size]=list(value.ljust(size))
        raw=('001440   '+'KR7001440007'+'sample'+''.join(tail)).encode('ascii')+b'\n'
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:archive.writestr('kospi_code.mst',raw)
        response=Mock();response.read.return_value=output.getvalue()
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch('app.services.candidate_runtime.urlopen',return_value=response) as http:
            master=self.module.acquire_master(self.runtime,('001440',),clock=lambda:self.now)
        self.assertEqual(master['001440']['output']['bstp_larg_div_code'],'0027')
        self.assertFalse(master['001440']['effective_day_verified'])
        self.assertEqual(http.call_args.kwargs,{'timeout':5})

    def test_existing_wallet_policy_cannot_be_changed_by_runtime_flag(self):
        self.initialize();flag=self.runtime/self.module.SUBDIRECTORY/'enabled.json'
        value=json.loads(flag.read_text());value['spec']['wallet_contract']['initial_cash']=600000
        from app.universe.intraday_candidates import _hash
        value['spec_hash']=_hash(value['spec']);flag.write_text(json.dumps(value))
        self.assertIsNone(self.module.load_candidate_runtime(self.settings,primary_symbols=['005930']))

    def test_single_runtime_owner_prevents_duplicate_collection(self):
        runner=self.runner()
        second=self.module.load_candidate_runtime(self.settings,primary_symbols=['005930'],clock=lambda:self.now)
        if second is not None:self.addCleanup(second.close)
        self.assertIsNone(second,'Duplicate candidate runtime must not reserve separate budgets')
        runner.close()
        third=self.module.load_candidate_runtime(self.settings,primary_symbols=['005930'],clock=lambda:self.now)
        self.assertIsNotNone(third);self.addCleanup(third.close)

    def test_normal_ws_startup_attaches_single_connection_and_routes_only_primary(self):
        self.initialize()
        processor=Mock();client=Mock();manager=Mock()
        subscriptions=[]
        async def frames(**kwargs):
            subscriptions.append(kwargs['symbols'])
            for symbol in ('001440','005930'):
                row=dict(MKSC_SHRN_ISCD=symbol,BSOP_DATE='20261015',STCK_CNTG_HOUR='090001',
                         STCK_PRPR='25000',CNTG_VOL='10',ACML_VOL='10')
                yield streaming._build_pipe_frame('H0STCNT0',streaming.DOMESTIC_TRADE_COLUMNS,[row])
        client.listen=frames
        with patch.object(streaming,'load_settings',return_value=self.settings), \
                patch.object(streaming,'OnlinePipelineProcessor',return_value=processor), \
                patch.object(streaming,'KisTokenManager',return_value=manager), \
                patch.object(streaming,'KisWebSocketQuoteClient',return_value=client) as factory:
            asyncio.run(streaming.run_kis_ws_listener(self.settings.project_root,symbols=['005930']))
        factory.assert_called_once()
        manager.get_access_token.assert_called_once()
        processor.process_trade_record.assert_called_once()
        self.assertEqual(processor.process_trade_record.call_args.args[0]['MKSC_SHRN_ISCD'],'005930')
        self.assertEqual(subscriptions,[['005930','001440','006800']])

    def test_live_cycle_breakout_future_virtual_fill_and_costs(self):
        runner=self.runner();bars=self.source_fixture(runner)
        evaluation_time=self.now
        for row in bars['001440'][:-1]:
            stamp=datetime.fromisoformat(row['bar_time'])
            from datetime import timedelta
            self.now=stamp+timedelta(minutes=1)
            bar=MinuteBar(symbol='001440',bar_time=stamp,
                **{k:row[k] for k in ('open','high','low','close','volume','trade_count')})
            runner.deliver(bar,quote_spread_bps=20,capture=None)
        self.now=evaluation_time
        runner.step()
        breakout=runner.comparison.wallets['breakout']
        self.assertIsNotNone(breakout.state['pending'])
        self.assertIsNone(runner.comparison.wallets['trend_pullback'].state['pending'])
        stamp=datetime.fromisoformat(breakout.state['pending']['execute_at'])
        self.now=stamp+timedelta(minutes=1)
        runner.deliver(MinuteBar(symbol='001440',bar_time=stamp,open=25000,high=25050,
            low=24950,close=25000,volume=1000,trade_count=50),quote_spread_bps=20,capture=None)
        self.assertEqual(breakout.state['fill_count'],1)
        self.assertGreater(breakout.state['commission'],0)
        self.assertEqual(runner.comparison.wallets['trend_pullback'].state['cash'],300000)

    def test_public_master_failure_is_bounded_and_primary_path_is_not_called(self):
        runner=self.runner();self.source_fixture(runner);runner.master=None
        with patch('app.services.candidate_runtime.urlopen',side_effect=OSError('sensitive transport detail')) as http:
            runner.step();runner.step()
        http.assert_called_once()
        self.assertTrue(runner.http_blocked)
        self.assertEqual(runner.request_count,0)
        self.assertNotIn('sensitive',json.dumps(runner.report()))

    def test_input_evidence_is_durable_before_wallet_write_failure(self):
        runner=self.runner()
        bar=MinuteBar(symbol='001440',bar_time=self.now.replace(hour=9,minute=59,second=0),
            open=25000,high=25010,low=24990,close=25000,volume=1000,trade_count=5)
        with patch.object(runner.comparison,'observe',side_effect=RuntimeError('wallet unavailable')):
            with self.assertRaises(RuntimeError):runner.deliver(bar,quote_spread_bps=20,capture=None)
        journal=runner.folder/'events.jsonl'
        self.assertTrue(journal.exists(),'Source evidence must survive a failed wallet write')
        self.assertEqual(json.loads(journal.read_text())['bar']['symbol'],'001440')

    def test_wrong_registration_shape_cannot_break_primary_auth(self):
        self.initialize();flag=self.runtime/self.module.SUBDIRECTORY/'enabled.json'
        from app.universe.intraday_candidates import _hash
        flag.write_text(json.dumps({'enabled':True,'spec':[],'spec_hash':_hash([])}))
        self.assertIsNone(KisTokenManager(get_kis_profile(self.settings)).request_coordinator)
