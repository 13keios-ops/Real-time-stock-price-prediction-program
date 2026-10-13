import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.paper_trading.daily_mission import MISSION_SUBDIRECTORY, MissionContract
from app.services.streaming import OnlinePipelineProcessor, build_sample_ws_frames
from app.brokers.kis_quote_ws import parse_kis_ws_frame


class DailyMissionStreamingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.folder = self.root / ".tmp-tests" / "mission-streaming" / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.folder)
        self.start = datetime.fromisoformat("2026-10-14T09:30:00+09:00")

    def processor(self, name, *, enabled=False, payload=None):
        folder = self.folder / name
        if enabled:
            mission_folder = folder / MISSION_SUBDIRECTORY
            mission_folder.mkdir(parents=True)
            contract = MissionContract(symbols=("005930",))
            (mission_folder / "contract.json").write_text(
                json.dumps(payload or {"enabled": True, "contract": contract.to_dict()}), encoding="utf-8")
        env = {"RUNTIME_DATA_DIR": str(folder), "DATABASE_URL": f"sqlite:///{folder / 'main-test.db'}",
               "ENABLE_BROKER_PAPER_MIRRORING": "false", "TRADING_MODE": "paper"}
        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=self.root)
            processor = OnlinePipelineProcessor(settings, prediction_horizons=(15,),
                                                id_namespace="mission-isolation-proof")
        mission = getattr(processor, "daily_profit_mission", None)
        if mission:
            self.addCleanup(mission.close)
        return processor

    def feed(self, processor):
        frames = build_sample_ws_frames("005930")
        quote = parse_kis_ws_frame(frames[0])["records"][0]
        trade = parse_kis_ws_frame(frames[1])["records"][0]
        for minute in range(4):
            timestamp = self.start + timedelta(minutes=minute)
            with patch("app.services.streaming.now_local", return_value=timestamp):
                processor.process_orderbook_record(quote, event_time=timestamp)
                processor.process_trade_record(trade, event_time=timestamp)
        with patch("app.services.streaming.now_local", return_value=self.start + timedelta(minutes=4)):
            return processor.flush()

    def test_enabled_mission_observes_bars_without_changing_main_decisions_orders_or_fills(self):
        baseline = self.processor("baseline")
        enabled = self.processor("enabled", enabled=True)
        self.assertIsNotNone(getattr(enabled, "daily_profit_mission", None),
                             "The opted-in separate wallet is not connected.")
        before = self.feed(baseline)
        after = self.feed(enabled)
        one = before.to_dict()
        two = after.to_dict()
        one.pop("runtime_root")
        two.pop("runtime_root")
        self.assertEqual(one, two)
        for table in ("serving_decision_ledger", "paper_orders", "paper_fills"):
            rows1 = [dict(r) for r in baseline.writer.sqlite_store.fetch_all_rows(table, "event_time")]
            rows2 = [dict(r) for r in enabled.writer.sqlite_store.fetch_all_rows(table, "event_time")]
            self.assertEqual(rows1, rows2, table)
        report = enabled.daily_profit_mission.report(as_of=self.start + timedelta(minutes=4))
        self.assertEqual(report["source_bar_count"], 4)
        self.assertEqual(report["cash_balance"], 300000)
        self.assertEqual(report["safety"]["broker_order_calls"], 0)

    def test_invalid_opt_in_is_logged_and_existing_pipeline_continues(self):
        with self.assertLogs("app.services.streaming", level="ERROR"):
            processor = self.processor("bad", enabled=True, payload={"enabled": "false", "contract": {}})
        self.assertIsNone(processor.daily_profit_mission)
        result = self.feed(processor)
        self.assertEqual(result.minute_bars_written, 4)

    def test_missing_contract_does_not_create_mission_storage(self):
        processor = self.processor("disabled")
        self.feed(processor)
        self.assertIsNone(getattr(processor, "daily_profit_mission", None))
        self.assertFalse((self.folder / "disabled" / MISSION_SUBDIRECTORY).exists())


    def test_mission_storage_failure_is_reported_and_primary_feed_keeps_running(self):
        processor = self.processor("failure", enabled=True)
        mission = processor.daily_profit_mission
        with patch.object(mission, "observe", side_effect=RuntimeError("test storage failure")):
            with self.assertLogs("app.services.streaming", level="ERROR"):
                result = self.feed(processor)
        self.assertEqual(result.minute_bars_written, 4)
        self.assertIsNone(processor.daily_profit_mission)
        report = json.loads((self.folder / "failure" / MISSION_SUBDIRECTORY / "latest.json").read_text())
        self.assertIn("mission_runtime_error", report["evidence_blocking_reasons"])
        self.assertFalse(report["target_reached"])


if __name__ == "__main__":
    unittest.main()
