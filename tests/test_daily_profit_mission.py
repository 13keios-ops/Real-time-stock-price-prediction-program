import importlib
import importlib.util
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import sqlite3
import threading
import unittest
import uuid
from unittest.mock import patch

from app.storage.contracts import MinuteBar


class DailyProfitMissionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("app.paper_trading.daily_mission"),
                             "The isolated daily-profit mission has not been implemented.")
        module = importlib.import_module("app.paper_trading.daily_mission")
        self.Contract = module.MissionContract
        self.Mission = module.DailyProfitMission
        self.folder = Path(__file__).resolve().parents[1] / ".tmp-tests" / "daily-profit-mission" / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.folder)
        self.contract = self.Contract(symbols=("005930",), holidays=("2026-10-16",))
        self.mission = self.Mission(self.folder, self.contract)
        self.addCleanup(self.mission.close)

    def bar(self, minute=0, price=10000, *, day="2026-10-14", **values):
        timestamp = datetime.fromisoformat(day + "T09:10:00+09:00") + timedelta(minutes=minute)
        record = dict(symbol="005930", bar_time=timestamp, open=price, high=price + 20,
                      low=price - 20, close=price, volume=10000, trade_count=500)
        record.update(values)
        return MinuteBar(**record)

    def observe(self, bar):
        return self.mission.observe(bar, observed_at=bar.bar_time + timedelta(minutes=1), quote_spread_bps=10.0)

    def report(self, bar=None):
        return self.mission.report(as_of=(bar or self.bar(25)).bar_time + timedelta(minutes=1))

    def prepare_entry(self):
        for minute in range(20):
            self.observe(self.bar(minute))
        trigger = self.bar(20, 10050, high=10055, low=10000, open=10000, volume=25000)
        self.observe(trigger)
        return trigger

    def fill_entry(self):
        self.prepare_entry()
        self.observe(self.bar(21, 10060))
        self.observe(self.bar(22, 10060))

    def test_initial_capital_date_goal_and_costs_are_explicit(self):
        r = self.report()
        self.assertEqual((r["initial_cash"], r["cash_balance"], r["daily_net_target"]), (300000, 300000, 10000))
        self.assertEqual(r["start_date"], "2026-10-14")
        self.assertEqual(r["cost_model"]["commission_rate_per_side"], 0.00147)
        self.assertEqual(r["cost_model"]["sell_tax_rate"], 0.002)
        self.assertEqual(r["safety"]["broker_order_calls"], 0)
        self.assertEqual(r["safety"]["main_database_access"], "none")
        self.assertFalse(r["target_reached"])

    def test_pre_start_weekend_and_holiday_do_not_create_trades(self):
        for day in ("2026-10-13", "2026-10-16", "2026-10-17"):
            self.assertFalse(self.observe(self.bar(day=day)))
        self.assertEqual(self.report()["virtual_fill_count"], 0)
        self.assertEqual(self.report()["cash_balance"], 300000)

    def test_breakout_needs_volume_and_does_not_chase_extreme_jump(self):
        for minute in range(20):
            self.observe(self.bar(minute))
        self.observe(self.bar(20, 10050, open=10000, volume=5000))
        self.assertEqual(self.report()["pending_order_count"], 0)
        self.observe(self.bar(21, 12000, open=10050, volume=100000))
        self.assertEqual(self.report()["pending_order_count"], 0)

    def test_signal_never_fills_same_bar_or_already_open_minute(self):
        self.prepare_entry()
        self.assertEqual(self.report()["virtual_fill_count"], 0)
        self.assertEqual(self.report()["pending_order_count"], 1)
        self.observe(self.bar(21, 10060))
        self.assertEqual(self.report()["virtual_fill_count"], 0)
        self.observe(self.bar(22, 10060))
        r = self.report()
        self.assertEqual((r["virtual_fill_count"], r["open_positions"]), (1, 1))
        self.assertGreaterEqual(r["cash_balance"], 0)
        fill = self.mission.events(kind="fill")[0]
        self.assertGreater(datetime.fromisoformat(fill["event_time"]), datetime.fromisoformat(fill["decision_available_at"]))
        self.assertIsInstance(fill["qty"], int)

    def test_current_high_is_not_future_profit_or_intrabar_exit(self):
        for minute in range(20):
            self.observe(self.bar(minute))
        self.observe(self.bar(20, 10050, open=10000, high=50000, low=10000, volume=25000))
        self.assertEqual(self.report()["virtual_fill_count"], 0)
        self.assertEqual(self.report()["realized_net_pnl"], 0)
        self.assertFalse(self.report()["target_reached"])

    def test_missing_execution_bar_cancels_buy(self):
        self.prepare_entry()
        self.observe(self.bar(24, 10060))
        self.assertEqual(self.report()["virtual_fill_count"], 0)
        self.assertEqual(self.report()["pending_order_count"], 0)
        self.assertIn("execution_bar_missing", [r.get("reason") for r in self.mission.events()])

    def test_restart_duplicate_does_not_duplicate_fill_or_capital(self):
        self.fill_entry()
        before = self.report()
        self.mission.close()
        reopened = self.Mission(self.folder, self.contract)
        self.addCleanup(reopened.close)
        self.assertFalse(reopened.observe(self.bar(22, 10060), observed_at=self.bar(23).bar_time))
        after = reopened.report(as_of=self.bar(25).bar_time)
        self.assertEqual(after["virtual_fill_count"], before["virtual_fill_count"])
        self.assertEqual(after["cash_balance"], before["cash_balance"])

    def test_conflicting_duplicate_is_blocked_not_rewritten(self):
        self.prepare_entry()
        self.observe(self.bar(20, 10049))
        r = self.report()
        self.assertIn("conflicting_bar_identity", r["evidence_blocking_reasons"])
        self.assertEqual((r["pending_order_count"], r["virtual_fill_count"]), (0, 0))

    def test_costs_charged_and_slippage_not_double_deducted(self):
        self.fill_entry()
        for minute, price in ((23, 10300), (24, 10000), (25, 10000), (26, 10000)):
            self.observe(self.bar(minute, price))
        fills = self.mission.events(kind="fill")
        self.assertEqual([r["side"] for r in fills], ["buy", "sell"])
        buy, sell = fills
        self.assertEqual(buy["tax"], 0)
        self.assertEqual(sell["tax"], math.ceil(sell["qty"] * sell["price"] * 0.002))
        self.assertEqual(buy["commission"], math.ceil(buy["qty"] * buy["price"] * 0.00147))
        expected = 300000 - buy["qty"] * buy["price"] - buy["commission"]
        expected += sell["qty"] * sell["price"] - sell["commission"] - sell["tax"]
        r = self.report(self.bar(26))
        self.assertAlmostEqual(r["cash_balance"], expected)
        self.assertAlmostEqual(r["realized_net_pnl"], expected - 300000)
        self.assertGreater(r["slippage_cost"], 0)
        self.assertEqual(r["open_positions"], 0)

    def test_target_is_not_profit_cap_and_requires_flat_realized_profit(self):
        self.fill_entry()
        self.observe(self.bar(23, 11000))
        r = self.report(self.bar(23))
        self.assertEqual((r["open_positions"], r["pending_order_count"]), (1, 0))
        self.assertFalse(r["target_reached"])
        self.observe(self.bar(24, 12000))
        self.assertEqual(self.report(self.bar(24))["pending_order_count"], 0)
        for minute in (25, 26, 27):
            self.observe(self.bar(minute, 11700))
        r = self.report(self.bar(27))
        self.assertTrue(r["target_reached"])
        self.assertEqual(r["day_status"], "target_reached")
        self.assertGreater(r["daily_net_pnl"], 10000)
        self.assertTrue(r["new_entries_halted"])
        self.assertEqual(r["open_positions"], 0)

    def test_daily_loss_exit_and_next_day_do_not_refill_capital(self):
        self.fill_entry()
        for minute in (23, 24, 25):
            self.observe(self.bar(minute, 9600))
        r = self.report(self.bar(25))
        self.assertTrue(r["new_entries_halted"])
        self.assertEqual(r["open_positions"], 0)
        self.assertLess(r["cash_balance"], 294000)
        balance = r["cash_balance"]
        self.observe(self.bar(day="2026-10-15"))
        self.assertEqual(self.report(self.bar(day="2026-10-15"))["cash_balance"], balance)

    def test_forced_flat_precedes_expected_closing_auction_gap(self):
        self.fill_entry()
        for stamp in ("15:13", "15:14", "15:15"):
            bar = self.bar(23, 10060, bar_time=datetime.fromisoformat("2026-10-14T" + stamp + ":00+09:00"))
            self.observe(bar)
        self.assertEqual(self.report(bar)["open_positions"], 0)
        self.assertEqual(self.mission.events(kind="fill")[-1]["event_time"], "2026-10-14T15:15:00+09:00")

    def test_incomplete_or_stale_bar_never_fills(self):
        self.prepare_entry()
        bar = self.bar(22, 10060)
        self.assertFalse(self.mission.observe(bar, observed_at=bar.bar_time))
        self.assertFalse(self.mission.observe(bar, observed_at=bar.bar_time + timedelta(minutes=10)))
        self.assertEqual(self.report()["virtual_fill_count"], 0)

    def test_nonfinite_price_fail_closed(self):
        self.assertFalse(self.observe(self.bar(20, math.nan)))
        self.assertEqual(self.report()["cash_balance"], 300000)
        self.assertFalse(self.report()["target_reached"])

    def test_failed_transaction_rolls_back_fill_and_book(self):
        self.prepare_entry()
        self.observe(self.bar(21, 10060))
        before = self.report()
        with patch.object(self.mission, "_write_state", side_effect=sqlite3.OperationalError("test failure")):
            with self.assertRaises(sqlite3.OperationalError):
                self.observe(self.bar(22, 10060))
        after = self.report()
        self.assertEqual(before["cash_balance"], after["cash_balance"])
        self.assertEqual(before["virtual_fill_count"], after["virtual_fill_count"])

    def test_contract_change_does_not_reset_wallet(self):
        self.fill_entry()
        changed = self.Contract(symbols=("005930",), commission_rate=0.00015)
        with self.assertRaisesRegex(ValueError, "contract"):
            self.Mission(self.folder, changed)

    def test_own_storage_and_report_never_create_main_paper_or_e7_records(self):
        self.fill_entry()
        self.mission.write_report(as_of=self.bar(23).bar_time)
        self.assertTrue((self.folder / "mission.db").is_file())
        r = json.loads((self.folder / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(r["safety"]["broker_network_calls"], 0)
        self.assertFalse((self.folder / "dev.db").exists())
        self.assertFalse(r["safety"]["e7_policy_changed"])


    def test_loader_is_opt_in_and_never_enabled_for_live_or_replay_source(self):
        module = importlib.import_module("app.paper_trading.daily_mission")
        self.assertTrue(callable(getattr(module, "load_enabled_mission", None)))
        root = self.folder / "runtime"
        self.assertIsNone(module.load_enabled_mission(root, source="kis-ws", trading_mode="paper"))
        folder = root / module.MISSION_SUBDIRECTORY
        folder.mkdir(parents=True)
        (folder / "contract.json").write_text(json.dumps({"enabled": True, "contract": self.contract.to_dict()}))
        for source, mode in (("synthetic", "paper"), ("kis-ws", "live")):
            self.assertIsNone(module.load_enabled_mission(root, source=source, trading_mode=mode))
        mission = module.load_enabled_mission(root, source="kis-ws", trading_mode="paper")
        self.addCleanup(mission.close)
        self.assertEqual(mission.report()["cash_balance"], 300000)

    def test_stale_open_mark_cannot_claim_target_or_liquidation_value(self):
        self.fill_entry()
        report = self.mission.report(as_of=self.bar(40).bar_time)
        self.assertIn("stale_open_position_mark", report["evidence_blocking_reasons"])
        self.assertIsNone(report["net_liquidation_after_exit_costs"])
        self.assertFalse(report["target_reached"])

    def test_nonfinite_volume_and_naive_timestamp_are_rejected(self):
        self.assertFalse(self.observe(self.bar(volume=math.nan)))
        self.assertFalse(self.observe(self.bar(volume=-1)))
        bar = self.bar()
        self.assertFalse(self.mission.observe(bar, observed_at=bar.bar_time.replace(tzinfo=None)))
        self.assertEqual(self.report()["source_bar_count"], 0)

    def test_previous_trade_day_cannot_regress_shared_wallet_day(self):
        contract = self.Contract(symbols=("005930", "000660"))
        mission = self.Mission(self.folder / "dual", contract)
        self.addCleanup(mission.close)
        current = self.bar(day="2026-10-15")
        mission.observe(current, observed_at=current.bar_time + timedelta(minutes=1))
        old = self.bar(day="2026-10-14", symbol="000660")
        self.assertFalse(mission.observe(old, observed_at=old.bar_time + timedelta(minutes=1)))
        self.assertEqual(mission.report(as_of=current.bar_time)["trade_date"], "2026-10-15")


    def test_history_after_data_gap_requires_new_contiguous_warmup(self):
        for minute in range(20):
            self.observe(self.bar(minute))
        self.observe(self.bar(29, 10050, open=10000, high=10055, low=10000, volume=25000))
        self.assertEqual(self.report(self.bar(29))["pending_order_count"], 0)

    def test_storage_symlink_cannot_point_mission_at_another_account(self):
        source = self.folder / "unrelated.db"
        with sqlite3.connect(source) as conn:
            conn.execute("CREATE TABLE protected_ledger (value TEXT)")
        bad = self.folder / "linked"
        bad.mkdir()
        (bad / "mission.db").symlink_to(source)
        with self.assertRaisesRegex(ValueError, "isolated"):
            self.Mission(bad, self.contract)
        with sqlite3.connect(source) as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertEqual(tables, ["protected_ledger"])


    def test_runtime_worker_thread_can_process_the_wallet_created_at_startup(self):
        results, errors = [], []
        def work():
            try:
                results.append(self.observe(self.bar()))
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=work)
        worker.start()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [True])
        self.assertEqual(self.report()["source_bar_count"], 1)

    def test_stale_second_writer_cannot_overwrite_shared_wallet_state(self):
        second = self.Mission(self.folder, self.contract)
        self.addCleanup(second.close)
        self.observe(self.bar())
        with self.assertRaisesRegex(RuntimeError, "concurrent"):
            second.observe(self.bar(1), observed_at=self.bar(2).bar_time, quote_spread_bps=10)
        self.assertEqual(self.report()["source_bar_count"], 1)

    def test_runtime_failure_is_persisted_and_blocks_pending_entry(self):
        self.prepare_entry()
        self.assertTrue(callable(getattr(self.mission, "mark_failed", None)))
        self.mission.mark_failed()
        report = self.report()
        self.assertIn("mission_runtime_error", report["evidence_blocking_reasons"])
        self.assertEqual(report["pending_order_count"], 0)
        self.mission.close()
        reopened = self.Mission(self.folder, self.contract)
        self.addCleanup(reopened.close)
        self.assertIn("mission_runtime_error", reopened.report()["evidence_blocking_reasons"])


    def test_initializer_is_idempotent_and_rejects_contract_change(self):
        self.assertIsNotNone(importlib.util.find_spec("scripts.run_daily_profit_mission"))
        module = importlib.import_module("scripts.run_daily_profit_mission")
        folder = self.folder / "initialized"
        first = module.initialize(folder, self.contract)
        second = module.initialize(folder, self.contract)
        self.assertEqual(first["cash_balance"], second["cash_balance"])
        self.assertEqual(first["contract_hash"], second["contract_hash"])
        altered = self.Contract(symbols=("005930",), initial_cash=400000)
        with self.assertRaisesRegex(ValueError, "contract"):
            module.initialize(folder, altered)
        payload = json.loads((folder / "contract.json").read_text())
        self.assertEqual(payload["contract"]["initial_cash"], 300000)


    def test_bid_ask_spread_and_slippage_are_both_in_price_not_double_charged(self):
        self.fill_entry()
        fill = self.mission.events(kind="fill")[0]
        self.assertAlmostEqual(fill["price"], 10060 * (1 + 18 / 10000))
        self.assertAlmostEqual(fill["slippage_cost"], 10060 * fill["qty"] * 3 / 10000)
        self.assertAlmostEqual(fill["spread_cost"], 10060 * fill["qty"] * 15 / 10000)
        report = self.report()
        self.assertEqual(report["cost_model"]["spread_allowance_bps_per_side"], 15)
        self.assertAlmostEqual(report["cost_model"]["round_trip_cost_pct"], 0.854)


if __name__ == "__main__":
    unittest.main()
