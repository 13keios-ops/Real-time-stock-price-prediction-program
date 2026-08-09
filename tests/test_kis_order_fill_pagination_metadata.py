import unittest
from unittest.mock import MagicMock

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
    def _client(self) -> KisRestQuoteClient:
        profile = MagicMock()
        profile.mode = "paper"
        profile.is_configured = True
        return KisRestQuoteClient(profile=profile, token_manager=MagicMock())

    def test_complete_pagination_is_reported_without_identifiers(self) -> None:
        client = self._client()
        client._request_response = MagicMock(
            side_effect=[
                (_payload(order_no="100", continuation=True), {"tr_cont": "M"}),
                (_payload(order_no="101", continuation=False), {"tr_cont": ""}),
            ]
        )

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
