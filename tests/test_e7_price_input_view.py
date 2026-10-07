import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.features.minute_bars import aggregate_ticks_to_minute_bar
from app.services import e7_price_input_view as price_view
from app.services.e7_portfolio_evaluator import E7_PORTFOLIO_REPLAY_MANIFEST as MANIFEST
from app.services.portfolio_replay import DecisionPoint, ReplayBar, build_executable_decisions, group_decision_episodes
from app.services.portfolio_replay_v2 import build_v2_replay_context, replay_long_only_v2
from app.storage.contracts import MarketTickEvent


MINUTE = datetime.fromisoformat("2026-09-28T14:42:00+09:00")


def fixture(root):
    database = root / "runtime.db"
    ticks = [
        MarketTickEvent("005930", MINUTE, 100, 10, "kis-ws"),
        MarketTickEvent("005930", MINUTE + timedelta(seconds=30), 102, 20, "kis-ws"),
        MarketTickEvent("005930", MINUTE + timedelta(minutes=1), 103, 10, "kis-ws"),
        MarketTickEvent("005930", MINUTE + timedelta(seconds=59), 101, 5, "kis-ws"),
        MarketTickEvent("005930", MINUTE + timedelta(minutes=1, seconds=1), 104, 10, "kis-ws"),
    ]
    fragments = [aggregate_ticks_to_minute_bar("005930", ticks[:2]).to_record(),
                 aggregate_ticks_to_minute_bar("005930", ticks[3:4]).to_record()]
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE raw_market_ticks(symbol TEXT, event_time TEXT, price REAL, volume INTEGER, source TEXT);
            CREATE INDEX raw_lookup ON raw_market_ticks(source,symbol,event_time);
            CREATE TABLE curated_minute_bars(symbol TEXT, bar_time TEXT, open REAL, high REAL, low REAL,
                                            close REAL, volume INTEGER, trade_count INTEGER,
                                            PRIMARY KEY(symbol,bar_time));
        """)
        connection.executemany("INSERT INTO raw_market_ticks VALUES (?,?,?,?,?)",
                               [(t.symbol, t.event_time.isoformat(), t.price, t.volume, t.source) for t in ticks])
        connection.execute("INSERT INTO curated_minute_bars VALUES (?,?,?,?,?,?,?,?)", tuple(fragments[-1].values()))
    generation_file = root / "curated/2026-09-28/minute_bars.jsonl"
    generation_file.parent.mkdir(parents=True)
    generation_file.write_text("".join(json.dumps(row) + "\n" for row in fragments))
    bars = {"005930": [ReplayBar("005930", MINUTE + timedelta(minutes=i),
                                101 if i == 0 else 100, 101 if i == 0 else 100)
                      for i in range(-15, 3)],
            "000660": [ReplayBar("000660", MINUTE, 200, 200)]}
    return database, generation_file, bars


class E7PriceInputViewTests(unittest.TestCase):
    def build(self, root, database, bars, requested=None):
        return price_view.build_verified_price_input_view(
            database, runtime_root=root, bars_by_symbol=bars,
            requested_minutes=requested if requested is not None else [("005930", MINUTE)],
        )

    def test_view_is_versioned_immutable_and_preserves_database_and_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, generations, bars = fixture(root)
            hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (database, generations)]
            view = self.build(root, database, bars)
            target = next(b for b in view.bars_by_symbol["005930"] if b.bar_time == MINUTE)
            self.assertEqual((target.open_price, target.close_price), (100, 101))
            self.assertEqual(view.bars_by_symbol["000660"], tuple(bars["000660"]))
            self.assertEqual(next(b for b in bars["005930"] if b.bar_time == MINUTE).open_price, 101)
            proof = view.to_dict()
            self.assertEqual(proof["input_source_version"], "e7-captured-raw-price-view-v1")
            self.assertFalse(proof["official_evaluation_permitted"])
            self.assertEqual(proof["corrections"][0]["captured_tick_count"], 3)
            self.assertEqual(len(proof["input_fingerprint"]), 64)
            with self.assertRaises(TypeError):
                view.bars_by_symbol["005930"] = ()
            self.assertEqual(hashes, [hashlib.sha256(p.read_bytes()).hexdigest() for p in (database, generations)])

    def test_fragment_conflict_missing_raw_and_invalid_price_fail_closed(self):
        for failure in ("fragment", "raw", "price", "missing_file", "invalid_json"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                database, generations, bars = fixture(root)
                if failure == "missing_file":
                    generations.unlink()
                elif failure == "invalid_json":
                    generations.write_text("not json\n")
                else:
                    with sqlite3.connect(database) as connection:
                        if failure == "fragment":
                            connection.execute("UPDATE raw_market_ticks SET volume=11 WHERE rowid=1")
                        elif failure == "raw":
                            connection.execute("DELETE FROM raw_market_ticks")
                        else:
                            connection.execute("UPDATE raw_market_ticks SET price=0 WHERE rowid=1")
                with self.assertRaises(price_view.PriceInputViewError):
                    self.build(root, database, bars)

    def test_wrong_baseline_or_duplicate_bar_cannot_receive_overlay(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                database, _, bars = fixture(root)
                if duplicate:
                    bars["005930"].append(ReplayBar("005930", MINUTE, 101, 101))
                else:
                    bars["005930"] = [ReplayBar(b.symbol, b.bar_time, 999, b.close_price) for b in bars["005930"]]
                with self.assertRaises(price_view.PriceInputViewError):
                    self.build(root, database, bars)

    def test_request_requires_unique_aware_minute_identity(self):
        for requested in ([], [("005930", MINUTE)] * 2, [("005930", MINUTE.replace(tzinfo=None))],
                          [("005930", MINUTE + timedelta(seconds=1))], [("000000", MINUTE)]):
            with self.subTest(requested=requested), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                database, _, bars = fixture(root)
                with self.assertRaises(price_view.PriceInputViewError):
                    self.build(root, database, bars, requested)

    def test_jsonl_change_during_validation_blocks_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, generations, bars = fixture(root)
            original = aggregate_ticks_to_minute_bar
            def mutate(*args, **kwargs):
                generations.write_text(generations.read_text() + "{}\n")
                return original(*args, **kwargs)
            with patch.object(price_view, "aggregate_ticks_to_minute_bar", side_effect=mutate):
                with self.assertRaises(price_view.PriceInputViewError):
                    self.build(root, database, bars)

    def test_provenance_changes_when_capture_identity_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, _, bars = fixture(root)
            first = self.build(root, database, bars)
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE raw_market_ticks SET rowid=rowid+100")
            second = self.build(root, database, bars)
        self.assertNotEqual(first.to_dict()["input_fingerprint"], second.to_dict()["input_fingerprint"])
        self.assertEqual(first.bars_by_symbol, second.bars_by_symbol)

    def test_malformed_capture_time_has_consistent_error_and_closes_snapshot(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                database, _, bars = fixture(root)
                if invalid:
                    with sqlite3.connect(database) as writer:
                        writer.execute("UPDATE raw_market_ticks SET event_time=? WHERE rowid=1",
                                       ("2026-09-28T14:42:bad+09:00",))
                connections = []
                opener = price_view._connect_readonly
                def track(path):
                    connection = opener(path)
                    connections.append(connection)
                    return connection
                with patch.object(price_view, "_connect_readonly", side_effect=track):
                    if invalid:
                        with self.assertRaises(price_view.PriceInputViewError):
                            self.build(root, database, bars)
                    else:
                        self.build(root, database, bars)
                for connection in connections:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        connection.execute("SELECT 1")

    def test_invalid_unrequested_price_cannot_enter_verified_view(self):
        for value in (float("nan"), float("inf"), 0, -1):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                database, _, bars = fixture(root)
                bars["000660"] = [ReplayBar("000660", MINUTE, value, 200)]
                with self.assertRaises(price_view.PriceInputViewError):
                    self.build(root, database, bars)

    def test_db_source_change_during_validation_blocks_result(self):
        for field in ("raw", "curated"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                database, _, bars = fixture(root)
                with sqlite3.connect(database) as connection:
                    connection.execute("PRAGMA journal_mode=WAL")
                changed = False
                original = aggregate_ticks_to_minute_bar
                def mutate(*args, **kwargs):
                    nonlocal changed
                    if not changed:
                        with sqlite3.connect(database) as writer:
                            writer.execute("UPDATE raw_market_ticks SET price=99 WHERE rowid=1" if field == "raw"
                                           else "UPDATE curated_minute_bars SET volume=6")
                        changed = True
                    return original(*args, **kwargs)
                with patch.object(price_view, "aggregate_ticks_to_minute_bar", side_effect=mutate):
                    with self.assertRaises(price_view.PriceInputViewError):
                        self.build(root, database, bars)

    def test_capture_boundary_survives_jump_of_two_minutes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, _, bars = fixture(root)
            with sqlite3.connect(database) as writer:
                writer.execute("UPDATE raw_market_ticks SET event_time=? WHERE rowid=3",
                               ((MINUTE + timedelta(minutes=2)).isoformat(),))
            view = self.build(root, database, bars)
            self.assertEqual(view.to_dict()["corrections"][0]["captured_tick_count"], 3)

    def test_frozen_execution_times_and_both_cost_scenarios_only_change_verified_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database, _, bars = fixture(root)
            view = self.build(root, database, bars)
            episodes = group_decision_episodes([DecisionPoint("decision", "005930", MINUTE - timedelta(minutes=15), False)])
            original, _ = build_executable_decisions(episodes, bars, horizon_min=15, forced_flat_time=MANIFEST.forced_flat_time)
            corrected, _ = build_executable_decisions(episodes, view.bars_by_symbol, horizon_min=15, forced_flat_time=MANIFEST.forced_flat_time)
            self.assertEqual(original[0].episode_id, corrected[0].episode_id)
            self.assertEqual((original[0].entry_time, original[0].exit_time, original[0].entry_price),
                             (corrected[0].entry_time, corrected[0].exit_time, corrected[0].entry_price))
            self.assertEqual((original[0].exit_price, corrected[0].exit_price), (101, 100))
            for scenario in ("normal", "double"):
                old = replay_long_only_v2(original, context=build_v2_replay_context(original, bars, manifest=MANIFEST),
                                          manifest=MANIFEST, cost_scenario=scenario)
                new = replay_long_only_v2(corrected, context=build_v2_replay_context(corrected, view.bars_by_symbol, manifest=MANIFEST),
                                          manifest=MANIFEST, cost_scenario=scenario)
                self.assertEqual(old["manifest_hash"], new["manifest_hash"])
                self.assertEqual(old["cost_model"], new["cost_model"])
                self.assertEqual(old["constraints"], new["constraints"])
                self.assertNotEqual(old["final_equity"], new["final_equity"])
