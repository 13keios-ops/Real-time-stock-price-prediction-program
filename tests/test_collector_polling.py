from pathlib import Path
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
