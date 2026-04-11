import json
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.models.loader import load_prediction_model
from app.storage.contracts import FeatureSnapshot
from app.utils.time import now_local


class ModelLoaderTests(unittest.TestCase):
    def test_load_prediction_model_prefers_centroid_artifact(self) -> None:
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

            self.assertEqual(prediction.model_version, "centroid-h15-v1")
            self.assertGreater(prediction.probability_up, prediction.probability_down)


if __name__ == "__main__":
    unittest.main()
