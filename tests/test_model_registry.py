import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.models.loader import load_prediction_model
from app.models.registry import ModelRegistry, ModelRegistryEntry
from app.services.orchestrator import run_synthetic_dev_cycle
from app.services.research import set_builtin_model_active
from app.storage.contracts import FeatureSnapshot
from app.utils.time import now_local


class ModelRegistryTests(unittest.TestCase):
    def test_training_keeps_registry_explicit_and_loader_falls_back_to_baseline(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "registry" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }

        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            registry = ModelRegistry(runtime_root)
            payload = registry.load()
            active_models = payload.get("active_models", {})
            self.assertEqual(active_models, {})

            settings = load_settings(project_root=root)
            model = load_prediction_model(settings, horizon_min=15)
            prediction = model.predict(
                feature_snapshot=FeatureSnapshot(
                    symbol="005930",
                    event_time=now_local("Asia/Seoul"),
                    feature_set_version="feature-set-v1",
                    values={
                        "return_1m_pct": 0.6,
                        "bid_ask_imbalance": 0.2,
                        "spread_bps": 1.0,
                        "hl_range_pct": 0.1,
                    },
                ),
                horizon_min=15,
                prediction_id="registry-fallback",
            )
            self.assertEqual(prediction.model_version, "baseline-h15-v1")

    def test_set_builtin_active_updates_registry_and_loader_uses_it(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "registry-explicit" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
        }

        with patch.dict(os.environ, env, clear=False):
            result = set_builtin_model_active(project_root=root, horizon_min=15, builtin_name="baseline")
            registry = ModelRegistry(runtime_root)
            payload = registry.load()
            active_models = payload.get("active_models", {})

            self.assertIn("15", active_models)
            self.assertEqual(result.model_version, "baseline-h15-v1")

            settings = load_settings(project_root=root)
            model = load_prediction_model(settings, horizon_min=15)
            self.assertEqual(type(model).__name__, "BaselineDirectionModel")

    def test_registry_can_store_builtin_model_entry(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "registry-builtin" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)

        registry = ModelRegistry(runtime_root)
        registry.set_active_model(
            ModelRegistryEntry(
                horizon_min=15,
                model_version="linear-score-h15-v1",
                artifact_path="",
                feature_set_version="feature-set-v1",
                model_kind="builtin",
                builtin_name="linear_score",
            )
        )
        payload = registry.load()

        self.assertEqual(payload["active_models"]["15"]["model_kind"], "builtin")
        self.assertEqual(payload["active_models"]["15"]["builtin_name"], "linear_score")


if __name__ == "__main__":
    unittest.main()
