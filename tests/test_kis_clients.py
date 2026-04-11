from pathlib import Path
import unittest

from app.brokers.kis_auth import KisTokenManager, get_active_kis_profile
from app.brokers.kis_quote_rest import KisCurrentPriceQuote, KisOrderbookQuote, KisRestQuoteClient
from app.brokers.kis_quote_ws import (
    DOMESTIC_ORDERBOOK_TR_ID,
    DOMESTIC_TRADE_TR_ID,
    KisWebSocketQuoteClient,
)
from app.collectors.market_data import market_tick_from_kis_quote, orderbook_from_kis_quote
from app.config.settings import load_settings
from app.utils.time import now_local


class KisClientTests(unittest.TestCase):
    def test_active_profile_uses_paper_urls_by_default(self) -> None:
        root = Path(__file__).resolve().parents[1]
        settings = load_settings(
            project_root=root,
            env={
                "KIS_APP_KEY_PAPER": "paper-key",
                "KIS_APP_SECRET_PAPER": "paper-secret",
            },
        )
        profile = get_active_kis_profile(settings)

        self.assertEqual(profile.mode, "paper")
        self.assertIn("openapivts.koreainvestment.com", profile.rest_url)
        self.assertIn("ops.koreainvestment.com:31000", profile.ws_url)

    def test_rest_client_describe(self) -> None:
        root = Path(__file__).resolve().parents[1]
        settings = load_settings(
            project_root=root,
            env={
                "KIS_APP_KEY_PAPER": "paper-key",
                "KIS_APP_SECRET_PAPER": "paper-secret",
            },
        )
        profile = get_active_kis_profile(settings)
        client = KisRestQuoteClient(profile=profile, token_manager=KisTokenManager(profile))

        self.assertEqual(client.describe()["status"], "active")

    def test_websocket_subscription_message_shape(self) -> None:
        root = Path(__file__).resolve().parents[1]
        settings = load_settings(
            project_root=root,
            env={
                "KIS_APP_KEY_PAPER": "paper-key",
                "KIS_APP_SECRET_PAPER": "paper-secret",
            },
        )
        profile = get_active_kis_profile(settings)
        client = KisWebSocketQuoteClient(profile=profile, token_manager=KisTokenManager(profile))

        trade_subscription = client.build_domestic_trade_subscription("005930")
        orderbook_subscription = client.build_domestic_orderbook_subscription("005930")
        trade_message = trade_subscription.to_message("approval-token")

        self.assertEqual(trade_subscription.tr_id, DOMESTIC_TRADE_TR_ID)
        self.assertEqual(orderbook_subscription.tr_id, DOMESTIC_ORDERBOOK_TR_ID)
        self.assertEqual(trade_message["body"]["input"]["tr_key"], "005930")
        self.assertEqual(trade_message["header"]["approval_key"], "approval-token")

    def test_kis_quote_conversion_to_internal_events(self) -> None:
        event_time = now_local("Asia/Seoul")
        current = KisCurrentPriceQuote(
            symbol="005930",
            market_code="J",
            current_price=70200,
            open_price=70000,
            high_price=70500,
            low_price=69900,
            prev_close_price=69800,
            accumulated_volume=123456,
            accumulated_trading_value=987654321,
            price_change_sign="2",
            price_change_abs=400,
            price_change_pct=0.57,
        )
        orderbook = KisOrderbookQuote(
            symbol="005930",
            market_code="J",
            ask_price_1=70200,
            bid_price_1=70100,
            ask_size_1=100,
            bid_size_1=120,
            total_ask_size=1000,
            total_bid_size=1200,
            expected_match_price=70150,
            expected_match_qty=300,
        )

        tick_event = market_tick_from_kis_quote(current, event_time=event_time)
        orderbook_event = orderbook_from_kis_quote(orderbook, event_time=event_time)

        self.assertEqual(tick_event.price, 70200.0)
        self.assertEqual(orderbook_event.ask_price, 70200.0)
        self.assertEqual(orderbook_event.bid_size, 120)


if __name__ == "__main__":
    unittest.main()
