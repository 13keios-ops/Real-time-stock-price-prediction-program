import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.services.orchestrator import run_synthetic_dev_cycle


class OrchestratorTests(unittest.TestCase):
    def test_run_synthetic_dev_cycle(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "orchestrator" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }
        with patch.dict(os.environ, env, clear=False):
            result = run_synthetic_dev_cycle(
                project_root=root,
                symbol="005930",
                minutes=70,
                train_horizon_min=15,
            )
            self.assertEqual(result.mode, "synthetic")
            self.assertIsNotNone(result.collection)
            self.assertGreater(result.minute_bars["bars_written"], 0)
            self.assertIsNotNone(result.training)
            self.assertIsNotNone(result.backtest)
            self.assertGreaterEqual(result.backtest["rows_evaluated"], 1)
            self.assertIsNotNone(result.walk_forward)
            self.assertGreaterEqual(result.walk_forward["folds"], 1)
            self.assertIsNotNone(result.challengers)
            self.assertGreaterEqual(len(result.challengers["candidates"]), 3)


if __name__ == "__main__":
    unittest.main()
