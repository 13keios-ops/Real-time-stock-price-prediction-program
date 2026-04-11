import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.services.synthetic import seed_synthetic_intraday_data
from app.storage.runtime_writer import get_sqlite_store


class SyntheticSeedTests(unittest.TestCase):
    def test_seed_synthetic_data_writes_ticks_and_orderbooks(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "synthetic" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            result = seed_synthetic_intraday_data(project_root=root, symbol="005930", minutes=10)
            sqlite_store = get_sqlite_store(settings)

            self.assertEqual(result.minutes_seeded, 10)
            self.assertIsNotNone(sqlite_store)
            self.assertEqual(sqlite_store.count_rows("raw_market_ticks"), 10)
            self.assertEqual(sqlite_store.count_rows("raw_orderbook_ticks"), 10)


if __name__ == "__main__":
    unittest.main()
