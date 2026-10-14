from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.brokers.kis_candidate_reader import CandidateRestReader


class CandidateReaderTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-10-14T10:00:00+09:00")
        self.profile = SimpleNamespace(mode="paper", rest_url="https://openapivts.koreainvestment.com:29443")
        self.manager = SimpleNamespace(load_cached_token=lambda: SimpleNamespace(is_expired=False))
        self.proof = dict(trade_date="2026-10-14", verified_at=self.now.isoformat(),
                          provider_at=self.now.isoformat(), source_hash="a"*64,
                          verification_version="kis-exchange-day-anchor-v1")
        outer = self
        self.calls = []
        class Client:
            def __init__(self, profile, token_manager, timeout_seconds):
                self.token_manager, self.calls = token_manager, outer.calls
            def _request_response(self, **kwargs):
                self.token_manager.get_access_token()
                self.calls.append(kwargs)
                return outer.payload, {}
        self.patch = patch("app.brokers.kis_readonly.KisRestQuoteClient", Client)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.payload = dict(rt_cd="0", msg_cd="MCA00000", output1=dict(askp1="25000", bidp1="24950", aspr_acpt_hour="100000", appsecret="SECRET_FIXTURE"))
        self.reader = CandidateRestReader(self.profile, self.manager, verifier=lambda *args: self.proof, clock=lambda: self.now)

    def quote(self, **kwargs):
        return self.reader.get("/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn", "FHKST01010200",
                               dict(FID_COND_MRKT_DIV_CODE="J", FID_INPUT_ISCD="123456"),
                               timeout_seconds=3, allow_retry=False, **kwargs)

    def test_cached_only_get_and_no_secret_response(self):
        result = self.quote()
        self.assertEqual(result["trade_date"], "2026-10-14")
        self.assertNotIn("SECRET_FIXTURE", str(result))
        call = self.calls[0]
        self.assertFalse(call["allow_retry"])
        self.assertTrue(call["allow_business_error"])

    def test_missing_verifier_blocks_before_request(self):
        self.reader = CandidateRestReader(self.profile, self.manager, clock=lambda: self.now)
        with self.assertRaises(ValueError):
            self.quote()
        self.assertEqual(self.calls, [])

    def test_expired_cache_does_not_issue_token(self):
        self.manager.load_cached_token = lambda: None
        with self.assertRaises(ValueError):
            self.quote()
        self.assertEqual(self.calls, [])

    def test_order_endpoint_and_extra_account_params_blocked(self):
        with self.assertRaises(ValueError):
            self.reader.get("/uapi/domestic-stock/v1/trading/order-cash", "VTTC0012U", {}, timeout_seconds=3, allow_retry=False)
        with self.assertRaises(ValueError):
            self.reader.get("/uapi/domestic-stock/v1/quotations/inquire-price", "FHKST01010100",
                            dict(FID_COND_MRKT_DIV_CODE="J", FID_INPUT_ISCD="123456", CANO="SECRET_FIXTURE"),
                            timeout_seconds=3, allow_retry=False)
        self.assertEqual(self.calls, [])

    def test_live_profile_and_wrong_host_rejected(self):
        for profile in (SimpleNamespace(mode="live", rest_url=self.profile.rest_url),
                        SimpleNamespace(mode="paper", rest_url="https://example.com")):
            with self.assertRaises(ValueError):
                CandidateRestReader(profile, self.manager)

    def test_wrapper_exposes_no_order_and_rejects_nonquote_endpoint(self):
        self.assertFalse(hasattr(self.reader._client, 'submit_cash_order'))
        self.assertFalse(hasattr(self.reader._client, 'cancel_order'))
        with self.assertRaises(ValueError):
            self.reader._client.get_candidate_response(path='/uapi/domestic-stock/v1/trading/order-cash',
                tr_id='VTTC0012U', query_params={})
        self.assertEqual(self.calls, [])

    def test_provider_time_cannot_be_receipt_time(self):
        self.payload["output1"]["aspr_acpt_hour"] = "200000"
        with self.assertRaises(ValueError):
            self.quote()

    def test_old_day_proof_rejected(self):
        self.proof["trade_date"] = "2026-10-13"
        with self.assertRaises(ValueError):
            self.quote()

    def test_retry_surface_rejected(self):
        with self.assertRaises(ValueError):
            self.reader.get("/uapi/domestic-stock/v1/quotations/inquire-price", "FHKST01010100", {},
                            timeout_seconds=3, allow_retry=True)

    def test_business_error_has_no_raw_message(self):
        self.payload = dict(rt_cd="1", msg_cd="EGW00201", msg1="SECRET_FIXTURE")
        self.assertEqual(self.quote(), dict(rt_cd="1", msg_cd="EGW00201"))
