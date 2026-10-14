import importlib.util
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.brokers.kis_quote_rest import KisRestQuoteClient
from tests.test_kis_http_clients import _mock_response


def _try_candidate(folder, queue):
    from app.brokers.kis_paper_coordinator import PaperRequestCoordinator, PaperCoordinatorBusy
    try:
        with PaperRequestCoordinator(folder).slot(timeout_seconds=3, low_priority=True):
            queue.put('entered')
    except PaperCoordinatorBusy:
        queue.put('deferred')


def _reserve_and_exit(folder, ready):
    import os
    from app.brokers.kis_paper_coordinator import PaperRequestCoordinator
    with PaperRequestCoordinator(folder, clock=lambda:100.0).slot(timeout_seconds=3):
        ready.set()
        os._exit(0)


class PaperCoordinatorTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'.tmp-tests';root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/'coord'
        self.now=100.0
        self.sleeps=[]

    def coordinator(self):
        self.assertIsNotNone(importlib.util.find_spec('app.brokers.kis_paper_coordinator'),
                             'Shared paper coordinator missing')
        from app.brokers.kis_paper_coordinator import PaperRequestCoordinator
        def sleep(seconds):
            self.sleeps.append(seconds);self.now+=seconds
        return PaperRequestCoordinator(self.folder, clock=lambda:self.now, sleep=sleep)

    def test_completion_gap_persists_across_instances(self):
        first=self.coordinator()
        with first.slot(timeout_seconds=3): self.now+=2
        with self.coordinator().slot(timeout_seconds=3): pass
        self.assertAlmostEqual(sum(self.sleeps),1.1)
        state=json.loads((self.folder/'state.json').read_text())
        self.assertEqual(set(state),{'version','not_before'})

    def test_candidate_does_not_wait_or_send_during_cooldown(self):
        c=self.coordinator()
        from app.brokers.kis_paper_coordinator import PaperCoordinatorBusy
        with c.slot(timeout_seconds=3): pass
        with self.assertRaises(PaperCoordinatorBusy):
            with c.slot(timeout_seconds=3, low_priority=True): self.fail('Must defer')
        self.assertEqual(self.sleeps,[])

    def test_failure_still_records_response_completion_gap(self):
        c=self.coordinator()
        with self.assertRaises(OSError):
            with c.slot(timeout_seconds=3): raise OSError('failure')
        with c.slot(timeout_seconds=3): pass
        self.assertAlmostEqual(sum(self.sleeps),1.1)

    def test_cross_process_primary_lock_defers_candidate(self):
        c=self.coordinator()
        ctx=multiprocessing.get_context('fork');q=ctx.Queue()
        with c.slot(timeout_seconds=3):
            proc=ctx.Process(target=_try_candidate,args=(str(self.folder),q));proc.start()
            proc.join(5)
            if proc.is_alive(): proc.terminate();proc.join();self.fail('Coordinator child stuck')
            self.assertEqual(proc.exitcode,0);self.assertEqual(q.get(timeout=2),'deferred')
        q.close();q.join_thread()

    def test_corrupt_state_fails_closed(self):
        c=self.coordinator();(self.folder/'state.json').write_text('{bad')
        with self.assertRaises(ValueError):
            with c.slot(timeout_seconds=3): self.fail('Invalid state must block')

    def test_symlink_and_invalid_timeout_fail_closed(self):
        c=self.coordinator()
        for timeout in (0, True, float('inf')):
            with self.assertRaises(ValueError):
                with c.slot(timeout_seconds=timeout): self.fail('Bad timeout')
        (self.folder/'state.json').symlink_to(Path(self.temp.name)/'foreign')
        with self.assertRaises(ValueError):
            with c.slot(timeout_seconds=3): self.fail('Linked state')

    def test_interrupted_reservation_is_not_silently_discarded(self):
        c=self.coordinator()
        (self.folder/'state.json').write_text(json.dumps({'version':'paper-request-pacing-v1','not_before':104.1}))
        from app.brokers.kis_paper_coordinator import PaperCoordinatorBusy
        with self.assertRaises(PaperCoordinatorBusy):
            with c.slot(timeout_seconds=3,low_priority=True): self.fail('Reserved slot')

    def test_killed_process_keeps_reservation_and_releases_lock(self):
        c=self.coordinator()
        ctx=multiprocessing.get_context('fork');ready=ctx.Event()
        proc=ctx.Process(target=_reserve_and_exit,args=(str(self.folder),ready));proc.start()
        if not ready.wait(5):proc.terminate();proc.join();self.fail('Reservation child stuck')
        proc.join(5)
        if proc.is_alive():proc.terminate();proc.join();self.fail('Child did not exit')
        self.assertEqual(proc.exitcode,0)
        from app.brokers.kis_paper_coordinator import PaperCoordinatorBusy
        with self.assertRaises(PaperCoordinatorBusy):
            with c.slot(timeout_seconds=3,low_priority=True):self.fail('Crash reservation discarded')
        self.now=105.0
        with c.slot(timeout_seconds=3,low_priority=True):pass

    def test_candidate_factory_injects_low_priority_and_keeps_cached_auth(self):
        from app.brokers.kis_readonly import get_kis_paper_candidate_client
        profile=SimpleNamespace(mode='paper',rest_url='https://openapivts.koreainvestment.com:29443')
        manager=SimpleNamespace(load_cached_token=lambda:SimpleNamespace(is_expired=False))
        c=self.coordinator()
        with patch('app.brokers.kis_readonly.KisRestQuoteClient') as factory:
            get_kis_paper_candidate_client(profile,manager,request_coordinator=c)
            self.assertIs(factory.call_args.kwargs['request_coordinator'],c)
            self.assertTrue(factory.call_args.kwargs['low_priority'])

    def test_profile_change_and_low_priority_post_are_blocked_before_http(self):
        from unittest.mock import Mock
        c=self.coordinator()
        profile=SimpleNamespace(mode='paper',rest_url='https://example.invalid',app_key='fixture',
                                app_secret='fixture',customer_type='P')
        manager=SimpleNamespace(get_access_token=Mock(return_value=SimpleNamespace(authorization_header='Bearer fixture')))
        client=KisRestQuoteClient(profile,manager,request_coordinator=c,low_priority=True)
        with patch('app.brokers.kis_quote_rest.urlopen',return_value=_mock_response({'rt_cd':'0'})) as network:
            with self.assertRaises(ValueError):client._post_response('/order','TR',{})
            profile.mode='live'
            with self.assertRaises(ValueError):client._request_response('/quote','TR',{})
            network.assert_not_called()
            manager.get_access_token.assert_not_called()

    def test_transport_injection_is_paper_only_and_covers_get_post(self):
        c=self.coordinator()
        profile=SimpleNamespace(mode='paper',rest_url='https://example.invalid',app_key='fixture',
                                app_secret='fixture',customer_type='P')
        manager=SimpleNamespace(get_access_token=lambda:SimpleNamespace(authorization_header='Bearer fixture'))
        self.assertIn('request_coordinator', __import__('inspect').signature(KisRestQuoteClient).parameters)
        client=KisRestQuoteClient(profile,manager,request_coordinator=c)
        with patch('app.brokers.kis_quote_rest.urlopen',return_value=_mock_response({'rt_cd':'0'})) as request:
            client._request_response('/quote','TR',{})
            client._post_response('/order','TR',{})
            self.assertEqual(request.call_count,2)
        self.assertAlmostEqual(sum(self.sleeps),1.1)
        profile.mode='live'
        with self.assertRaises(ValueError): KisRestQuoteClient(profile,manager,request_coordinator=c)
