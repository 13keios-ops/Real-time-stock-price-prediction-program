import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.models.baseline import BaselineDirectionModel
from app.models.loader import load_latest_lightgbm_shadow_model, load_prediction_model
from app.models.registry import ModelRegistry, ModelRegistryEntry
from app.storage.contracts import FeatureSnapshot
from app.utils.time import now_local


class ModelLoaderTests(unittest.TestCase):
    def test_load_prediction_model_defaults_to_baseline_without_registry(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "model-loader" / str(uuid.uuid4())
        model_dir = runtime_root / "ml" / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = model_dir / "centroid-h15-v1.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "model_version": "centroid-h15-v1",
                    "feature_set_version": "feature-set-v1",
                    "horizon_min": 15,
                    "feature_names": [
                        "avg_trade_size",
                        "bid_ask_imbalance",
                        "hl_range_pct",
                        "mid_price",
                        "return_1m_pct",
                        "spread_bps",
                    ],
                    "centroids": {
                        "up": [10, 0.2, 0.1, 70000, 0.5, 1.2],
                        "flat": [10, 0.0, 0.1, 70000, 0.0, 1.2],
                        "down": [10, -0.2, 0.1, 70000, -0.5, 1.2],
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"RUNTIME_DATA_DIR": str(runtime_root)}, clear=False):
            settings = load_settings(project_root=root)
            model = load_prediction_model(settings, horizon_min=15)
            prediction = model.predict(
                FeatureSnapshot(
                    symbol="005930",
                    event_time=now_local("Asia/Seoul"),
                    feature_set_version="feature-set-v1",
                    values={
                        "avg_trade_size": 12.0,
                        "bid_ask_imbalance": 0.25,
                        "hl_range_pct": 0.1,
                        "mid_price": 70010.0,
                        "return_1m_pct": 0.6,
                        "spread_bps": 1.1,
                    },
                ),
                horizon_min=15,
                prediction_id="pred-test",
            )

            self.assertEqual(prediction.model_version, "baseline-h15-v1")
            self.assertGreater(prediction.probability_up, prediction.probability_down)

    def test_load_prediction_model_supports_builtin_registry_entry(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "model-loader-builtin" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)

        with patch.dict(os.environ, {"RUNTIME_DATA_DIR": str(runtime_root)}, clear=False):
            registry = ModelRegistry(runtime_root)
            registry.set_active_model(
                ModelRegistryEntry(
                    horizon_min=15,
                    model_version="baseline-h15-v1",
                    artifact_path="",
                    feature_set_version="feature-set-v1",
                    model_kind="builtin",
                    builtin_name="baseline",
                )
            )
            settings = load_settings(project_root=root)
            model = load_prediction_model(settings, horizon_min=15)

            self.assertIsInstance(model, BaselineDirectionModel)

    def test_load_latest_lightgbm_shadow_model_returns_none_without_artifact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "model-loader-lightgbm-shadow-empty" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)

        with patch.dict(os.environ, {"RUNTIME_DATA_DIR": str(runtime_root)}, clear=False):
            settings = load_settings(project_root=root)

            self.assertIsNone(load_latest_lightgbm_shadow_model(settings, horizon_min=15))

    def test_load_latest_lightgbm_shadow_model_uses_latest_artifact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "model-loader-lightgbm-shadow" / str(uuid.uuid4())
        model_dir = runtime_root / "ml" / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        older_artifact = model_dir / "lightgbm-h15-v1.joblib"
        latest_artifact = model_dir / "lightgbm-h15-v2.joblib"
        older_artifact.write_text("placeholder", encoding="utf-8")
        latest_artifact.write_text("placeholder", encoding="utf-8")
        fake_model = object()

        with patch.dict(os.environ, {"RUNTIME_DATA_DIR": str(runtime_root)}, clear=False):
            settings = load_settings(project_root=root)
            with patch("app.models.loader.LightGbmDirectionModel.from_path", return_value=fake_model) as from_path:
                model = load_latest_lightgbm_shadow_model(settings, horizon_min=15)

        self.assertIs(model, fake_model)
        from_path.assert_called_once_with(latest_artifact)

    def test_load_latest_lightgbm_shadow_model_skips_invalid_newer_artifact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "model-loader-lightgbm-shadow-invalid" / str(uuid.uuid4())
        model_dir = runtime_root / "ml" / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        valid_artifact = model_dir / "lightgbm-h15-valid.joblib"
        invalid_artifact = model_dir / "lightgbm-h15-invalid.joblib"
        valid_artifact.write_text("valid", encoding="utf-8")
        invalid_artifact.write_text("invalid", encoding="utf-8")
        current_time = time.time()
        os.utime(valid_artifact, (current_time - 10, current_time - 10))
        os.utime(invalid_artifact, (current_time, current_time))
        valid_model = SimpleNamespace(
            artifact=SimpleNamespace(
                horizon_min=15,
                feature_set_version="feature-set-v1",
                class_labels=["down", "flat", "up"],
            )
        )

        with patch.dict(os.environ, {"RUNTIME_DATA_DIR": str(runtime_root)}, clear=False):
            settings = load_settings(project_root=root)
            with patch(
                "app.models.loader.LightGbmDirectionModel.from_path",
                side_effect=[ValueError("corrupt artifact"), valid_model],
            ) as from_path:
                model = load_latest_lightgbm_shadow_model(settings, horizon_min=15)

        self.assertIs(model, valid_model)
        self.assertEqual(
            [call.args[0] for call in from_path.call_args_list],
            [invalid_artifact, valid_artifact],
        )


if __name__ == "__main__":
    unittest.main()
