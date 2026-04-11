import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.services.kis_verification import verify_kis_websocket_runtime


class KisWebSocketVerificationTests(unittest.TestCase):
    def test_verification_reports_missing_requirements_without_credentials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "kis-ws-verification" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
            "TRADING_MODE": "paper",
            "KIS_APP_KEY_PAPER": "",
            "KIS_APP_SECRET_PAPER": "",
        }

        with patch.dict(os.environ, env, clear=False):
            result = verify_kis_websocket_runtime(
                project_root=root,
                symbols=["005930"],
                max_frames=5,
                max_reconnects=0,
            )

            self.assertFalse(result.ok)
            self.assertIn("KIS credentials", result.missing_requirements)
            self.assertTrue(result.report_markdown_path.exists())
            self.assertTrue(result.report_json_path.exists())


if __name__ == "__main__":
    unittest.main()

