import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.live_position_accounting import build_live_position_from_fills, build_live_positions_from_store
from app.storage.contracts import LiveFill
from app.storage.sqlite_store import SQLiteRuntimeStore


class LivePositionAccountingTests(unittest.TestCase):
    def _now(self) -> datetime:
        return datetime(2026, 5, 18, 1, 0, tzinfo=timezone.utc)

    def _tmp_root(self) -> Path:
        return Path(__file__).resolve().parents[1] / ".tmp-tests" / "live-position-accounting" / str(uuid.uuid4())

    def _fill(
        self,
        *,
        fill_id: str,
        side: str,
        qty: int,
        price: float,
        minutes: int = 0,
        commission: float = 0.0,
        tax: float = 0.0,
        fee: float = 0.0,
        symbol: str = "005930",
    ) -> LiveFill:
        return LiveFill(
            fill_id=fill_id,
            order_id=f"order-{fill_id}",
            broker_order_no=f"broker-{fill_id}",
            broker_branch_no="001",
            symbol=symbol,
            trading_day="2026-05-18",
            event_time=self._now().replace(minute=minutes),
            side=side,
            fill_qty=qty,
            fill_price=price,
            commission=commission,
            tax=tax,
            fee=fee,
            settlement_day="2026-05-20",
            detail_json={
                "raw_broker_fill": {},
                "fees": {"commission": commission, "tax": tax, "fee": fee},
                "settlement": {"settlement_day": "2026-05-20"},
            },
        )

    def test_build_live_position_from_fills_uses_long_only_weighted_average(self) -> None:
        result = build_live_position_from_fills(
            symbol="005930",
            trading_day="2026-05-18",
            fills=[
                self._fill(fill_id="1", side="buy", qty=3, price=100.0),
                self._fill(fill_id="2", side="buy", qty=2, price=110.0, minutes=1),
                self._fill(fill_id="3", side="sell", qty=4, price=120.0, minutes=2),
            ],
            last_price=130.0,
            updated_at=self._now(),
        )

        position = result.position
        self.assertEqual(position.qty, 1)
        self.assertAlmostEqual(position.avg_price, 104.0)
        self.assertAlmostEqual(position.cost_basis, 104.0)
        self.assertAlmostEqual(position.realized_pnl, 64.0)
        self.assertAlmostEqual(position.unrealized_pnl, 26.0)
        self.assertEqual(result.over_sell_qty, 0)

    def test_build_live_position_from_fills_includes_buy_and_sell_costs(self) -> None:
        result = build_live_position_from_fills(
            symbol="005930",
            trading_day="2026-05-18",
            fills=[
                self._fill(fill_id="1", side="buy", qty=2, price=100.0, commission=2.0),
                self._fill(fill_id="2", side="sell", qty=1, price=110.0, minutes=1, tax=1.0, fee=1.0),
            ],
            last_price=110.0,
            updated_at=self._now(),
        )

        position = result.position
        self.assertEqual(position.qty, 1)
        self.assertAlmostEqual(position.avg_price, 101.0)
        self.assertAlmostEqual(position.realized_pnl, 7.0)
        self.assertEqual(result.total_commission, 2.0)
        self.assertEqual(result.total_tax, 1.0)
        self.assertEqual(result.total_fee, 1.0)

    def test_build_live_position_from_fills_records_over_sell_qty(self) -> None:
        result = build_live_position_from_fills(
            symbol="005930",
            trading_day="2026-05-18",
            fills=[
                self._fill(fill_id="1", side="buy", qty=1, price=100.0),
                self._fill(fill_id="2", side="sell", qty=3, price=120.0, minutes=1),
            ],
            last_price=120.0,
            updated_at=self._now(),
        )

        self.assertEqual(result.position.qty, 0)
        self.assertEqual(result.position.cost_basis, 0.0)
        self.assertAlmostEqual(result.position.realized_pnl, 20.0)
        self.assertEqual(result.over_sell_qty, 2)
        self.assertEqual(result.position.detail_json["accounting"]["over_sell_qty"], 2)

    def test_build_live_position_from_fills_records_invalid_side_count(self) -> None:
        result = build_live_position_from_fills(
            symbol="005930",
            trading_day="2026-05-18",
            fills=[
                self._fill(fill_id="1", side="buy", qty=1, price=100.0),
                self._fill(fill_id="2", side="unknown", qty=1, price=120.0, minutes=1),
            ],
            last_price=120.0,
            updated_at=self._now(),
        )

        self.assertEqual(result.position.qty, 1)
        self.assertEqual(result.invalid_side_count, 1)
        self.assertEqual(result.position.detail_json["accounting"]["invalid_side_count"], 1)

    def test_build_live_positions_from_store_groups_by_symbol(self) -> None:
        store = SQLiteRuntimeStore(self._tmp_root() / "dev.db")
        store.insert_live_fill(self._fill(fill_id="1", side="buy", qty=1, price=100.0, symbol="005930"))
        store.insert_live_fill(self._fill(fill_id="2", side="buy", qty=2, price=200.0, symbol="000660"))

        results = build_live_positions_from_store(
            store,
            trading_day="2026-05-18",
            last_prices={"005930": 110.0, "000660": 210.0},
            updated_at=self._now(),
            broker_quantities={"005930": 1, "000660": 1},
        )

        self.assertEqual([result.position.symbol for result in results], ["000660", "005930"])
        self.assertEqual(results[0].position.qty, 2)
        self.assertTrue(results[0].position.detail_json["accounting"]["broker_qty_mismatch"])
        self.assertEqual(results[1].position.qty, 1)


if __name__ == "__main__":
    unittest.main()
