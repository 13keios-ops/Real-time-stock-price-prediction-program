from __future__ import annotations

import math
import unittest

from app.brokers.kis_quote_rest import (
    KRX_INSTRUMENT_COMMON_STOCK,
    KRX_INSTRUMENT_ETF_ETN,
    krx_tick_size,
    normalize_krx_limit_price,
)


class KrxOrderPriceTests(unittest.TestCase):
    def test_common_stock_tick_boundaries_and_directional_normalization(self) -> None:
        cases = (
            (1999, 1, 1999, 1999),
            (2000, 5, 2000, 2000),
            (2001, 5, 2000, 2005),
            (4999, 5, 4995, 5000),
            (5000, 10, 5000, 5000),
            (5001, 10, 5000, 5010),
            (19999, 10, 19990, 20000),
            (20000, 50, 20000, 20000),
            (20001, 50, 20000, 20050),
            (49999, 50, 49950, 50000),
            (50000, 100, 50000, 50000),
            (50001, 100, 50000, 50100),
            (199999, 100, 199900, 200000),
            (200000, 500, 200000, 200000),
            (200001, 500, 200000, 200500),
            (499999, 500, 499500, 500000),
            (500000, 1000, 500000, 500000),
            (500001, 1000, 500000, 501000),
        )

        for raw_price, expected_tick, expected_buy, expected_sell in cases:
            with self.subTest(raw_price=raw_price):
                self.assertEqual(
                    krx_tick_size(
                        raw_price,
                        instrument_type=KRX_INSTRUMENT_COMMON_STOCK,
                    ),
                    expected_tick,
                )
                self.assertEqual(
                    normalize_krx_limit_price(
                        raw_price,
                        side="buy",
                        instrument_type=KRX_INSTRUMENT_COMMON_STOCK,
                    ),
                    expected_buy,
                )
                self.assertEqual(
                    normalize_krx_limit_price(
                        raw_price,
                        side="sell",
                        instrument_type=KRX_INSTRUMENT_COMMON_STOCK,
                    ),
                    expected_sell,
                )

    def test_etf_etn_requires_explicit_type_and_uses_its_own_tick_table(self) -> None:
        self.assertEqual(krx_tick_size(1999, instrument_type=KRX_INSTRUMENT_ETF_ETN), 1)
        self.assertEqual(krx_tick_size(2000, instrument_type=KRX_INSTRUMENT_ETF_ETN), 5)
        self.assertEqual(
            normalize_krx_limit_price(
                2001,
                side="sell",
                instrument_type=KRX_INSTRUMENT_ETF_ETN,
            ),
            2005,
        )

    def test_invalid_values_side_and_instrument_type_fail_before_submission(self) -> None:
        for value in (0, -1, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    krx_tick_size(value, instrument_type=KRX_INSTRUMENT_COMMON_STOCK)
        with self.assertRaises(ValueError):
            normalize_krx_limit_price(
                70000,
                side="hold",
                instrument_type=KRX_INSTRUMENT_COMMON_STOCK,
            )
        with self.assertRaises(ValueError):
            krx_tick_size(70000, instrument_type="inferred-from-symbol")


if __name__ == "__main__":
    unittest.main()
