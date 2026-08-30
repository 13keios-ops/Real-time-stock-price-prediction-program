import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import Mock, patch

from app.brokers.kis_auth import KisApiError
from app.brokers.kis_quote_rest import KisCashOrderResult
from app.config.settings import load_settings
from app.services.broker_paper import (
    BROKER_ACCOUNT_HARD_REJECTION_COOLDOWN_SECONDS,
    BROKER_ACCOUNT_NOT_ORDERABLE_MESSAGE,
    BrokerPaperMirror,
    BrokerPaperSubmissionError,
    classify_broker_paper_failure,
    sanitize_broker_error_text,
)
from app.storage.contracts import PaperOrder
from app.utils.time import now_local


class BrokerPaperFailureGuardTests(unittest.TestCase):
    def _build_mirror(self) -> BrokerPaperMirror:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "broker-paper-failure-guard" / str(uuid.uuid4())
        settings = load_settings(
            project_root=root,
            env={
                "RUNTIME_DATA_DIR": str(runtime_root),
                "DATABASE_URL": f"sqlite:///{runtime_root / 'test.db'}",
                "TRADING_MODE": "paper",
                "ENABLE_BROKER_PAPER_MIRRORING": "true",
                "KIS_APP_KEY_PAPER": "paper-key",
                "KIS_APP_SECRET_PAPER": "paper-secret",
                "KIS_ACCOUNT_NO_PAPER": "12345678",
                "KIS_PRODUCT_CODE_PAPER": "01",
            },
        )
        mirror = BrokerPaperMirror(settings)
        mirror.client = Mock()
        return mirror

    @staticmethod
    def _order(order_id: str = "paper-order-test-000001") -> PaperOrder:
        return PaperOrder(
            order_id=order_id,
            symbol="005930",
            event_time=now_local("Asia/Seoul"),
            side="buy",
            qty=3,
            limit_price=70000.0,
            status="created",
            prediction_id="prediction-test-1",
            signal_id="signal-test-1",
            target_id="target-test-1",
        )

    @staticmethod
    def _success() -> KisCashOrderResult:
        return KisCashOrderResult(
            mode="paper",
            side="buy",
            symbol="005930",
            qty=3,
            order_type="00",
            limit_price=70000.0,
            broker_order_no="broker-order-test",
            broker_branch_no="broker-branch-test",
            order_time="101530",
            message_code="APBK0013",
            message="submitted",
            raw_output={"ODNO": "broker-order-test"},
        )

    def test_account_hard_rejection_opens_circuit_and_blocks_repeated_network_call(self) -> None:
        mirror = self._build_mirror()
        mirror.client.submit_cash_order.side_effect = KisApiError(
            f"KIS REST quote error: {BROKER_ACCOUNT_NOT_ORDERABLE_MESSAGE}"
        )
        with patch("app.services.broker_paper.time.monotonic", return_value=100.0):
            with self.assertRaises(BrokerPaperSubmissionError) as first:
                mirror.submit_local_order(self._order(), decision_id="decision-test-1")
            with self.assertRaises(BrokerPaperSubmissionError) as second:
                mirror.submit_local_order(self._order("paper-order-test-000002"), decision_id="decision-test-2")

        self.assertEqual(mirror.client.submit_cash_order.call_count, 1)
        self.assertEqual(first.exception.failure.category, "broker_account_not_orderable")
        self.assertTrue(first.exception.failure.network_attempted)
        self.assertTrue(first.exception.failure.circuit_opened)
        self.assertEqual(
            first.exception.failure.retry_after_seconds,
            BROKER_ACCOUNT_HARD_REJECTION_COOLDOWN_SECONDS,
        )
        self.assertEqual(second.exception.failure.category, "broker_account_not_orderable")
        self.assertFalse(second.exception.failure.network_attempted)
        self.assertTrue(second.exception.failure.circuit_opened)

    def test_rate_limit_does_not_open_account_circuit(self) -> None:
        mirror = self._build_mirror()
        mirror.client.submit_cash_order.side_effect = [
            KisApiError(
                'KIS HTTP error 500: {"rt_cd":"1","msg_cd":"EGW00201",'
                '"msg1":"requests per second exceeded"}'
            ),
            self._success(),
        ]

        with self.assertRaises(BrokerPaperSubmissionError) as first:
            mirror.submit_local_order(self._order())
        submission = mirror.submit_local_order(self._order("paper-order-test-000002"))

        self.assertEqual(first.exception.failure.category, "broker_rate_limited")
        self.assertFalse(first.exception.failure.circuit_opened)
        self.assertEqual(mirror.client.submit_cash_order.call_count, 2)
        self.assertEqual(submission.status, "submitted")

    def test_transient_network_error_does_not_open_account_circuit(self) -> None:
        mirror = self._build_mirror()
        mirror.client.submit_cash_order.side_effect = [
            KisApiError("KIS network error: connection reset"),
            self._success(),
        ]

        with self.assertRaises(BrokerPaperSubmissionError) as first:
            mirror.submit_local_order(self._order())
        submission = mirror.submit_local_order(self._order("paper-order-test-000002"))

        self.assertEqual(first.exception.failure.category, "broker_network_error")
        self.assertFalse(first.exception.failure.circuit_opened)
        self.assertEqual(mirror.client.submit_cash_order.call_count, 2)
        self.assertEqual(submission.status, "submitted")

    def test_circuit_expires_and_allows_one_probe(self) -> None:
        mirror = self._build_mirror()
        mirror.client.submit_cash_order.side_effect = [
            KisApiError(f"KIS REST quote error: {BROKER_ACCOUNT_NOT_ORDERABLE_MESSAGE}"),
            self._success(),
        ]
        with patch(
            "app.services.broker_paper.time.monotonic",
            side_effect=[100.0, 100.0 + BROKER_ACCOUNT_HARD_REJECTION_COOLDOWN_SECONDS],
        ):
            with self.assertRaises(BrokerPaperSubmissionError):
                mirror.submit_local_order(self._order())
            submission = mirror.submit_local_order(self._order("paper-order-test-000002"))

        self.assertEqual(mirror.client.submit_cash_order.call_count, 2)
        self.assertEqual(submission.status, "submitted")

    def test_circuit_can_be_reset_explicitly(self) -> None:
        mirror = self._build_mirror()
        mirror.client.submit_cash_order.side_effect = [
            KisApiError(f"KIS REST quote error: {BROKER_ACCOUNT_NOT_ORDERABLE_MESSAGE}"),
            self._success(),
        ]
        with patch("app.services.broker_paper.time.monotonic", return_value=100.0):
            with self.assertRaises(BrokerPaperSubmissionError):
                mirror.submit_local_order(self._order())
            mirror.reset_account_hard_rejection_circuit()
            submission = mirror.submit_local_order(self._order("paper-order-test-000002"))

        self.assertEqual(mirror.client.submit_cash_order.call_count, 2)
        self.assertEqual(submission.status, "submitted")

    def test_success_records_stable_lineage_and_sanitized_request_shape(self) -> None:
        mirror = self._build_mirror()
        mirror.client.submit_cash_order.return_value = self._success()
        order = self._order()

        submission = mirror.submit_local_order(order, decision_id="decision-test-1")

        self.assertEqual(submission.detail["attempt_id"], f"broker-paper-attempt-{order.order_id}")
        self.assertEqual(submission.detail["decision_id"], "decision-test-1")
        self.assertEqual(submission.detail["prediction_id"], order.prediction_id)
        self.assertEqual(submission.detail["signal_id"], order.signal_id)
        self.assertEqual(submission.detail["target_id"], order.target_id)
        request = submission.detail["request"]
        self.assertEqual(request["tr_id"], "VTTC0012U")
        self.assertEqual(
            request["body"],
            {
                "PDNO": "005930",
                "ORD_DVSN": "00",
                "ORD_QTY": "3",
                "ORD_UNPR": "70000",
                "EXCG_ID_DVSN_CD": "KRX",
                "SLL_TYPE": "",
                "CNDT_PRIC": "",
            },
        )
        serialized = json.dumps(request, sort_keys=True)
        self.assertNotIn("12345678", serialized)
        self.assertNotIn("paper-key", serialized)
        self.assertNotIn("paper-secret", serialized)

    def test_error_redaction_removes_secret_fields_and_account_identifiers(self) -> None:
        unsafe = (
            'appkey="sensitive-key"; appsecret=sensitive-secret; '
            'authorization=Bearer-secret; CANO="12345678"; token=secret-token'
        )

        sanitized = sanitize_broker_error_text(unsafe)

        self.assertNotIn("sensitive-key", sanitized)
        self.assertNotIn("sensitive-secret", sanitized)
        self.assertNotIn("Bearer-secret", sanitized)
        self.assertNotIn("12345678", sanitized)
        self.assertNotIn("secret-token", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_failure_taxonomy_keeps_invalid_order_auth_rejection_and_unknown_distinct(self) -> None:
        cases = {
            "broker_auth_error": KisApiError("KIS HTTP error 401: EGW00123 token expired"),
            "broker_invalid_request": KisApiError("Order quantity must be positive."),
            "broker_order_rejected": KisApiError("broker order rejected for this symbol"),
            "broker_unknown_error": KisApiError("unexpected broker response"),
        }

        for category, exc in cases.items():
            with self.subTest(category=category):
                failure = classify_broker_paper_failure(exc, network_attempted=True)
                self.assertEqual(failure.category, category)


if __name__ == "__main__":
    unittest.main()
