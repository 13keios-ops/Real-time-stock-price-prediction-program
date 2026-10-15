import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


class CandidateDashboardTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('app.services.candidate_dashboard'),'Dedicated dashboard view missing')
        from app.services import candidate_dashboard
        self.module=candidate_dashboard
        root=Path(__file__).resolve().parents[1]/'.tmp-tests';root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=self.root/'paper-missions/kr-intraday-candidate-runtime'

    def write(self,report):
        self.folder.mkdir(parents=True,exist_ok=True)
        (self.folder/'latest-runtime.json').write_text(json.dumps(report))

    def test_missing_data_does_not_create_wallet_or_claim_zero_profit(self):
        data=self.module.load_candidate_dashboard(self.root)
        self.assertEqual(data['status'],'not_available')
        self.assertFalse(self.folder.exists())

    def test_failed_warmup_is_input_failure_not_strategy_loss(self):
        self.write({'day':'2026-10-15','status':'warmup','record_rejections':74836,
            'feed_gap_count':4135,'warmup_bars':{'001440':0,'006800':0},
            'symbols':['001440','006800'],'comparison':{'wallets':{
                'breakout':{'source_bar_count':0,'virtual_fill_count':0,'cash_balance':300000},
                'trend_pullback':{'source_bar_count':0,'virtual_fill_count':0,'cash_balance':300000}}}})
        data=self.module.load_candidate_dashboard(self.root)
        self.assertEqual(data['status'],'input_failed')
        html=self.module.render_candidate_dashboard(data)
        for text in ['001440','006800','74,836','4,135','돌파','눌림목','입력 실패']:
            self.assertIn(text,html)
        self.assertNotIn('수익성 통과',html)
        self.assertIn('min-width:1170px',html)

    def test_explicit_date_never_substitutes_other_day(self):
        self.write({'day':'2026-10-15','status':'warmup'})
        self.assertEqual(self.module.load_candidate_dashboard(self.root,selected_date='2026-10-16')['status'],'not_available')

    def test_expected_preopen_rejections_are_not_input_failure(self):
        self.write({'day':'2026-10-16','status':'warmup','record_rejections':20,
                    'rejection_reasons':{'outside_session':20}})
        self.assertEqual(self.module.load_candidate_dashboard(self.root)['status'],'warming_up')

    def test_prior_day_results_are_not_today_profitability(self):
        self.write({'day':'2026-10-16','status':'warmup','comparison':{'wallets':{'breakout':{
            'trade_date':'2026-10-15','source_bar_count':300,'virtual_fill_count':2,
            'daily_net_pnl':12345,'day_status':'target_reached','cash_balance':310000,
            'daily_history':{'2026-10-15':{'source_bars':300,'fills':2}}}}}})
        (self.folder/'days').mkdir()
        (self.folder/'days/2026-10-16.json').write_bytes((self.folder/'latest-runtime.json').read_bytes())
        data=self.module.load_candidate_dashboard(self.root)
        self.assertEqual(data['status'],'warming_up')
        self.assertIsNone(data['wallets']['breakout']['daily_net_pnl'])
        self.assertEqual(data['wallets']['breakout']['day_source_bar_count'],0)
        self.assertEqual(data['wallets']['breakout']['cash_balance'],310000)
        self.assertNotIn('12,345',self.module.render_candidate_dashboard(data))

    def test_unindexed_old_history_has_execution_budget(self):
        from unittest.mock import patch
        self.write({'day':'2026-10-16'})
        path=self.folder/'wallets/breakout/mission.db';path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as c:
            c.execute('create table mission_events(seq integer primary key,kind text,payload text)')
            c.executemany('insert into mission_events(kind,payload) values(?,?)',[
                ('observation',json.dumps({'event_time':'2026-10-15T11:00:00+09:00'}))]*1000)
        with patch.object(self.module,'READ_BUDGET_SECONDS',-1):
            data=self.module.load_candidate_dashboard(self.root)
        self.assertTrue(data['warnings'])
        self.assertEqual(data['observations'],[])

    def test_escape_report_and_bound_event_payload(self):
        self.write({'day':'2026-10-15','status':'blocked','reason':'<script>alert(1)</script>',
            'symbols':['001440'],'comparison':{'wallets':{'breakout':{'source_bar_count':1}}}})
        path=self.folder/'wallets/breakout/mission.db';path.parent.mkdir(parents=True)
        c=sqlite3.connect(path);c.execute('create table mission_events(seq integer primary key,kind text,payload text)')
        for i in range(205):c.execute('insert into mission_events(kind,payload) values(?,?)',('fill',json.dumps({
            'kind':'fill','symbol':'001440','event_time':'2026-10-15T10:00:00+09:00',
            'qty':1,'price':25000,'side':'buy','app_secret':'SECRET_SENTINEL'})))
        c.commit();c.close()
        data=self.module.load_candidate_dashboard(self.root)
        self.assertLessEqual(len(data['events']),200)
        rendered=self.module.render_candidate_dashboard(data)
        self.assertNotIn('<script>alert',rendered)
        self.assertNotIn('SECRET_SENTINEL',json.dumps(data))
        self.assertIn('001440',rendered)

    def test_archiving_preserves_original_report(self):
        report={'day':'2026-10-15','status':'warmup','record_rejections':74836}
        self.write(report);before=(self.folder/'latest-runtime.json').read_bytes()
        self.module.archive_candidate_report(self.root)
        self.assertEqual(json.loads((self.folder/'days/2026-10-15.json').read_text()),report)
        self.assertEqual((self.folder/'latest-runtime.json').read_bytes(),before)

    def test_observations_never_hide_fills_and_position_mark_uses_ledger_field(self):
        self.write({'day':'2026-10-15','comparison':{'wallets':{'breakout':{'source_bar_count':300,'virtual_fill_count':1}}}})
        path=self.folder/'wallets/breakout/mission.db';path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as c:
            c.execute('create table mission_events(seq integer primary key,kind text,payload text)')
            c.execute('create table mission_state(singleton integer,payload text)')
            c.execute('insert into mission_events(kind,payload) values(?,?)',('fill',json.dumps({
                'kind':'fill','event_time':'2026-10-15T10:00:00+09:00','decision_id':'stable-id'})))
            for _ in range(300):
                c.execute('insert into mission_events(kind,payload) values(?,?)',('observation',json.dumps({
                    'event_time':'2026-10-15T11:00:00+09:00','reason':'not_selected'})))
            c.execute('insert into mission_state values(1,?)',(json.dumps({'trade_date':'2026-10-15',
                'positions':{'001440':{'qty':2,'avg_price':25000,'last_price':25100}}}),))
        data=self.module.load_candidate_dashboard(self.root)
        self.assertEqual([e['decision_id'] for e in data['events']],['stable-id'])
        self.assertEqual(len(data['observations']),200)
        self.assertEqual(data['positions'][0]['mark_price'],25100)

    def test_symlinked_external_report_rejected(self):
        self.folder.mkdir(parents=True)
        outside=self.root/'outside.json';outside.write_text('{"app_secret":"SECRET_SENTINEL"}')
        (self.folder/'latest-runtime.json').symlink_to(outside)
        data=self.module.load_candidate_dashboard(self.root)
        self.assertNotIn('SECRET_SENTINEL',json.dumps(data))
        self.assertEqual(data['status'],'not_available')
