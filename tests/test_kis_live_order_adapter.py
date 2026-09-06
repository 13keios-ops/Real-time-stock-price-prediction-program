import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock, create_autospec

from app.brokers.kis_live_order import KisLiveOrderAdapter, KisLiveOrderAdapterError
from app.brokers.kis_quote_rest import KisRestQuoteClient


@dataclass(slots=True)
class FakeSettings:
    trading_mode: str = "live"
    allow_live_orders: bool = True


class KisLiveOrderAdapterTests(unittest.TestCase):
    def test_submit_translates_manager_request_to_kis_client_contract(self) -> None:
        delegate = create_autospec(KisRestQuoteClient, instance=True)
        delegate.submit_cash_order.return_value = {"accepted": True}
        adapter = KisLiveOrderAdapter(delegate, settings=FakeSettings())

        result = adapter.submit_cash_order(
            symbol="005930",
            side="buy",
            qty=1,
            order_type="limit",
            limit_price=70000.0,
            idempotency_key="idem-1",
        )

        self.assertEqual(result, {"accepted": True})
        delegate.submit_cash_order.assert_called_once_with(
            symbol="005930",
            side="buy",
            qty=1,
            order_type="00",
            limit_price=70000.0,
        )

    def test_submit_blocks_when_allow_live_orders_is_false(self) -> None:
        delegate = MagicMock()
        adapter = KisLiveOrderAdapter(delegate, settings=FakeSettings(allow_live_orders=False))

        with self.assertRaises(KisLiveOrderAdapterError):
            adapter.submit_cash_order(symbol="005930", side="buy", qty=1)

        delegate.submit_cash_order.assert_not_called()

    def test_cancel_blocks_when_profile_is_not_live(self) -> None:
        delegate = MagicMock()
        adapter = KisLiveOrderAdapter(delegate, settings=FakeSettings(), profile_mode="paper")

        with self.assertRaises(KisLiveOrderAdapterError):
            adapter.cancel_order(broker_order_no="order-1", broker_branch_no="01", order_qty=1, reason="test")

        delegate.cancel_order.assert_not_called()

    def test_cancel_does_not_require_allow_live_orders_for_protective_cancel(self) -> None:
        delegate = MagicMock()
        delegate.cancel_order.return_value = {"accepted": True}
        adapter = KisLiveOrderAdapter(delegate, settings=FakeSettings(allow_live_orders=False))

        result = adapter.cancel_order(
            broker_order_no="order-1",
            broker_branch_no="01",
            order_qty=1,
            reason="protective_cancel",
        )

        self.assertEqual(result, {"accepted": True})
        delegate.cancel_order.assert_called_once()

    def test_cancel_delegates_when_flags_are_enabled(self) -> None:
        delegate = create_autospec(KisRestQuoteClient, instance=True)
        delegate.cancel_order.return_value = {"accepted": True}
        adapter = KisLiveOrderAdapter(delegate, settings=FakeSettings())

        result = adapter.cancel_order(
            broker_order_no="order-1",
            broker_branch_no="01",
            order_qty=1,
            reason="test",
        )

        self.assertEqual(result, {"accepted": True})
        delegate.cancel_order.assert_called_once_with(
            broker_order_no="order-1",
            broker_branch_no="01",
            order_qty=1,
        )

    def test_describe_marks_adapter_as_guarded(self) -> None:
        delegate = MagicMock()
        delegate.describe.return_value = {"transport": "rest"}
        adapter = KisLiveOrderAdapter(delegate, settings=FakeSettings())

        self.assertEqual(
            adapter.describe(),
            {"transport": "rest", "access": "live-order-guarded", "profile_mode": "live"},
        )


if __name__ == "__main__":
    unittest.main()
