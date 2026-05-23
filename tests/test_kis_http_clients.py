from pathlib import Path
import json
import unittest
from unittest.mock import MagicMock, patch

from app.brokers.kis_auth import KisAccessToken, KisApiError, KisTokenManager, get_active_kis_profile
from app.brokers.kis_quote_rest import KisRestQuoteClient
from app.config.settings import load_settings
from app.services.system_clock import reference_time_from_http_date_header
from app.utils.time import now_local


def _mock_response(payload: dict, *, headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.headers = headers or {"tr_cont": ""}
    context_manager = MagicMock()
    context_manager.__enter__.return_value = response
    context_manager.__exit__.return_value = False
    return context_manager


class KisHttpClientTests(unittest.TestCase):
    def _build_profile(self):
        root = Path(__file__).resolve().parents[1]
        settings = load_settings(
            project_root=root,
            env={
                "KIS_APP_KEY_PAPER": "paper-key",
                "KIS_APP_SECRET_PAPER": "paper-secret",
                "KIS_ACCOUNT_NO_PAPER": "12345678",
                "KIS_PRODUCT_CODE_PAPER": "01",
            },
        )
        return get_active_kis_profile(settings)

    @patch("app.brokers.kis_auth.urlopen")
    def test_issue_access_token(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = _mock_response(
            {
                "access_token": "issued-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        )
        profile = self._build_profile()
        manager = KisTokenManager(profile)

        token = manager.issue_access_token()

        self.assertEqual(token.access_token, "issued-token")
        self.assertEqual(token.token_type, "Bearer")
        self.assertTrue(profile.token_cache_path.exists())

    @patch("app.brokers.kis_quote_rest.urlopen")
    def test_get_current_price(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = _mock_response(
            {
                "rt_cd": "0",
                "output": {
                    "stck_prpr": "70200",
                    "stck_oprc": "70000",
                    "stck_hgpr": "70500",
                    "stck_lwpr": "69900",
                    "stck_sdpr": "69800",
                    "acml_vol": "123456",
                    "acml_tr_pbmn": "987654321",
                    "prdy_vrss_sign": "2",
                    "prdy_vrss": "400",
                    "prdy_ctrt": "0.57",
                },
            }
        )
        profile = self._build_profile()
        manager = KisTokenManager(profile)
        manager.get_access_token = MagicMock(
            return_value=KisAccessToken(
                access_token="cached-token",
                token_type="Bearer",
                expires_at=now_local("Asia/Seoul"),
            )
        )
        client = KisRestQuoteClient(profile=profile, token_manager=manager)

        quote = client.get_current_price("005930")

        self.assertEqual(quote.symbol, "005930")
        self.assertEqual(quote.current_price, 70200)
        self.assertEqual(quote.accumulated_volume, 123456)

    @patch("app.brokers.kis_quote_rest.urlopen")
    def test_last_response_headers_exposes_http_date_for_clock_reference(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = _mock_response(
            {
                "rt_cd": "0",
                "output": {
                    "stck_prpr": "70200",
                    "stck_oprc": "70000",
                    "stck_hgpr": "70500",
                    "stck_lwpr": "69900",
                    "stck_sdpr": "69800",
                    "acml_vol": "123456",
                    "acml_tr_pbmn": "987654321",
                    "prdy_vrss_sign": "2",
                    "prdy_vrss": "400",
                    "prdy_ctrt": "0.57",
                },
            },
            headers={
                "Date": "Wed, 20 May 2026 00:00:00 GMT",
                "tr_cont": "",
            },
        )
        profile = self._build_profile()
        manager = KisTokenManager(profile)
        manager.get_access_token = MagicMock(
            return_value=KisAccessToken(
                access_token="cached-token",
                token_type="Bearer",
                expires_at=now_local("Asia/Seoul"),
            )
        )
        client = KisRestQuoteClient(profile=profile, token_manager=manager)

        client.get_current_price("005930")
        headers = client.last_response_headers
        headers["date"] = "mutated"
        reference = reference_time_from_http_date_header(client.last_response_headers)

        self.assertEqual(client.last_response_headers["date"], "Wed, 20 May 2026 00:00:00 GMT")
        self.assertEqual(reference.source, "kis_rest_http_date")
        self.assertEqual(reference.reference_time.isoformat(), "2026-05-20T00:00:00+00:00")

    @patch("app.brokers.kis_quote_rest.urlopen")
    def test_last_response_headers_are_cleared_before_failed_request(self, mocked_urlopen) -> None:
        success_payload = {
            "rt_cd": "0",
            "output": {
                "stck_prpr": "70200",
                "stck_oprc": "70000",
                "stck_hgpr": "70500",
                "stck_lwpr": "69900",
                "stck_sdpr": "69800",
                "acml_vol": "123456",
                "acml_tr_pbmn": "987654321",
                "prdy_vrss_sign": "2",
                "prdy_vrss": "400",
                "prdy_ctrt": "0.57",
            },
        }
        mocked_urlopen.side_effect = [
            _mock_response(success_payload, headers={"Date": "Wed, 20 May 2026 00:00:00 GMT"}),
            _mock_response({"rt_cd": "1", "msg1": "business error"}, headers={"Date": "Wed, 20 May 2026 00:00:01 GMT"}),
        ]
        profile = self._build_profile()
        manager = KisTokenManager(profile)
        manager.get_access_token = MagicMock(
            return_value=KisAccessToken(
                access_token="cached-token",
                token_type="Bearer",
                expires_at=now_local("Asia/Seoul"),
            )
        )
        client = KisRestQuoteClient(profile=profile, token_manager=manager)

        client.get_current_price("005930")
        self.assertIn("date", client.last_response_headers)
        with self.assertRaises(KisApiError):
            client.get_current_price("005930")

        self.assertEqual(client.last_response_headers, {})

    @patch("app.brokers.kis_quote_rest.urlopen")
    def test_get_account_balance(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = _mock_response(
            {
                "rt_cd": "0",
                "output1": [
                    {
                        "pdno": "005930",
                        "prdt_name": "삼성전자",
                        "hldg_qty": "3",
                        "ord_psbl_qty": "3",
                        "pchs_avg_pric": "70000",
                        "pchs_amt": "210000",
                        "prpr": "71500",
                        "evlu_amt": "214500",
                        "evlu_pfls_amt": "4500",
                        "evlu_pfls_rt": "2.14",
                    }
                ],
                "output2": [
                    {
                        "dnca_tot_amt": "1000000",
                        "scts_evlu_amt": "214500",
                        "tot_evlu_amt": "1214500",
                        "pchs_amt_smtl_amt": "210000",
                        "evlu_pfls_smtl_amt": "4500",
                        "nass_amt": "1214500",
                    }
                ],
                "ctx_area_fk100": "",
                "ctx_area_nk100": "",
            }
        )
        profile = self._build_profile()
        manager = KisTokenManager(profile)
        manager.get_access_token = MagicMock(
            return_value=KisAccessToken(
                access_token="cached-token",
                token_type="Bearer",
                expires_at=now_local("Asia/Seoul"),
            )
        )
        client = KisRestQuoteClient(profile=profile, token_manager=manager)

        snapshot = client.get_account_balance()

        self.assertEqual(snapshot.account_no_masked, "1234****")
        self.assertEqual(snapshot.cash_balance, 1000000)
        self.assertEqual(snapshot.position_row_count, 1)
        self.assertEqual(snapshot.positions[0].symbol, "005930")
        self.assertEqual(snapshot.positions[0].holding_qty, 3)

    @patch("app.brokers.kis_quote_rest.urlopen")
    def test_get_daily_order_fills(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = _mock_response(
            {
                "rt_cd": "0",
                "output1": [
                    {
                        "ord_dt": "20260417",
                        "ord_gno_brno": "00111",
                        "odno": "1234567890",
                        "orgn_odno": "",
                        "pdno": "005930",
                        "prdt_name": "삼성전자",
                        "sll_buy_dvsn_cd": "02",
                        "sll_buy_dvsn_cd_name": "매수",
                        "ord_dvsn_cd": "00",
                        "ord_dvsn_name": "지정가",
                        "ord_tmd": "101530",
                        "ord_qty": "3",
                        "ord_unpr": "70000",
                        "tot_ccld_qty": "3",
                        "rmn_qty": "0",
                        "avg_prvs": "70100",
                        "tot_ccld_amt": "210300",
                        "cncl_cfrm_qty": "0",
                        "rjct_qty": "0",
                        "cncl_yn": "N",
                        "excg_id_dvsn_cd": "KRX",
                    }
                ],
                "ctx_area_fk100": "",
                "ctx_area_nk100": "",
            }
        )
        profile = self._build_profile()
        manager = KisTokenManager(profile)
        manager.get_access_token = MagicMock(
            return_value=KisAccessToken(
                access_token="cached-token",
                token_type="Bearer",
                expires_at=now_local("Asia/Seoul"),
            )
        )
        client = KisRestQuoteClient(profile=profile, token_manager=manager)

        rows = client.get_daily_order_fills(start_date="20260417", end_date="20260417")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].symbol, "005930")
        self.assertEqual(rows[0].filled_qty, 3)
        self.assertEqual(rows[0].avg_fill_price, 70100.0)

    @patch("app.brokers.kis_quote_rest.urlopen")
    def test_get_daily_order_fills_accepts_redacted_runtime_fixture_shape(self, mocked_urlopen) -> None:
        # Redacted KIS paper status snapshot exported by scripts/export_kis_paper_fixture_candidates.py.
        mocked_urlopen.return_value = _mock_response(
            {
                "rt_cd": "0",
                "output1": [
                    {
                        "ord_dt": "20260515",
                        "ord_gno_brno": "00950",
                        "ord_orgno": "",
                        "odno": "0000025448",
                        "orgn_odno": "0000000000",
                        "pdno": "373220",
                        "prdt_name": "",
                        "sll_buy_dvsn_cd": "01",
                        "sll_buy_dvsn_cd_name": "매도",
                        "ord_dvsn_cd": "00",
                        "ord_dvsn_name": "지정가",
                        "ord_tmd": "115605",
                        "ord_qty": "1",
                        "ord_unpr": "432500",
                        "tot_ccld_qty": "1",
                        "rmn_qty": "0",
                        "avg_prvs": "432500",
                        "tot_ccld_amt": "432500",
                        "cncl_cfrm_qty": "0",
                        "rjct_qty": "0",
                        "cncl_yn": "N",
                        "excg_id_dvsn_cd": "KRX",
                    }
                ],
                "ctx_area_fk100": "",
                "ctx_area_nk100": "",
            }
        )
        profile = self._build_profile()
        manager = KisTokenManager(profile)
        manager.get_access_token = MagicMock(
            return_value=KisAccessToken(
                access_token="cached-token",
                token_type="Bearer",
                expires_at=now_local("Asia/Seoul"),
            )
        )
        client = KisRestQuoteClient(profile=profile, token_manager=manager)

        rows = client.get_daily_order_fills(start_date="20260515", end_date="20260515")

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.order_date, "20260515")
        self.assertEqual(row.broker_branch_no, "00950")
        self.assertEqual(row.broker_order_no, "0000025448")
        self.assertEqual(row.symbol, "373220")
        self.assertEqual(row.side, "01")
        self.assertEqual(row.order_qty, 1)
        self.assertEqual(row.filled_qty, 1)
        self.assertEqual(row.remaining_qty, 0)
        self.assertEqual(row.avg_fill_price, 432500.0)
        self.assertFalse(row.cancel_yn)
        self.assertEqual(row.exchange_id, "KRX")

    @patch("app.brokers.kis_quote_rest.urlopen")
    def test_get_daily_order_fills_accepts_alternate_kis_field_names(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = _mock_response(
            {
                "rt_cd": "0",
                "output1": [
                    {
                        "ord_dt": "20260417",
                        "ord_orgno": "00112",
                        "odno": "1234567891",
                        "orgn_odno": "",
                        "pdno": "005930",
                        "prdt_name": "삼성전자",
                        "sll_buy_dvsn_cd": "02",
                        "sll_buy_dvsn_cd_name": "매수",
                        "ord_dvsn_cd": "00",
                        "ord_dvsn_cd_name": "지정가",
                        "ord_tmd": "101531",
                        "ord_qty": "3",
                        "ord_unpr": "70000",
                        "ccld_qty": "2",
                        "ord_remn_qty": "1",
                        "avg_ccld_unpr": "70150",
                        "tot_ccld_amt": "140300",
                        "cncl_cfrm_qty": "1",
                        "rjct_qty": "0",
                        "cncl_yn": "Y",
                        "excg_dvsn_cd": "KRX",
                    }
                ],
                "ctx_area_fk100": "",
                "ctx_area_nk100": "",
            }
        )
        profile = self._build_profile()
        manager = KisTokenManager(profile)
        manager.get_access_token = MagicMock(
            return_value=KisAccessToken(
                access_token="cached-token",
                token_type="Bearer",
                expires_at=now_local("Asia/Seoul"),
            )
        )
        client = KisRestQuoteClient(profile=profile, token_manager=manager)

        rows = client.get_daily_order_fills(start_date="20260417", end_date="20260417")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].broker_branch_no, "00112")
        self.assertEqual(rows[0].filled_qty, 2)
        self.assertEqual(rows[0].remaining_qty, 1)
        self.assertEqual(rows[0].avg_fill_price, 70150.0)
        self.assertEqual(rows[0].cancel_confirm_qty, 1)
        self.assertTrue(rows[0].cancel_yn)
        self.assertEqual(rows[0].exchange_id, "KRX")

    @patch("app.brokers.kis_quote_rest.urlopen")
    def test_get_daily_order_fills_paginates_when_kis_continuation_header_present(self, mocked_urlopen) -> None:
        first_page = {
            "rt_cd": "0",
            "output1": [
                {
                    "ord_dt": "20260417",
                    "ord_gno_brno": "00111",
                    "odno": "1234567890",
                    "orgn_odno": "",
                    "pdno": "005930",
                    "prdt_name": "삼성전자",
                    "sll_buy_dvsn_cd": "02",
                    "sll_buy_dvsn_cd_name": "매수",
                    "ord_dvsn_cd": "00",
                    "ord_dvsn_name": "지정가",
                    "ord_tmd": "101530",
                    "ord_qty": "3",
                    "ord_unpr": "70000",
                    "tot_ccld_qty": "3",
                    "rmn_qty": "0",
                    "avg_prvs": "70100",
                    "tot_ccld_amt": "210300",
                    "cncl_cfrm_qty": "0",
                    "rjct_qty": "0",
                    "cncl_yn": "N",
                    "excg_id_dvsn_cd": "KRX",
                }
            ],
            "ctx_area_fk100": "next-fk",
            "ctx_area_nk100": "next-nk",
        }
        second_page = {
            "rt_cd": "0",
            "output1": [
                {
                    "ord_dt": "20260417",
                    "ord_gno_brno": "00111",
                    "odno": "1234567892",
                    "orgn_odno": "",
                    "pdno": "000660",
                    "prdt_name": "SK하이닉스",
                    "sll_buy_dvsn_cd": "01",
                    "sll_buy_dvsn_cd_name": "매도",
                    "ord_dvsn_cd": "00",
                    "ord_dvsn_name": "지정가",
                    "ord_tmd": "101700",
                    "ord_qty": "2",
                    "ord_unpr": "180000",
                    "tot_ccld_qty": "1",
                    "rmn_qty": "1",
                    "avg_prvs": "180500",
                    "tot_ccld_amt": "180500",
                    "cncl_cfrm_qty": "0",
                    "rjct_qty": "0",
                    "cncl_yn": "N",
                    "excg_id_dvsn_cd": "KRX",
                }
            ],
            "ctx_area_fk100": "",
            "ctx_area_nk100": "",
        }
        mocked_urlopen.side_effect = [
            _mock_response(first_page, headers={"tr_cont": "M"}),
            _mock_response(second_page, headers={"tr_cont": ""}),
        ]
        profile = self._build_profile()
        manager = KisTokenManager(profile)
        manager.get_access_token = MagicMock(
            return_value=KisAccessToken(
                access_token="cached-token",
                token_type="Bearer",
                expires_at=now_local("Asia/Seoul"),
            )
        )
        client = KisRestQuoteClient(profile=profile, token_manager=manager)

        rows = client.get_daily_order_fills(start_date="20260417", end_date="20260417")

        self.assertEqual(mocked_urlopen.call_count, 2)
        self.assertEqual([row.broker_order_no for row in rows], ["1234567890", "1234567892"])
        self.assertEqual(rows[1].side, "01")
        self.assertEqual(rows[1].filled_qty, 1)
        self.assertEqual(rows[1].remaining_qty, 1)

    @patch("app.brokers.kis_quote_rest.urlopen")
    def test_submit_cash_order(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = _mock_response(
            {
                "rt_cd": "0",
                "msg_cd": "APBK0013",
                "msg1": "주문 전송 완료",
                "output": {
                    "KRX_FWDG_ORD_ORGNO": "00111",
                    "ODNO": "1234567890",
                    "ORD_TMD": "101530",
                },
            }
        )
        profile = self._build_profile()
        manager = KisTokenManager(profile)
        manager.get_access_token = MagicMock(
            return_value=KisAccessToken(
                access_token="cached-token",
                token_type="Bearer",
                expires_at=now_local("Asia/Seoul"),
            )
        )
        manager.issue_hashkey = MagicMock(return_value="hash-key")
        client = KisRestQuoteClient(profile=profile, token_manager=manager)

        result = client.submit_cash_order(symbol="005930", side="buy", qty=3, limit_price=70000)

        self.assertEqual(result.mode, "paper")
        self.assertEqual(result.side, "buy")
        self.assertEqual(result.symbol, "005930")
        self.assertEqual(result.qty, 3)
        self.assertEqual(result.broker_order_no, "1234567890")
        self.assertEqual(result.broker_branch_no, "00111")


if __name__ == "__main__":
    unittest.main()
