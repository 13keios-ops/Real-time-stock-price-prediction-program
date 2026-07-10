import inspect
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from app.brokers.kis_quote_rest import KisRestQuoteClient
from app.brokers.kis_readonly import KisReadOnlyClient, get_kis_live_readonly_client, get_kis_readonly_client
from app.config.settings import load_settings


class LiveReadOnlyGuardTests(unittest.TestCase):
    def test_readonly_client_does_not_expose_order_methods(self) -> None:
        client = KisReadOnlyClient(MagicMock())

        self.assertFalse(hasattr(client, "submit_cash_order"))
        self.assertFalse(hasattr(client, "cancel_order"))

    def test_readonly_method_signatures_match_delegate(self) -> None:
        method_names = (
            "describe",
            "get_current_price",
            "get_orderbook",
            "get_intraday_minute_chart",
            "get_account_balance",
            "get_daily_order_fills",
        )

        for method_name in method_names:
            with self.subTest(method_name=method_name):
                self.assertEqual(
                    inspect.signature(getattr(KisReadOnlyClient, method_name)),
                    inspect.signature(getattr(KisRestQuoteClient, method_name)),
                )

    def test_readonly_client_delegates_quote_and_account_reads(self) -> None:
        delegate = MagicMock()
        delegate.describe.return_value = {"transport": "rest"}
        delegate.get_current_price.return_value = object()
        delegate.get_orderbook.return_value = object()
        delegate.get_intraday_minute_chart.return_value = []
        delegate.get_account_balance.return_value = object()
        delegate.get_daily_order_fills.return_value = []
        client = KisReadOnlyClient(delegate)

        self.assertEqual(client.describe(), {"transport": "rest", "access": "read-only"})
        self.assertEqual(delegate.describe.return_value, {"transport": "rest"})
        delegate.describe.assert_called_once_with()

        self.assertIs(client.get_current_price("005930"), delegate.get_current_price.return_value)
        delegate.get_current_price.assert_called_once_with(symbol="005930", market_code="J")

        self.assertIs(client.get_orderbook("005930"), delegate.get_orderbook.return_value)
        delegate.get_orderbook.assert_called_once_with(symbol="005930", market_code="J")

        self.assertEqual(client.get_intraday_minute_chart("005930"), [])
        delegate.get_intraday_minute_chart.assert_called_once_with(
            "005930",
            input_hour="153000",
            market_code="J",
            include_past_data=True,
        )

        self.assertIs(client.get_account_balance(), delegate.get_account_balance.return_value)
        delegate.get_account_balance.assert_called_once_with(inqr_dvsn="02", max_pages=10)

        self.assertEqual(client.get_daily_order_fills(start_date="20260514", end_date="20260514"), [])
        delegate.get_daily_order_fills.assert_called_once_with(
            start_date="20260514",
            end_date="20260514",
            symbol="",
            order_no="",
            side_filter="00",
            filled_filter="00",
            order_filter_3="00",
            order_filter_1="",
            exchange_code="KRX",
            max_pages=10,
        )

    def test_readonly_client_exposes_copied_last_response_headers(self) -> None:
        delegate = MagicMock()
        delegate.last_response_headers = {"date": "Wed, 20 May 2026 00:00:00 GMT"}
        client = KisReadOnlyClient(delegate)

        headers = client.last_response_headers
        headers["date"] = "mutated"

        self.assertEqual(client.last_response_headers["date"], "Wed, 20 May 2026 00:00:00 GMT")

    def test_readonly_factory_accepts_paper_and_live_modes(self) -> None:
        settings = load_settings(project_root=Path(__file__).resolve().parents[1], env={})
        profile = object()
        token_manager = object()
        rest_client = object()

        with (
            patch("app.brokers.kis_readonly.get_kis_profile", return_value=profile) as mocked_profile,
            patch("app.brokers.kis_readonly.KisTokenManager", return_value=token_manager) as mocked_manager,
            patch("app.brokers.kis_readonly.KisRestQuoteClient", return_value=rest_client) as mocked_rest_client,
        ):
            paper_client = get_kis_readonly_client(settings, mode="paper", timeout_seconds=6)
            live_client = get_kis_readonly_client(settings, mode="live", timeout_seconds=7)

        self.assertIsInstance(paper_client, KisReadOnlyClient)
        self.assertIsInstance(live_client, KisReadOnlyClient)
        self.assertEqual(mocked_profile.call_args_list[0].args, (settings, "paper"))
        self.assertEqual(mocked_profile.call_args_list[1].args, (settings, "live"))
        self.assertEqual(mocked_manager.call_count, 2)
        self.assertEqual(mocked_rest_client.call_args_list[0].kwargs["timeout_seconds"], 6)
        self.assertEqual(mocked_rest_client.call_args_list[1].kwargs["timeout_seconds"], 7)

    def test_readonly_factory_rejects_unknown_mode(self) -> None:
        settings = load_settings(project_root=Path(__file__).resolve().parents[1], env={})

        with self.assertRaises(ValueError):
            get_kis_readonly_client(settings, mode="sandbox")

    def test_live_readonly_factory_uses_live_profile_only(self) -> None:
        settings = load_settings(project_root=Path(__file__).resolve().parents[1], env={})
        profile = object()
        token_manager = object()
        rest_client = object()

        with (
            patch("app.brokers.kis_readonly.get_kis_profile", return_value=profile) as mocked_profile,
            patch("app.brokers.kis_readonly.KisTokenManager", return_value=token_manager) as mocked_manager,
            patch("app.brokers.kis_readonly.KisRestQuoteClient", return_value=rest_client) as mocked_rest_client,
        ):
            readonly_client = get_kis_live_readonly_client(settings, timeout_seconds=7)

        mocked_profile.assert_called_once_with(settings, "live")
        mocked_manager.assert_called_once_with(profile)
        mocked_rest_client.assert_called_once_with(
            profile=profile,
            token_manager=token_manager,
            timeout_seconds=7,
        )
        self.assertIsInstance(readonly_client, KisReadOnlyClient)
        self.assertIs(readonly_client._client, rest_client)

    def test_live_readonly_factory_rejects_non_live_mode(self) -> None:
        settings = load_settings(project_root=Path(__file__).resolve().parents[1], env={})

        with self.assertRaises(ValueError):
            get_kis_live_readonly_client(settings, mode="paper")

    def test_live_readonly_factory_call_does_not_trigger_network(self) -> None:
        settings = load_settings(project_root=Path(__file__).resolve().parents[1], env={})

        with (
            patch("app.brokers.kis_auth.urlopen") as mocked_auth_urlopen,
            patch("app.brokers.kis_quote_rest.urlopen") as mocked_rest_urlopen,
        ):
            readonly_client = get_kis_live_readonly_client(settings)

        self.assertIsInstance(readonly_client, KisReadOnlyClient)
        mocked_auth_urlopen.assert_not_called()
        mocked_rest_urlopen.assert_not_called()

    def test_import_does_not_trigger_network(self) -> None:
        with (
            patch("app.brokers.kis_auth.urlopen") as mocked_auth_urlopen,
            patch("app.brokers.kis_quote_rest.urlopen") as mocked_rest_urlopen,
        ):
            import app.brokers.kis_readonly  # noqa: F401

        mocked_auth_urlopen.assert_not_called()
        mocked_rest_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
