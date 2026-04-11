import json
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.models.loader import load_prediction_model
from app.models.registry import ModelRegistry
from app.services.orchestrator import run_synthetic_dev_cycle


class ModelRegistryTests(unittest.TestCase):
    def test_training_updates_registry_and_loader_uses_it(self) -> None:
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
            self.assertIn("15", active_models)

            settings = load_settings(project_root=root)
            model = load_prediction_model(settings, horizon_min=15)
            artifact_path = Path(active_models["15"]["artifact_path"])
            artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(model.artifact.model_version, artifact_payload["model_version"])


if __name__ == "__main__":
    unittest.main()
