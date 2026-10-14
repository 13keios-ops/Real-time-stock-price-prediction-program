import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.brokers.kis_auth import KisTokenManager, get_kis_profile
from app.brokers.kis_paper_coordinator import PaperRequestCoordinator, PaperCoordinatorBusy
from app.config.settings import load_settings
from app.services.broker_paper import BrokerPaperMirror, BrokerPaperSubmissionError
from tests import test_broker_paper_failure_guard as broker_fixtures
from tests.test_kis_http_clients import _mock_response


class PaperRuntimeCoordinationTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]
        temp=tempfile.TemporaryDirectory(dir=root/'.tmp-tests');self.addCleanup(temp.cleanup)
        self.runtime=Path(temp.name)
        self.settings=load_settings(project_root=root,env={'RUNTIME_DATA_DIR':str(self.runtime),
            'DATABASE_URL':f"sqlite:///{self.runtime/'test.db'}",'TRADING_MODE':'paper',
            'KIS_APP_KEY_PAPER':'fixture','KIS_APP_SECRET_PAPER':'fixture',
            'KIS_ACCOUNT_NO_PAPER':'12345678','KIS_PRODUCT_CODE_PAPER':'01',
            'ENABLE_BROKER_PAPER_MIRRORING':'true'})
        self.now=100.0;self.sleeps=[]
        def sleep(seconds):self.sleeps.append(seconds);self.now+=seconds
        self.coordinator=PaperRequestCoordinator(self.runtime/'coord',clock=lambda:self.now,sleep=sleep)

    def manager(self):
        self.assertIn('request_coordinator',inspect.signature(KisTokenManager).parameters)
        return KisTokenManager(get_kis_profile(self.settings),request_coordinator=self.coordinator)

    def test_approval_and_hashkey_http_share_completion_gap(self):
        manager=self.manager()
        with patch('app.brokers.kis_auth.urlopen',side_effect=[_mock_response({'approval_key':'fixture'}),
                                                            _mock_response({'HASH':'fixture'})]) as http:
            self.assertEqual(manager.issue_approval_key(),'fixture')
            self.assertEqual(manager.issue_hashkey({}),'fixture')
            self.assertEqual(http.call_count,2)
        self.assertAlmostEqual(sum(self.sleeps),1.1)

    def test_token_issue_uses_same_slot_and_only_temporary_cache(self):
        manager=self.manager()
        with self.coordinator.slot(timeout_seconds=3):pass
        with patch('app.brokers.kis_auth.urlopen',return_value=_mock_response({'access_token':'fixture','expires_in':3600})):
            manager.issue_access_token()
        self.assertAlmostEqual(sum(self.sleeps),1.1)
        self.assertTrue(manager.profile.token_cache_path.is_relative_to(self.runtime))

    def test_live_auth_with_coordinator_is_rejected(self):
        self.assertIn('request_coordinator',inspect.signature(KisTokenManager).parameters)
        with self.assertRaises(ValueError):
            KisTokenManager(get_kis_profile(self.settings,'live'),request_coordinator=self.coordinator)

    def test_mirror_registers_auth_and_submission_coordinator(self):
        self.assertIn('request_coordinator',inspect.signature(BrokerPaperMirror).parameters)
        mirror=BrokerPaperMirror(self.settings,request_coordinator=self.coordinator)
        self.assertIs(mirror.client._request_coordinator,self.coordinator)
        self.assertIs(mirror.client.token_manager.request_coordinator,self.coordinator)

    def test_deferred_submission_has_no_broker_http_attempt_and_no_account_circuit(self):
        mirror=BrokerPaperMirror(self.settings)
        mirror.client=Mock()
        mirror.client.submit_cash_order.side_effect=PaperCoordinatorBusy('primary slot unavailable')
        with self.assertRaises(BrokerPaperSubmissionError) as caught:
            mirror.submit_local_order(broker_fixtures.BrokerPaperFailureGuardTests._order(),decision_id='decision-fixture')
        failure=caught.exception.failure
        self.assertEqual(failure.category,'broker_request_deferred')
        self.assertFalse(failure.network_attempted)
        self.assertFalse(failure.circuit_opened)
        self.assertIsNone(mirror._account_hard_rejection_until)
        self.assertTrue(caught.exception.attempt_id)

    def test_processor_registers_same_owner_for_mirror_and_fill_sync(self):
        from app.services.streaming import OnlinePipelineProcessor
        self.assertIn('paper_request_coordinator',inspect.signature(OnlinePipelineProcessor).parameters)
        processor=OnlinePipelineProcessor(self.settings,paper_request_coordinator=self.coordinator)
        self.assertIs(processor.broker_paper_mirror.client._request_coordinator,self.coordinator)
        self.assertIs(processor.broker_paper_sync.broker_mirror.client._request_coordinator,self.coordinator)

    def test_ws_listener_exposes_explicit_owner_injection(self):
        from app.services.streaming import run_kis_ws_listener
        self.assertIn('paper_request_coordinator',inspect.signature(run_kis_ws_listener).parameters)

    def test_pre_http_close_deferral_does_not_create_unknown_or_permanent_retry_block(self):
        from datetime import datetime, timedelta
        from app.services.streaming import OnlinePipelineProcessor
        from app.storage.contracts import Fill
        from app.storage.runtime_writer import get_sqlite_store
        processor=OnlinePipelineProcessor(self.settings,max_hold_minutes=1)
        stamp=datetime.fromisoformat('2026-10-15T10:00:00+09:00')
        fill=Fill('fill-fixture','order-fixture',stamp,70000,1,0,0)
        processor.portfolio_book.apply_buy_fill('005930',fill=fill,fill_price=70000)
        with patch.object(processor.broker_paper_mirror,'submit_local_order',side_effect=PaperCoordinatorBusy('busy')) as submit:
            reason=processor._maybe_close_position('005930',70100,stamp+timedelta(minutes=5))
            self.assertEqual(reason,'broker_request_deferred')
            row=get_sqlite_store(self.settings).fetch_latest_row('paper_orders','event_time')
            self.assertEqual(row['status'],'deferred')
            self.assertNotIn('005930',processor.pending_order_symbols)
            self.assertNotIn('005930',processor.close_retry_blocked_symbols)
            processor._restore_close_retry_block_state()
            self.assertNotIn('005930',processor.close_retry_blocked_symbols)
            processor._maybe_close_position('005930',70100,stamp+timedelta(minutes=6))
            self.assertEqual(submit.call_count,2)
