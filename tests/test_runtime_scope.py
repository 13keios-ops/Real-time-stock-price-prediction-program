import os
from datetime import datetime
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from app.config.settings import load_settings
from app.services.runtime_scope import build_runtime_scope, filter_actual_rows
from app.storage.contracts import MarketTickEvent, MinuteBar
from app.storage.runtime_writer import get_sqlite_store


class RuntimeScopeTests(unittest.TestCase):
    def test_runtime_scope_excludes_out_of_session_kis_rows(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "runtime-scope" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            sqlite_store = get_sqlite_store(settings)

            assert sqlite_store is not None
            sqlite_store.insert_market_tick(
                MarketTickEvent(
                    symbol="005930",
                    event_time=datetime.fromisoformat("2026-04-12T16:44:43+09:00"),
                    price=206000.0,
                    volume=18244459,
                    source="kis-rest",
                )
            )
            sqlite_store.insert_market_tick(
                MarketTickEvent(
                    symbol="005930",
                    event_time=datetime.fromisoformat("2026-05-01T10:43:58+09:00"),
                    price=204000.0,
                    volume=120,
                    source="kis-ws",
                )
            )
            sqlite_store.insert_market_tick(
                MarketTickEvent(
                    symbol="005930",
                    event_time=datetime.fromisoformat("2026-04-13T10:43:58+09:00"),
                    price=203000.0,
                    volume=470,
                    source="kis-ws",
                )
            )
            sqlite_store.insert_market_tick(
                MarketTickEvent(
                    symbol="005930",
                    event_time=datetime.fromisoformat("2026-04-13T10:44:58+09:00"),
                    price=203500.0,
                    volume=470,
                    source="cybos-historical",
                )
            )
            sqlite_store.upsert_minute_bar(
                MinuteBar(
                    symbol="005930",
                    bar_time=datetime.fromisoformat("2026-04-12T16:44:00+09:00"),
                    open=206000.0,
                    high=206000.0,
                    low=206000.0,
                    close=206000.0,
                    volume=18244459,
                    trade_count=1,
                )
            )
            sqlite_store.upsert_minute_bar(
                MinuteBar(
                    symbol="005930",
                    bar_time=datetime.fromisoformat("2026-05-01T10:43:00+09:00"),
                    open=204000.0,
                    high=204000.0,
                    low=203500.0,
                    close=203800.0,
                    volume=120,
                    trade_count=4,
                )
            )
            sqlite_store.upsert_minute_bar(
                MinuteBar(
                    symbol="005930",
                    bar_time=datetime.fromisoformat("2026-04-13T10:43:00+09:00"),
                    open=203000.0,
                    high=203000.0,
                    low=202750.0,
                    close=203000.0,
                    volume=470,
                    trade_count=14,
                )
            )
            sqlite_store.upsert_minute_bar(
                MinuteBar(
                    symbol="005930",
                    bar_time=datetime.fromisoformat("2026-04-13T10:44:00+09:00"),
                    open=203500.0,
                    high=203500.0,
                    low=203250.0,
                    close=203500.0,
                    volume=470,
                    trade_count=14,
                )
            )

            scope = build_runtime_scope(sqlite_store, settings)
            minute_rows = [dict(row) for row in sqlite_store.fetch_all_rows("curated_minute_bars", "bar_time")]
            filtered_rows = filter_actual_rows("curated_minute_bars", minute_rows, scope)

        self.assertIn(("005930", "2026-04-13T10:43"), scope.actual_symbol_minutes)
        self.assertNotIn(("005930", "2026-04-12T16:44"), scope.actual_symbol_minutes)
        self.assertNotIn(("005930", "2026-05-01T10:43"), scope.actual_symbol_minutes)
        self.assertNotIn(("005930", "2026-04-13T10:44"), scope.actual_symbol_minutes)
        self.assertEqual(scope.actual_raw_counts_by_table["raw_market_ticks"][("005930", "2026-04-13T10:43")], 1)
        self.assertEqual([row["bar_time"] for row in filtered_rows], ["2026-04-13T10:43:00+09:00"])

    def test_runtime_scope_can_limit_raw_counts_to_period(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "runtime-scope" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            sqlite_store = get_sqlite_store(settings)

            assert sqlite_store is not None
            sqlite_store.insert_market_tick(
                MarketTickEvent(
                    symbol="005930",
                    event_time=datetime.fromisoformat("2026-04-13T10:43:58+09:00"),
                    price=203000.0,
                    volume=470,
                    source="kis-ws",
                )
            )
            sqlite_store.insert_market_tick(
                MarketTickEvent(
                    symbol="005930",
                    event_time=datetime.fromisoformat("2026-04-14T10:43:58+09:00"),
                    price=204000.0,
                    volume=120,
                    source="kis-ws",
                )
            )

            scope = build_runtime_scope(
                sqlite_store,
                settings,
                start_at="2026-04-14T00:00:00+09:00",
                end_at="2026-04-15T00:00:00+09:00",
            )

        self.assertNotIn(("005930", "2026-04-13T10:43"), scope.actual_symbol_minutes)
        self.assertIn(("005930", "2026-04-14T10:43"), scope.actual_symbol_minutes)
        self.assertEqual(scope.actual_raw_counts_by_table["raw_market_ticks"][("005930", "2026-04-14T10:43")], 1)

    def test_runtime_scope_can_use_curated_minute_bars_for_dashboard_scope(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "runtime-scope" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            sqlite_store = get_sqlite_store(settings)

            assert sqlite_store is not None
            sqlite_store.upsert_minute_bar(
                MinuteBar(
                    symbol="005930",
                    bar_time=datetime.fromisoformat("2026-04-13T10:43:00+09:00"),
                    open=203000.0,
                    high=203000.0,
                    low=202750.0,
                    close=203000.0,
                    volume=470,
                    trade_count=14,
                )
            )

            scope = build_runtime_scope(
                sqlite_store,
                settings,
                start_at="2026-04-13T00:00:00+09:00",
                end_at="2026-04-14T00:00:00+09:00",
                source="curated_minute_bars",
            )

        self.assertIn(("005930", "2026-04-13T10:43"), scope.actual_symbol_minutes)
        self.assertEqual(scope.actual_raw_counts_by_table["raw_market_ticks"], {})

    def test_runtime_scope_reveals_minute_bar_builder_lag(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "runtime-scope" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }

        with patch.dict(os.environ, env, clear=False):
            settings = load_settings(project_root=root)
            sqlite_store = get_sqlite_store(settings)

            assert sqlite_store is not None
            sqlite_store.insert_market_tick(
                MarketTickEvent(
                    symbol="005930",
                    event_time=datetime.fromisoformat("2026-04-13T10:43:58+09:00"),
                    price=203000.0,
                    volume=470,
                    source="kis-ws",
                )
            )
            sqlite_store.insert_market_tick(
                MarketTickEvent(
                    symbol="005930",
                    event_time=datetime.fromisoformat("2026-04-13T10:44:58+09:00"),
                    price=203500.0,
                    volume=510,
                    source="kis-ws",
                )
            )
            sqlite_store.upsert_minute_bar(
                MinuteBar(
                    symbol="005930",
                    bar_time=datetime.fromisoformat("2026-04-13T10:43:00+09:00"),
                    open=203000.0,
                    high=203000.0,
                    low=202750.0,
                    close=203000.0,
                    volume=470,
                    trade_count=14,
                )
            )

            raw_scope = build_runtime_scope(
                sqlite_store,
                settings,
                start_at="2026-04-13T00:00:00+09:00",
                end_at="2026-04-14T00:00:00+09:00",
            )
            curated_scope = build_runtime_scope(
                sqlite_store,
                settings,
                start_at="2026-04-13T00:00:00+09:00",
                end_at="2026-04-14T00:00:00+09:00",
                source="curated_minute_bars",
            )

        self.assertIn(("005930", "2026-04-13T10:44"), raw_scope.actual_symbol_minutes)
        self.assertNotIn(("005930", "2026-04-13T10:44"), curated_scope.actual_symbol_minutes)
        self.assertGreater(max(raw_scope.actual_global_minutes), max(curated_scope.actual_global_minutes))


if __name__ == "__main__":
    unittest.main()
