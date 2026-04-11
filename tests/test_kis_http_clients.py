from pathlib import Path
import json
import unittest
from unittest.mock import MagicMock, patch

from app.brokers.kis_auth import KisAccessToken, KisTokenManager, get_active_kis_profile
from app.brokers.kis_quote_rest import KisRestQuoteClient
from app.config.settings import load_settings
from app.utils.time import now_local


def _mock_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
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


if __name__ == "__main__":
    unittest.main()
