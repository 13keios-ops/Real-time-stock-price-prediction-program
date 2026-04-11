from datetime import datetime
import unittest

from app.paper_trading.book import PaperPortfolioBook
from app.storage.contracts import Fill
from app.utils.time import get_timezone


class PaperBookTests(unittest.TestCase):
    def test_apply_buy_fill_updates_position_and_cash(self) -> None:
        kst = get_timezone("Asia/Seoul")
        book = PaperPortfolioBook(initial_cash=1_000_000, max_open_positions=3)
        fill = Fill(
            fill_id="fill-1",
            order_id="order-1",
            event_time=datetime(2026, 4, 11, 9, 15, tzinfo=kst),
            fill_price=10000,
            fill_qty=10,
            commission=15,
            tax=18,
        )

        state = book.apply_buy_fill(symbol="005930", fill=fill, fill_price=10000)

        self.assertEqual(state.qty, 10)
        self.assertGreater(state.avg_price, 10000)
        self.assertLess(book.cash_balance, 1_000_000)
        snapshot = book.to_portfolio_snapshot("snap-1", fill.event_time)
        self.assertEqual(snapshot.open_positions, 1)
        self.assertGreater(snapshot.gross_market_value, 0)

    def test_can_open_blocks_existing_symbol(self) -> None:
        kst = get_timezone("Asia/Seoul")
        book = PaperPortfolioBook(initial_cash=1_000_000, max_open_positions=1)
        fill = Fill(
            fill_id="fill-1",
            order_id="order-1",
            event_time=datetime(2026, 4, 11, 9, 15, tzinfo=kst),
            fill_price=10000,
            fill_qty=10,
            commission=0,
            tax=0,
        )
        book.apply_buy_fill(symbol="005930", fill=fill, fill_price=10000)

        allowed, reason = book.can_open("005930")
        self.assertFalse(allowed)
        self.assertEqual(reason, "position_already_open")


if __name__ == "__main__":
    unittest.main()
