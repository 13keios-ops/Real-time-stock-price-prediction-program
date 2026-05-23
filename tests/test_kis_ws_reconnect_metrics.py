import unittest
from datetime import datetime, timezone

from app.brokers.kis_quote_ws import KisWebSocketReconnectMetrics, _emit_reconnect_snapshot


class KisWebSocketReconnectMetricsTests(unittest.TestCase):
    def _clock(self, *values: datetime):
        times = iter(values)
        return lambda: next(times)

    def test_consecutive_reconnects_reset_after_stable_frames(self) -> None:
        metrics = KisWebSocketReconnectMetrics(stable_frame_reset_threshold=2, reconnect_storm_threshold=2)

        first_drop = metrics.record_disconnected("drop-1")
        metrics.record_connected()
        no_reset_yet = metrics.record_frame()
        stable = metrics.record_frame()

        self.assertEqual(first_drop.cumulative_reconnects, 1)
        self.assertEqual(first_drop.consecutive_reconnects, 1)
        self.assertIsNone(no_reset_yet)
        self.assertIsNotNone(stable)
        self.assertEqual(stable.state, "stable")
        self.assertEqual(stable.cumulative_reconnects, 1)
        self.assertEqual(stable.consecutive_reconnects, 0)
        self.assertTrue(stable.stable_connection_seen)

    def test_reconnect_storm_uses_consecutive_reconnects_not_cumulative(self) -> None:
        metrics = KisWebSocketReconnectMetrics(stable_frame_reset_threshold=1, reconnect_storm_threshold=2)

        first_drop = metrics.record_disconnected("drop-1")
        second_drop = metrics.record_disconnected("drop-2")
        metrics.record_connected()
        stable = metrics.record_frame()
        third_drop = metrics.record_disconnected("drop-3")

        self.assertFalse(first_drop.reconnect_storm)
        self.assertTrue(second_drop.reconnect_storm)
        self.assertEqual(stable.consecutive_reconnects, 0)
        self.assertEqual(stable.cumulative_reconnects, 2)
        self.assertFalse(third_drop.reconnect_storm)
        self.assertEqual(third_drop.cumulative_reconnects, 3)
        self.assertEqual(third_drop.consecutive_reconnects, 1)

    def test_snapshot_records_reconnect_and_stable_timestamps(self) -> None:
        first_drop_at = datetime(2026, 5, 20, 9, 1, tzinfo=timezone.utc)
        connected_at = datetime(2026, 5, 20, 9, 2, tzinfo=timezone.utc)
        frame_at = datetime(2026, 5, 20, 9, 3, tzinfo=timezone.utc)
        stable_at = datetime(2026, 5, 20, 9, 4, tzinfo=timezone.utc)
        metrics = KisWebSocketReconnectMetrics(
            stable_frame_reset_threshold=2,
            reconnect_storm_threshold=2,
            clock=self._clock(first_drop_at, connected_at, frame_at, stable_at),
        )

        first_drop = metrics.record_disconnected("drop-1")
        connected = metrics.record_connected()
        self.assertIsNone(metrics.record_frame())
        stable = metrics.record_frame()

        self.assertEqual(first_drop.observed_at, first_drop_at)
        self.assertEqual(first_drop.last_reconnect_at, first_drop_at)
        self.assertIsNone(first_drop.last_stable_at)
        self.assertEqual(connected.observed_at, connected_at)
        self.assertIsNotNone(stable)
        self.assertEqual(stable.observed_at, stable_at)
        self.assertEqual(stable.last_reconnect_at, first_drop_at)
        self.assertEqual(stable.last_stable_at, stable_at)

    def test_storm_active_since_is_set_once_and_cleared_after_stable_connection(self) -> None:
        first_drop_at = datetime(2026, 5, 20, 9, 1, tzinfo=timezone.utc)
        storm_started_at = datetime(2026, 5, 20, 9, 2, tzinfo=timezone.utc)
        still_storm_at = datetime(2026, 5, 20, 9, 3, tzinfo=timezone.utc)
        connected_at = datetime(2026, 5, 20, 9, 4, tzinfo=timezone.utc)
        stable_at = datetime(2026, 5, 20, 9, 5, tzinfo=timezone.utc)
        metrics = KisWebSocketReconnectMetrics(
            stable_frame_reset_threshold=1,
            reconnect_storm_threshold=2,
            clock=self._clock(first_drop_at, storm_started_at, still_storm_at, connected_at, stable_at),
        )

        first_drop = metrics.record_disconnected("drop-1")
        second_drop = metrics.record_disconnected("drop-2")
        third_drop = metrics.record_disconnected("drop-3")
        metrics.record_connected()
        stable = metrics.record_frame()

        self.assertFalse(first_drop.reconnect_storm)
        self.assertIsNone(first_drop.storm_active_since)
        self.assertTrue(second_drop.reconnect_storm)
        self.assertEqual(second_drop.storm_active_since, storm_started_at)
        self.assertTrue(third_drop.reconnect_storm)
        self.assertEqual(third_drop.storm_active_since, storm_started_at)
        self.assertIsNotNone(stable)
        self.assertFalse(stable.reconnect_storm)
        self.assertIsNone(stable.storm_active_since)

    def test_snapshot_to_dict_is_json_serializable(self) -> None:
        observed_at = datetime(2026, 5, 20, 9, 1, tzinfo=timezone.utc)
        metrics = KisWebSocketReconnectMetrics(clock=self._clock(observed_at))

        snapshot = metrics.record_connected()
        payload = snapshot.to_dict()

        self.assertEqual(payload["state"], "connected")
        self.assertEqual(payload["observed_at"], "2026-05-20T09:01:00+00:00")
        self.assertIsNone(payload["last_reconnect_at"])
        self.assertIsNone(payload["last_stable_at"])
        self.assertIsNone(payload["storm_active_since"])

    def test_metrics_callback_error_does_not_break_stream(self) -> None:
        metrics = KisWebSocketReconnectMetrics()
        snapshot = metrics.record_connected()

        def fail_callback(_snapshot):
            raise RuntimeError("callback failed")

        with self.assertLogs("app.brokers.kis_quote_ws", level="WARNING"):
            _emit_reconnect_snapshot(fail_callback, snapshot)


if __name__ == "__main__":
    unittest.main()
