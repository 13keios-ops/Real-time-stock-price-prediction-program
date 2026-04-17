import os
from datetime import datetime
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.services.broker_paper_sync import BrokerPaperSyncResult
from app.storage.contracts import BrokerOrderSubmission
from app.services.streaming import OnlinePipelineProcessor, build_sample_ws_frames, replay_ws_frames
from app.storage.runtime_writer import get_sqlite_store


class StreamingPipelineTests(unittest.TestCase):
    def test_replay_sample_ws_frames_builds_online_outputs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            result = replay_ws_frames(project_root=root, frames=build_sample_ws_frames("005930"))
            sqlite_store = get_sqlite_store(settings)

            self.assertIsNotNone(sqlite_store)
            self.assertGreaterEqual(result.frames_received, 1)
            self.assertEqual(result.control_frames, 0)
            self.assertGreaterEqual(result.raw_trade_events, 3)
            self.assertGreaterEqual(result.raw_orderbook_events, 2)
            self.assertGreaterEqual(result.minute_bars_written, 1)
            self.assertGreaterEqual(result.predictions_written, 2)
            self.assertGreaterEqual(result.signals_written, 1)
            self.assertGreater(sqlite_store.count_rows("raw_market_ticks"), 0)
            self.assertGreater(sqlite_store.count_rows("serving_predictions"), 0)
            self.assertGreaterEqual(sqlite_store.count_rows("paper_positions"), 1)
            self.assertGreaterEqual(sqlite_store.count_rows("paper_portfolio_snapshots"), 1)
            latest_tick = sqlite_store.fetch_latest_row("raw_market_ticks", "event_time")
            latest_prediction = sqlite_store.fetch_latest_row("serving_predictions", "event_time")
            prediction_rows = sqlite_store.fetch_all_rows("serving_predictions", "event_time")
            horizons = {int(row["horizon_min"]) for row in prediction_rows}
            self.assertIsNotNone(latest_tick)
            self.assertIsNotNone(latest_prediction)
            self.assertEqual(latest_tick["source"], "kis-ws-replay")
            self.assertIn("-replay-", str(latest_prediction["prediction_id"]))
            self.assertIn(15, horizons)
            self.assertIn(60, horizons)

    def test_replay_can_close_positions_on_short_hold(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming-close" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            result = replay_ws_frames(
                project_root=root,
                frames=build_sample_ws_frames("005930"),
                max_hold_minutes=1,
            )
            sqlite_store = get_sqlite_store(settings)

            self.assertIsNotNone(sqlite_store)
            self.assertGreaterEqual(result.orders_written, 1)
            latest_position = sqlite_store.fetch_latest_row("paper_positions", "updated_at")
            self.assertIsNotNone(latest_position)
            self.assertEqual(int(latest_position["qty"]), 0)

    def test_replay_ignores_control_frames(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming-control" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
        }

        with patch.dict(os.environ, env, clear=False):
            result = replay_ws_frames(
                project_root=root,
                frames=['{"header":{"tr_id":"PINGPONG"},"body":{"rt_cd":"0"}}', *build_sample_ws_frames("005930")],
            )
            self.assertGreaterEqual(result.frames_received, 5)
            self.assertEqual(result.control_frames, 1)

    def test_online_pipeline_restores_existing_open_position_state(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming-restore" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            replay_ws_frames(project_root=root, frames=build_sample_ws_frames("005930"))
            processor = OnlinePipelineProcessor(settings)
            self.assertLess(processor.portfolio_book.cash_balance, settings.strategy.paper_initial_cash)
            self.assertIn("005930", processor.portfolio_book.positions)

    def test_online_pipeline_writes_broker_submission_when_enabled(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming-broker-mirror" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
            "ENABLE_BROKER_PAPER_MIRRORING": "true",
            "KIS_APP_KEY_PAPER": "paper-key",
            "KIS_APP_SECRET_PAPER": "paper-secret",
            "KIS_ACCOUNT_NO_PAPER": "12345678",
            "KIS_PRODUCT_CODE_PAPER": "01",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            fake_submission = BrokerOrderSubmission(
                submission_id="broker-paper-paper-order-replay-000001",
                local_order_id="paper-order-replay-000001",
                broker_mode="paper",
                symbol="005930",
                event_time=datetime.fromisoformat("2026-04-13T10:15:00+09:00"),
                side="buy",
                qty=1,
                limit_price=70000.0,
                order_type="00",
                status="submitted",
                broker_order_no="123456",
                broker_branch_no="00111",
                detail={"message": "ok"},
            )
            with patch("app.services.streaming.BrokerPaperMirror.submit_local_order", return_value=fake_submission):
                with patch(
                    "app.services.streaming.BrokerPaperExecutionSync.sync_recent_orders",
                    return_value=BrokerPaperSyncResult(
                        ok=True,
                        synced_at="2026-04-13T10:16:00+09:00",
                        status="ok",
                        total_submissions=1,
                        matched_orders=0,
                        updated_orders=0,
                        applied_fill_events=0,
                        applied_fill_qty=0,
                        open_order_count=1,
                        final_order_count=0,
                        pending_symbols=["005930"],
                        report_markdown_path=runtime_root / "sync.md",
                        report_json_path=runtime_root / "sync.json",
                    ),
                ):
                    result = replay_ws_frames(project_root=root, frames=build_sample_ws_frames("005930"))
                    sqlite_store = get_sqlite_store(settings)

        self.assertIsNotNone(sqlite_store)
        self.assertGreaterEqual(result.orders_written, 1)
        self.assertEqual(sqlite_store.count_rows("broker_paper_order_submissions"), 1)


if __name__ == "__main__":
    unittest.main()
