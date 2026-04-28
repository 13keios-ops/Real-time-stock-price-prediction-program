import os
from datetime import datetime
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.storage.contracts import Fill, MarketTickEvent, PaperOrder, PortfolioSnapshot
from app.storage.runtime_writer import RuntimeWriter
from app.services.runtime import run_demo_pipeline
from app.services.runtime_cleanup import cleanup_non_actual_runtime_rows
from app.services.streaming import build_sample_ws_frames, replay_ws_frames
from app.storage.runtime_writer import get_sqlite_store
from app.config.settings import load_settings


class RuntimeCleanupTests(unittest.TestCase):
    def test_cleanup_removes_demo_runtime_rows(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "runtime-cleanup" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }
        with patch.dict(os.environ, env, clear=False):
            run_demo_pipeline(project_root=root, symbol="005930")
            result = cleanup_non_actual_runtime_rows(project_root=root)
            settings = load_settings(project_root=root)
            sqlite_store = get_sqlite_store(settings)

        self.assertIsNotNone(sqlite_store)
        self.assertGreater(result.deleted_rows["raw_market_ticks"], 0)
        self.assertGreater(result.deleted_rows["raw_orderbook_ticks"], 0)
        self.assertGreater(result.deleted_rows["serving_predictions"], 0)
        self.assertGreater(result.deleted_rows["paper_orders"], 0)
        self.assertEqual(sqlite_store.count_rows("raw_market_ticks"), 0)
        self.assertEqual(sqlite_store.count_rows("raw_orderbook_ticks"), 0)
        self.assertEqual(sqlite_store.count_rows("serving_predictions"), 0)
        self.assertEqual(sqlite_store.count_rows("paper_orders"), 0)
        self.assertEqual(sqlite_store.count_rows("paper_portfolio_snapshots"), 0)

    def test_cleanup_removes_replay_runtime_rows(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "runtime-cleanup-replay" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }
        with patch.dict(os.environ, env, clear=False):
            replay_ws_frames(project_root=root, frames=build_sample_ws_frames("005930"))
            result = cleanup_non_actual_runtime_rows(project_root=root)
            settings = load_settings(project_root=root)
            sqlite_store = get_sqlite_store(settings)

        self.assertIsNotNone(sqlite_store)
        self.assertGreater(result.deleted_rows["raw_market_ticks"], 0)
        self.assertGreater(result.deleted_rows["raw_orderbook_ticks"], 0)
        self.assertGreater(result.deleted_rows["serving_predictions"], 0)
        self.assertGreater(result.deleted_rows["paper_orders"], 0)
        self.assertEqual(sqlite_store.count_rows("raw_market_ticks"), 0)
        self.assertEqual(sqlite_store.count_rows("raw_orderbook_ticks"), 0)
        self.assertEqual(sqlite_store.count_rows("serving_predictions"), 0)
        self.assertEqual(sqlite_store.count_rows("paper_orders"), 0)

    def test_cleanup_keeps_actual_snapshot_written_at_fill_minute(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "runtime-cleanup-actual-fill" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            writer = RuntimeWriter.from_settings(settings)
            order_time = datetime.fromisoformat("2026-04-17T09:30:00+09:00")
            fill_time = datetime.fromisoformat("2026-04-17T09:31:00+09:00")
            writer.write_market_tick(
                MarketTickEvent(
                    symbol="005930",
                    event_time=order_time,
                    price=70000.0,
                    volume=100,
                    source="kis-ws",
                )
            )
            writer.write_paper_order(
                PaperOrder(
                    order_id="paper-order-actual-001",
                    symbol="005930",
                    event_time=order_time,
                    side="buy",
                    qty=3,
                    limit_price=70000.0,
                    status="filled",
                )
            )
            writer.write_fill(
                Fill(
                    fill_id="fill-actual-001",
                    order_id="paper-order-actual-001",
                    event_time=fill_time,
                    fill_price=70000.0,
                    fill_qty=3,
                    commission=100.0,
                    tax=50.0,
                )
            )
            writer.write_portfolio_snapshot(
                PortfolioSnapshot(
                    snapshot_id="portfolio-actual-fill-001",
                    event_time=fill_time,
                    cash_balance=789850.0,
                    gross_market_value=214500.0,
                    net_liquidation_value=1004350.0,
                    open_positions=1,
                    realized_pnl=0.0,
                    unrealized_pnl=4350.0,
                )
            )
            result = cleanup_non_actual_runtime_rows(project_root=root)
            sqlite_store = get_sqlite_store(settings)

        self.assertIsNotNone(sqlite_store)
        self.assertEqual(result.deleted_rows["paper_portfolio_snapshots"], 0)
        self.assertEqual(sqlite_store.count_rows("paper_orders"), 1)
        self.assertEqual(sqlite_store.count_rows("paper_fills"), 1)
        self.assertEqual(sqlite_store.count_rows("paper_portfolio_snapshots"), 1)


if __name__ == "__main__":
    unittest.main()
