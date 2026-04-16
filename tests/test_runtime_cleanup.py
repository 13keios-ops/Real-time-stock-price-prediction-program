import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
