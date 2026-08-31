import json
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone

from app.brokers.kis_auth import KisApiError
from app.services.kis_orderability_probe import (
    build_orderability_dry_run,
    probe_kis_paper_orderability,
)


@dataclass
class FakeOrderabilitySnapshot:
    rt_cd: str = "0"
    message_code: str = "APBK0013"
    message: str = "조회 완료"
    orderable_cash: int = 100_000
    non_receivable_buy_amount: int = 100_000
    non_receivable_buy_qty: int = 1
    max_buy_amount: int = 100_000
    max_buy_qty: int = 1


class FakeReadOnlyClient:
    def __init__(
        self,
        snapshot: FakeOrderabilitySnapshot | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.snapshot = snapshot or FakeOrderabilitySnapshot()
        self.raises = raises
        self.calls = 0

    def get_orderability(self, **kwargs):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.snapshot


class KisOrderabilityProbeTests(unittest.TestCase):
    def test_dry_run_has_zero_network_and_order_calls(self) -> None:
        payload = build_orderability_dry_run(
            symbol="005930",
            order_price=70_000,
            product_code_present=True,
            product_code_length=2,
            product_code_is_domestic_stock_default=True,
        )

        self.assertEqual(payload["status"], "dry_run")
        self.assertFalse(payload["execution_started"])
        self.assertEqual(payload["safety"]["network_calls"], 0)
        self.assertEqual(payload["safety"]["order_calls"], 0)
        self.assertEqual(payload["safety"]["cancel_calls"], 0)

    def test_execute_uses_one_readonly_call_and_reports_positive_presence(self) -> None:
        client = FakeReadOnlyClient()

        payload = probe_kis_paper_orderability(
            client,
            symbol="005930",
            order_price=70_000,
            checked_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(payload["status"], "orderability_ok")
        self.assertTrue(payload["passed"])
        self.assertTrue(payload["response"]["transport_success"])
        self.assertTrue(payload["response"]["api_success"])
        self.assertEqual(
            payload["response"]["orderability_value_presence"], "positive"
        )
        self.assertEqual(payload["safety"]["network_calls"], 1)
        self.assertEqual(payload["safety"]["order_calls"], 0)
        self.assertEqual(payload["safety"]["cancel_calls"], 0)

    def test_zero_orderability_is_not_reported_as_api_failure(self) -> None:
        client = FakeReadOnlyClient(
            FakeOrderabilitySnapshot(
                orderable_cash=0,
                non_receivable_buy_amount=0,
                non_receivable_buy_qty=0,
                max_buy_amount=0,
                max_buy_qty=0,
            )
        )

        payload = probe_kis_paper_orderability(
            client,
            symbol="005930",
            order_price=70_000,
        )

        self.assertEqual(payload["status"], "orderability_zero")
        self.assertEqual(payload["evidence_health"], "valid_readonly_response")
        self.assertEqual(payload["response"]["orderability_value_presence"], "zero")

    def test_account_hard_rejection_is_classified(self) -> None:
        client = FakeReadOnlyClient(
            FakeOrderabilitySnapshot(
                rt_cd="1",
                message_code="APBK0919",
                message="모의투자 주문이 불가한 계좌입니다.",
            )
        )

        payload = probe_kis_paper_orderability(
            client,
            symbol="005930",
            order_price=70_000,
        )

        self.assertEqual(payload["status"], "account_not_orderable")
        self.assertTrue(payload["response"]["transport_success"])
        self.assertFalse(payload["response"]["api_success"])
        self.assertEqual(
            payload["cash_order_failure_taxonomy"],
            "broker_account_not_orderable",
        )

    def test_rate_limit_and_network_errors_are_distinct(self) -> None:
        rate_limited = FakeReadOnlyClient(
            FakeOrderabilitySnapshot(
                rt_cd="1",
                message_code="EGW00201",
                message="초당 거래건수를 초과하였습니다.",
            )
        )
        network = FakeReadOnlyClient(
            raises=KisApiError("KIS network error: timed out")
        )

        rate_payload = probe_kis_paper_orderability(
            rate_limited,
            symbol="005930",
            order_price=70_000,
        )
        network_payload = probe_kis_paper_orderability(
            network,
            symbol="005930",
            order_price=70_000,
        )

        self.assertEqual(rate_payload["status"], "rate_limited")
        self.assertEqual(network_payload["status"], "network_error")
        self.assertFalse(network_payload["response"]["transport_success"])
        self.assertFalse(network_payload["response"]["api_success"])

    def test_report_redacts_identifiers_secrets_and_exact_amounts(self) -> None:
        client = FakeReadOnlyClient(
            FakeOrderabilitySnapshot(
                message=(
                    "CANO=12345678 appkey=super-secret "
                    "authorization=Bearer-token"
                ),
                orderable_cash=987_654_321,
                non_receivable_buy_amount=987_654_321,
                non_receivable_buy_qty=12_345,
                max_buy_amount=987_654_321,
                max_buy_qty=12_345,
            )
        )

        payload = probe_kis_paper_orderability(
            client,
            symbol="005930",
            order_price=70_000,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertNotIn("12345678", encoded)
        self.assertNotIn("super-secret", encoded)
        self.assertNotIn("Bearer-token", encoded)
        self.assertNotIn("987654321", encoded)
        self.assertNotIn("12345", encoded)
        self.assertNotIn("ACNT_PRDT_CD\": \"01", encoded)


if __name__ == "__main__":
    unittest.main()
