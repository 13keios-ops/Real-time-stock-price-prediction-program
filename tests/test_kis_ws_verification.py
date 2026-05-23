import os
from datetime import datetime
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.services.kis_verification import _market_session_context
from app.services.kis_verification import verify_kis_websocket_runtime
from app.services.streaming import OnlinePipelineResult


class KisWebSocketVerificationTests(unittest.TestCase):
    def test_market_session_context_marks_configured_holiday(self) -> None:
        root = Path(__file__).resolve().parents[1]
        settings = load_settings(project_root=root, env={})

        session_status, market_data_expected, status_note = _market_session_context(
            settings,
            datetime.fromisoformat("2026-05-05T10:00:00+09:00"),
        )

        self.assertEqual(session_status, "holiday")
        self.assertFalse(market_data_expected)
        self.assertIn("holiday", status_note.lower())

    def test_market_session_context_marks_overnight_before_warmup(self) -> None:
        root = Path(__file__).resolve().parents[1]
        settings = load_settings(project_root=root, env={})

        session_status, market_data_expected, status_note = _market_session_context(
            settings,
            datetime.fromisoformat("2026-05-21T00:30:00+09:00"),
        )

        self.assertEqual(session_status, "overnight")
        self.assertFalse(market_data_expected)
        self.assertIn("not expected", status_note.lower())

    def test_verification_reports_missing_requirements_without_credentials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        temp_root = root / ".tmp-tests" / "kis-ws-verification-root" / str(uuid.uuid4())
        shutil.copytree(root / "config", temp_root / "config")
        runtime_root = temp_root / "runtime-data"
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
                project_root=temp_root,
                symbols=["005930"],
                max_frames=5,
                max_reconnects=0,
            )

            self.assertFalse(result.ok)
            self.assertIn("KIS credentials", result.missing_requirements)
            self.assertTrue(result.report_markdown_path.exists())
            self.assertTrue(result.report_json_path.exists())

    def test_verification_marks_market_data_flow_false_when_only_control_frames_arrive(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "kis-ws-verification" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
            "TRADING_MODE": "paper",
            "KIS_APP_KEY_PAPER": "paper-key",
            "KIS_APP_SECRET_PAPER": "paper-secret",
        }

        fake_result = OnlinePipelineResult(
            frames_received=5,
            control_frames=5,
            raw_trade_events=0,
            raw_orderbook_events=0,
            minute_bars_written=0,
            predictions_written=0,
            signals_written=0,
            orders_written=0,
            runtime_root=runtime_root,
        )

        with (
            patch.dict(os.environ, env, clear=False),
            patch("app.services.kis_verification.websockets", object()),
            patch("app.services.kis_verification.KisTokenManager.issue_approval_key", return_value="approval-key"),
            patch("app.services.kis_verification.run_kis_ws_listener_sync", return_value=fake_result),
        ):
            result = verify_kis_websocket_runtime(
                project_root=root,
                symbols=["005930"],
                max_frames=5,
                max_reconnects=0,
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.connection_ready)
        self.assertFalse(result.market_data_flow_ok)
        self.assertEqual(result.control_frames, 5)


if __name__ == "__main__":
    unittest.main()
