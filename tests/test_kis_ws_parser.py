import unittest

from app.brokers.kis_quote_ws import (
    DOMESTIC_ORDERBOOK_COLUMNS,
    DOMESTIC_ORDERBOOK_TR_ID,
    DOMESTIC_TRADE_COLUMNS,
    DOMESTIC_TRADE_TR_ID,
    parse_kis_ws_frame,
)
from app.collectors.market_data import market_tick_from_kis_ws_record, orderbook_from_kis_ws_record
from app.utils.time import now_local


class KisWebSocketParserTests(unittest.TestCase):
    def test_parse_trade_frame(self) -> None:
        values = [""] * len(DOMESTIC_TRADE_COLUMNS)
        index = {name: position for position, name in enumerate(DOMESTIC_TRADE_COLUMNS)}
        values[index["MKSC_SHRN_ISCD"]] = "005930"
        values[index["STCK_PRPR"]] = "70200"
        values[index["CNTG_VOL"]] = "12"
        values[index["ASKP1"]] = "70200"
        values[index["BIDP1"]] = "70100"
        frame = f"0|{DOMESTIC_TRADE_TR_ID}|1|{'^'.join(values)}"

        parsed = parse_kis_ws_frame(frame)

        self.assertEqual(parsed["tr_id"], DOMESTIC_TRADE_TR_ID)
        self.assertEqual(parsed["record_count"], 1)
        self.assertEqual(parsed["records"][0]["MKSC_SHRN_ISCD"], "005930")
        self.assertEqual(parsed["records"][0]["STCK_PRPR"], "70200")

    def test_parse_orderbook_frame_and_convert(self) -> None:
        values = [""] * len(DOMESTIC_ORDERBOOK_COLUMNS)
        index = {name: position for position, name in enumerate(DOMESTIC_ORDERBOOK_COLUMNS)}
        values[index["MKSC_SHRN_ISCD"]] = "005930"
        values[index["ASKP1"]] = "70200"
        values[index["BIDP1"]] = "70100"
        values[index["ASKP_RSQN1"]] = "100"
        values[index["BIDP_RSQN1"]] = "150"
        frame = f"0|{DOMESTIC_ORDERBOOK_TR_ID}|1|{'^'.join(values)}"

        parsed = parse_kis_ws_frame(frame)
        event_time = now_local("Asia/Seoul")
        orderbook = orderbook_from_kis_ws_record(parsed["records"][0], event_time=event_time)

        self.assertEqual(orderbook.symbol, "005930")
        self.assertEqual(orderbook.ask_price, 70200.0)
        self.assertEqual(orderbook.bid_size, 150)

    def test_convert_trade_record_to_tick(self) -> None:
        event_time = now_local("Asia/Seoul")
        tick = market_tick_from_kis_ws_record(
            {
                "MKSC_SHRN_ISCD": "005930",
                "STCK_PRPR": "70200",
                "CNTG_VOL": "25",
            },
            event_time=event_time,
        )
        self.assertEqual(tick.symbol, "005930")
        self.assertEqual(tick.price, 70200.0)
        self.assertEqual(tick.volume, 25)

    def test_parse_json_control_frame(self) -> None:
        parsed = parse_kis_ws_frame('{"header":{"tr_id":"PINGPONG"},"body":{"rt_cd":"0"}}')

        self.assertEqual(parsed["header"]["tr_id"], "PINGPONG")
        self.assertEqual(parsed["body"]["rt_cd"], "0")


if __name__ == "__main__":
    unittest.main()
