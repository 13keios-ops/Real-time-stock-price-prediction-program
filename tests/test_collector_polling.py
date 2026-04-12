from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from app.brokers.kis_auth import KisApiError
from app.services.collector import collect_kis_watchlist_snapshots
from app.services.collector import WatchlistSnapshotResult, poll_kis_watchlist_snapshots


class CollectorPollingTests(unittest.TestCase):
    @patch("app.services.collector.collect_kis_watchlist_snapshots")
    def test_polling_aggregates_iterations(self, mocked_collect) -> None:
        root = Path(__file__).resolve().parents[1]
        mocked_collect.side_effect = [
            WatchlistSnapshotResult(
                symbols_requested=["005930", "000660"],
                symbols_succeeded=["005930"],
                failed=[{"symbol": "000660", "error": "temporary"}],
                runtime_root=root / "runtime-data",
            ),
            WatchlistSnapshotResult(
                symbols_requested=["005930", "000660"],
                symbols_succeeded=["005930", "000660"],
                failed=[],
                runtime_root=root / "runtime-data",
            ),
        ]

        result = poll_kis_watchlist_snapshots(
            project_root=root,
            symbols=["005930", "000660"],
            iterations=2,
            interval_seconds=0,
        )

        self.assertEqual(result.iterations_completed, 2)
        self.assertEqual(result.success_events, 3)
        self.assertEqual(result.failure_events, 1)

    @patch("app.services.collector.time.sleep")
    @patch("app.services.collector.configure_logging")
    @patch("app.services.collector.orderbook_from_kis_quote")
    @patch("app.services.collector.market_tick_from_kis_quote")
    @patch("app.services.collector.RuntimeWriter.from_settings")
    @patch("app.services.collector.KisRestQuoteClient")
    @patch("app.services.collector.KisTokenManager")
    @patch("app.services.collector.get_active_kis_profile")
    @patch("app.services.collector.load_settings")
    def test_collect_retries_on_rate_limit(
        self,
        mocked_load_settings,
        mocked_get_profile,
        mocked_token_manager,
        mocked_client_cls,
        mocked_writer_factory,
        mocked_tick_factory,
        mocked_orderbook_factory,
        mocked_configure_logging,
        mocked_sleep,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / "runtime-data"
        mocked_load_settings.return_value = SimpleNamespace(
            runtime_data_dir=runtime_root,
            timezone="Asia/Seoul",
        )
        mocked_get_profile.return_value = SimpleNamespace()
        mocked_token_manager.return_value = SimpleNamespace()

        client = MagicMock()
        client.get_current_price.return_value = SimpleNamespace(current_price=70000)
        client.get_orderbook.side_effect = [
            KisApiError('KIS HTTP error 500: {"rt_cd":"1","msg1":"초당 거래건수를 초과하였습니다.","message":"EGW00201"}'),
            SimpleNamespace(ask_price_1=70010, bid_price_1=69990),
        ]
        mocked_client_cls.return_value = client

        writer = MagicMock()
        mocked_writer_factory.return_value = writer
        mocked_tick_factory.return_value = SimpleNamespace()
        mocked_orderbook_factory.return_value = SimpleNamespace()

        result = collect_kis_watchlist_snapshots(
            project_root=root,
            symbols=["005930"],
        )

        self.assertEqual(result.symbols_succeeded, ["005930"])
        self.assertEqual(result.failed, [])
        self.assertEqual(client.get_orderbook.call_count, 2)
        self.assertGreaterEqual(mocked_sleep.call_count, 2)
        writer.write_market_tick.assert_called_once()
        writer.write_orderbook_snapshot.assert_called_once()


if __name__ == "__main__":
    unittest.main()
