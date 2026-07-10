import os
import json
from datetime import datetime
from datetime import timedelta
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.services.broker_paper_sync import BrokerPaperSyncResult
from app.storage.contracts import BrokerOrderSubmission, Fill, PaperOrder, Prediction
from app.services.streaming import OnlinePipelineProcessor, build_sample_ws_frames, replay_ws_frames
from app.storage.runtime_writer import RuntimeWriter, get_sqlite_store


class StreamingPipelineTests(unittest.TestCase):
    def test_replay_sample_ws_frames_builds_online_outputs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
            "ENABLE_BROKER_PAPER_MIRRORING": "false",
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

    def test_lightgbm_shadow_predictions_are_written_without_driving_orders(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming-lightgbm-shadow" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
            "ENABLE_BROKER_PAPER_MIRRORING": "false",
        }

        class FakeLightGbmShadow:
            def predict(self, feature_snapshot, horizon_min: int, prediction_id: str) -> Prediction:
                return Prediction(
                    prediction_id=prediction_id,
                    symbol=feature_snapshot.symbol,
                    event_time=feature_snapshot.event_time,
                    horizon_min=horizon_min,
                    model_version=f"lightgbm-h{horizon_min}-shadow-test",
                    probability_up=0.05,
                    probability_flat=0.1,
                    probability_down=0.85,
                )

        def fake_shadow_loader(settings, horizon_min: int):
            return FakeLightGbmShadow() if horizon_min == 15 else None

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            with patch("app.services.streaming.load_latest_lightgbm_shadow_model", side_effect=fake_shadow_loader):
                result = replay_ws_frames(project_root=root, frames=build_sample_ws_frames("005930"))
            sqlite_store = get_sqlite_store(settings)

            self.assertIsNotNone(sqlite_store)
            prediction_rows = sqlite_store.fetch_all_rows("serving_predictions", "event_time")
            order_rows = sqlite_store.fetch_all_rows("paper_orders", "event_time")

        model_versions = {str(row["model_version"]) for row in prediction_rows}
        shadow_prediction_ids = [
            str(row["prediction_id"])
            for row in prediction_rows
            if str(row["model_version"]).startswith("lightgbm-h15-shadow-test")
        ]
        self.assertGreaterEqual(result.predictions_written, 3)
        self.assertIn("baseline-h15-v1", model_versions)
        self.assertIn("lightgbm-h15-shadow-test", model_versions)
        self.assertTrue(shadow_prediction_ids)
        self.assertTrue(order_rows)
        for order in order_rows:
            prediction_id = str(order["prediction_id"] or "")
            if not prediction_id:
                continue
            self.assertIn("pred-h15-", prediction_id)
            self.assertNotIn("shadow-lightgbm", prediction_id)

    def test_replay_can_close_positions_on_short_hold(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming-close" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
            "ENABLE_BROKER_PAPER_MIRRORING": "false",
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
            "ENABLE_BROKER_PAPER_MIRRORING": "false",
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
            "ENABLE_BROKER_PAPER_MIRRORING": "false",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            replay_ws_frames(project_root=root, frames=build_sample_ws_frames("005930"))
            processor = OnlinePipelineProcessor(settings)
            self.assertLess(processor.portfolio_book.cash_balance, settings.strategy.paper_initial_cash)
            self.assertIn("005930", processor.portfolio_book.positions)

    def test_online_pipeline_ignores_pending_orders_before_alignment_marker(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming-pending-alignment" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
            "ENABLE_BROKER_PAPER_MIRRORING": "false",
        }
        marker_dir = runtime_root / "reports" / "broker-paper"
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / "latest-alignment.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "aligned_at": "2026-05-13T10:00:00+09:00",
                    "baseline_positions": [],
                    "baseline_snapshot": {
                        "snapshot_id": "portfolio-broker-aligned-test",
                        "event_time": "2026-05-13T10:00:00+09:00",
                        "cash_balance": 1000000.0,
                        "gross_market_value": 0.0,
                        "net_liquidation_value": 1000000.0,
                        "open_positions": 0,
                        "realized_pnl": 0.0,
                        "unrealized_pnl": 0.0,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            writer = RuntimeWriter.from_settings(settings)
            writer.write_paper_order(
                PaperOrder(
                    order_id="paper-order-before-align",
                    symbol="005930",
                    event_time=datetime.fromisoformat("2026-05-13T09:59:00+09:00"),
                    side="buy",
                    qty=1,
                    limit_price=70000.0,
                    status="pending_lookup",
                )
            )
            writer.write_paper_order(
                PaperOrder(
                    order_id="paper-order-after-align",
                    symbol="000660",
                    event_time=datetime.fromisoformat("2026-05-13T10:01:00+09:00"),
                    side="buy",
                    qty=1,
                    limit_price=130000.0,
                    status="pending_lookup",
                )
            )

            processor = OnlinePipelineProcessor(settings)

        self.assertNotIn("005930", processor.pending_order_symbols)
        self.assertNotIn("005930", processor.pending_buy_symbols)
        self.assertIn("000660", processor.pending_order_symbols)
        self.assertIn("000660", processor.pending_buy_symbols)

    def test_online_pipeline_default_ids_are_unique_across_runtime_starts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming-unique-ids" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        database_path = runtime_root / "test.db"
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{database_path}",
            "ENABLE_BROKER_PAPER_MIRRORING": "false",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            first = OnlinePipelineProcessor(settings)
            second = OnlinePipelineProcessor(settings)

        first_order_id = first._next_scoped_id("paper-order")
        second_order_id = second._next_scoped_id("paper-order")
        self.assertNotEqual(first_order_id, second_order_id)
        self.assertIn("paper-order-online-", first_order_id)
        self.assertIn("paper-order-online-", second_order_id)

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
            def fake_sync_result(*args, **kwargs):
                return BrokerPaperSyncResult(
                    ok=True,
                    synced_at="2026-04-13T10:16:00+09:00",
                    status="no_submissions",
                    total_submissions=0,
                    matched_orders=0,
                    updated_orders=0,
                    applied_fill_events=0,
                    applied_fill_qty=0,
                    open_order_count=0,
                    final_order_count=0,
                    pending_symbols=[],
                    report_markdown_path=runtime_root / "sync.md",
                    report_json_path=runtime_root / "sync.json",
                )

            with patch("app.services.streaming.BrokerPaperMirror.submit_local_order", return_value=fake_submission):
                with patch(
                    "app.services.streaming.BrokerPaperExecutionSync.sync_recent_orders",
                    side_effect=fake_sync_result,
                ):
                    result = replay_ws_frames(project_root=root, frames=build_sample_ws_frames("005930"))
                    sqlite_store = get_sqlite_store(settings)

        self.assertIsNotNone(sqlite_store)
        self.assertGreaterEqual(result.orders_written, 1)
        self.assertEqual(sqlite_store.count_rows("broker_paper_order_submissions"), 1)

    def test_broker_sync_rate_limit_cooldown_skips_until_window_elapsed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming-broker-sync-cooldown" / str(uuid.uuid4())
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

        class FakeBrokerSync:
            def __init__(self) -> None:
                self.calls = 0
                self.retry_delays_seen = []

            def sync_recent_orders(self, **kwargs) -> BrokerPaperSyncResult:
                self.calls += 1
                self.retry_delays_seen.append(kwargs.get("retry_delays_seconds"))
                status = "rate_limited" if self.calls == 1 else "ok"
                return BrokerPaperSyncResult(
                    ok=status == "ok",
                    synced_at="2026-04-13T10:16:00+09:00",
                    status=status,
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
                    error="rate limit" if status == "rate_limited" else None,
                )

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            processor = OnlinePipelineProcessor(settings)
            fake_sync = FakeBrokerSync()
            processor.broker_paper_sync = fake_sync

            first_time = datetime.fromisoformat("2026-04-13T10:15:30+09:00")
            processor._run_broker_sync(bar_time=first_time)
            processor._run_broker_sync(bar_time=first_time.replace(minute=16))
            processor._run_broker_sync(bar_time=first_time.replace(minute=20))
            processor._run_broker_sync(bar_time=first_time.replace(minute=21), force=True)

        self.assertEqual(fake_sync.calls, 3)
        self.assertEqual(fake_sync.retry_delays_seen, [(), (), ()])

    def test_broker_sync_exception_keeps_runtime_alive_and_enters_cooldown(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming-broker-sync-timeout" / str(uuid.uuid4())
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

        class FailingBrokerSync:
            def __init__(self) -> None:
                self.calls = 0

            def sync_recent_orders(self, **kwargs):
                self.calls += 1
                raise TimeoutError("broker sync timed out")

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            processor = OnlinePipelineProcessor(settings)
            fake_sync = FailingBrokerSync()
            processor.broker_paper_sync = fake_sync

            first_time = datetime.fromisoformat("2026-04-13T10:15:30+09:00")
            processor._run_broker_sync(bar_time=first_time)
            processor._run_broker_sync(bar_time=first_time.replace(minute=16))

        self.assertEqual(fake_sync.calls, 1)
        self.assertIsNotNone(processor._broker_sync_pause_until)

    def test_pending_broker_order_blocks_repeated_close_submission(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "streaming-pending-close" / str(uuid.uuid4())
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

        opened_at = datetime.fromisoformat("2026-04-13T10:00:00+09:00")
        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            processor = OnlinePipelineProcessor(settings, max_hold_minutes=1)
            fill = Fill(
                fill_id="fill-open-test",
                order_id="paper-order-open-test",
                event_time=opened_at,
                fill_price=70000.0,
                fill_qty=1,
                commission=0.0,
                tax=0.0,
            )
            processor.portfolio_book.apply_buy_fill("005930", fill=fill, fill_price=70000.0)
            processor.pending_order_symbols.add("005930")

            with patch("app.services.streaming.BrokerPaperMirror.submit_local_order") as submit_local_order:
                reason = processor._maybe_close_position(
                    "005930",
                    mark_price=70100.0,
                    event_time=opened_at + timedelta(minutes=5),
                )

        self.assertEqual(reason, "broker_order_pending")
        submit_local_order.assert_not_called()


if __name__ == "__main__":
    unittest.main()
