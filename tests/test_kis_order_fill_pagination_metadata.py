import unittest
from unittest.mock import MagicMock, patch

from app.brokers.kis_auth import KisApiError
from app.brokers.kis_quote_rest import KisRestQuoteClient


def _payload(*, order_no: str, continuation: bool) -> dict:
    return {
        "rt_cd": "0",
        "output1": [
            {
                "ord_dt": "20260615",
                "ord_gno_brno": "001",
                "odno": order_no,
                "pdno": "005930",
                "sll_buy_dvsn_cd": "02",
                "ord_qty": "1",
                "tot_ccld_qty": "1",
                "rmn_qty": "0",
            }
        ],
        "ctx_area_fk100": "next" if continuation else "",
        "ctx_area_nk100": "next" if continuation else "",
    }


class KisOrderFillPaginationMetadataTests(unittest.TestCase):
    def _client(self, *, mode: str = "paper") -> KisRestQuoteClient:
        profile = MagicMock()
        profile.mode = mode
        profile.is_configured = True
        return KisRestQuoteClient(profile=profile, token_manager=MagicMock())

    def test_first_paper_page_does_not_sleep(self) -> None:
        client = self._client()
        client._request_response = MagicMock(
            return_value=(_payload(order_no="100", continuation=False), {"tr_cont": ""})
        )

        with patch("time.sleep") as mocked_sleep:
            rows = client.get_daily_order_fills(
                start_date="20260614",
                end_date="20260807",
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(client._request_response.call_count, 1)
        self.assertEqual(client.last_daily_order_fill_query.get("http_requests_attempted"), 1)
        mocked_sleep.assert_not_called()

    def test_paper_continuation_waits_before_second_page(self) -> None:
        client = self._client()
        clock = [100.0]
        events: list[object] = []
        responses = iter(
            [
                (_payload(order_no="100", continuation=True), {"tr_cont": "M"}),
                (_payload(order_no="101", continuation=False), {"tr_cont": ""}),
            ]
        )

        def request_page(*args, **kwargs):
            events.append("request_start")
            clock[0] += 0.2
            response = next(responses)
            events.append("response_complete")
            return response

        def sleep(seconds: float) -> None:
            events.append(("sleep", seconds))
            clock[0] += seconds

        client._request_response = MagicMock(side_effect=request_page)
        with patch("app.brokers.kis_quote_rest.time.monotonic", side_effect=lambda: clock[0]):
            with patch("app.brokers.kis_quote_rest.time.sleep", side_effect=sleep):
                rows = client.get_daily_order_fills(
                    start_date="20260614",
                    end_date="20260807",
                )

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            events,
            [
                "request_start",
                "response_complete",
                ("sleep", 0.5),
                "request_start",
                "response_complete",
            ],
        )

    def test_three_page_paper_query_paces_each_continuation(self) -> None:
        client = self._client()
        clock = [100.0]
        events: list[object] = []
        responses = iter(
            [
                (_payload(order_no="100", continuation=True), {"tr_cont": "M"}),
                (_payload(order_no="101", continuation=True), {"tr_cont": "M"}),
                (_payload(order_no="102", continuation=False), {"tr_cont": ""}),
            ]
        )

        def request_page(*args, **kwargs):
            events.append("request_start")
            clock[0] += 0.2
            response = next(responses)
            events.append("response_complete")
            return response

        def sleep(seconds: float) -> None:
            events.append(("sleep", seconds))
            clock[0] += seconds

        client._request_response = MagicMock(side_effect=request_page)
        with patch("app.brokers.kis_quote_rest.time.monotonic", side_effect=lambda: clock[0]):
            with patch("app.brokers.kis_quote_rest.time.sleep", side_effect=sleep):
                rows = client.get_daily_order_fills(
                    start_date="20260614",
                    end_date="20260807",
                )

        self.assertEqual([row.broker_order_no for row in rows], ["100", "101", "102"])
        self.assertEqual(
            events,
            [
                "request_start",
                "response_complete",
                ("sleep", 0.5),
                "request_start",
                "response_complete",
                ("sleep", 0.5),
                "request_start",
                "response_complete",
            ],
        )

    def test_live_continuation_does_not_use_paper_pacing(self) -> None:
        client = self._client(mode="live")
        client._request_response = MagicMock(
            side_effect=[
                (_payload(order_no="100", continuation=True), {"tr_cont": "M"}),
                (_payload(order_no="101", continuation=False), {"tr_cont": ""}),
            ]
        )

        with patch("time.sleep") as mocked_sleep:
            rows = client.get_daily_order_fills(
                start_date="20260614",
                end_date="20260807",
            )

        self.assertEqual(len(rows), 2)
        mocked_sleep.assert_not_called()

    def test_second_page_rate_limit_preserves_first_page_metadata(self) -> None:
        client = self._client()
        client._request_response = MagicMock(
            side_effect=[
                (_payload(order_no="100", continuation=True), {"tr_cont": "M"}),
                KisApiError("KIS REST quote error: EGW00201 rate limit"),
            ]
        )

        with patch("time.monotonic", return_value=100.0):
            with patch("time.sleep"):
                with self.assertRaises(KisApiError):
                    client.get_daily_order_fills(
                        start_date="20260614",
                        end_date="20260807",
                    )

        metadata = client.last_daily_order_fill_query
        self.assertEqual(metadata.get("http_requests_attempted"), 2)
        self.assertEqual(metadata["pages_fetched"], 1)
        self.assertEqual(metadata.get("pages_fetched_before_error"), 1)
        self.assertEqual(metadata.get("failed_page"), 2)
        self.assertFalse(metadata["pagination_complete"])
        self.assertTrue(metadata.get("pagination_interrupted_by_rate_limit"))
        self.assertEqual(metadata["records_returned"], 1)
        self.assertNotIn("100", str(metadata))

    def test_first_page_rate_limit_records_failed_page_one(self) -> None:
        client = self._client()
        client._request_response = MagicMock(
            side_effect=KisApiError("KIS REST quote error: EGW00201 rate limit")
        )

        with self.assertRaises(KisApiError):
            client.get_daily_order_fills(
                start_date="20260614",
                end_date="20260807",
            )

        metadata = client.last_daily_order_fill_query
        self.assertEqual(metadata.get("http_requests_attempted"), 1)
        self.assertEqual(metadata["pages_fetched"], 0)
        self.assertEqual(metadata.get("pages_fetched_before_error"), 0)
        self.assertEqual(metadata.get("failed_page"), 1)
        self.assertFalse(metadata["pagination_complete"])
        self.assertTrue(metadata.get("pagination_interrupted_by_rate_limit"))

    def test_third_page_rate_limit_preserves_two_completed_pages(self) -> None:
        client = self._client()
        client._request_response = MagicMock(
            side_effect=[
                (_payload(order_no="100", continuation=True), {"tr_cont": "M"}),
                (_payload(order_no="101", continuation=True), {"tr_cont": "M"}),
                KisApiError("KIS REST quote error: EGW00201 rate limit"),
            ]
        )

        with patch("app.brokers.kis_quote_rest.time.monotonic", return_value=100.0):
            with patch("app.brokers.kis_quote_rest.time.sleep"):
                with self.assertRaises(KisApiError):
                    client.get_daily_order_fills(
                        start_date="20260614",
                        end_date="20260807",
                    )

        metadata = client.last_daily_order_fill_query
        self.assertEqual(metadata.get("http_requests_attempted"), 3)
        self.assertEqual(metadata["pages_fetched"], 2)
        self.assertEqual(metadata.get("pages_fetched_before_error"), 2)
        self.assertEqual(metadata.get("failed_page"), 3)
        self.assertEqual(metadata["records_returned"], 2)
        self.assertFalse(metadata["pagination_complete"])
        self.assertTrue(metadata.get("pagination_interrupted_by_rate_limit"))

    def test_successful_three_page_query_records_complete_metadata(self) -> None:
        client = self._client()
        client._request_response = MagicMock(
            side_effect=[
                (_payload(order_no="100", continuation=True), {"tr_cont": "M"}),
                (_payload(order_no="101", continuation=True), {"tr_cont": "M"}),
                (_payload(order_no="102", continuation=False), {"tr_cont": ""}),
            ]
        )

        with patch("time.monotonic", return_value=100.0):
            with patch("time.sleep"):
                rows = client.get_daily_order_fills(
                    start_date="20260614",
                    end_date="20260807",
                )

        self.assertEqual(len(rows), 3)
        metadata = client.last_daily_order_fill_query
        self.assertEqual(metadata.get("http_requests_attempted"), 3)
        self.assertEqual(metadata["pages_fetched"], 3)
        self.assertEqual(metadata["records_returned"], 3)
        self.assertTrue(metadata["pagination_complete"])
        self.assertIsNone(metadata.get("failed_page"))
        self.assertFalse(metadata.get("pagination_interrupted_by_rate_limit"))

    def test_complete_pagination_is_reported_without_identifiers(self) -> None:
        client = self._client()
        client._request_response = MagicMock(
            side_effect=[
                (_payload(order_no="100", continuation=True), {"tr_cont": "M"}),
                (_payload(order_no="101", continuation=False), {"tr_cont": ""}),
            ]
        )

        with patch("app.brokers.kis_quote_rest.time.sleep"):
            rows = client.get_daily_order_fills(
                start_date="20260614",
                end_date="20260807",
                max_pages=10,
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(client.last_daily_order_fill_query["pages_fetched"], 2)
        self.assertEqual(client.last_daily_order_fill_query["records_returned"], 2)
        self.assertTrue(client.last_daily_order_fill_query["pagination_complete"])
        self.assertFalse(client.last_daily_order_fill_query["page_limit_reached"])
        self.assertNotIn("100", str(client.last_daily_order_fill_query))

    def test_page_limit_is_fail_closed(self) -> None:
        client = self._client()
        client._request_response = MagicMock(
            return_value=(_payload(order_no="100", continuation=True), {"tr_cont": "M"})
        )

        rows = client.get_daily_order_fills(
            start_date="20260614",
            end_date="20260807",
            max_pages=1,
        )

        self.assertEqual(len(rows), 1)
        self.assertFalse(client.last_daily_order_fill_query["pagination_complete"])
        self.assertTrue(client.last_daily_order_fill_query["page_limit_reached"])


if __name__ == "__main__":
    unittest.main()
