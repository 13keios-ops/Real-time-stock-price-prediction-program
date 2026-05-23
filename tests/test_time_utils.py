from datetime import datetime
import unittest

from app.utils.time import get_market_session_status


class _Calendar:
    session_open = "09:00"
    session_close = "15:30"
    holidays: tuple[str, ...] = ()


class MarketSessionStatusTests(unittest.TestCase):
    def test_before_pre_open_warmup_is_overnight(self) -> None:
        self.assertEqual(
            get_market_session_status(_Calendar, datetime.fromisoformat("2026-05-21T00:30:00+09:00")),
            "overnight",
        )
        self.assertEqual(
            get_market_session_status(_Calendar, datetime.fromisoformat("2026-05-21T07:59:59+09:00")),
            "overnight",
        )

    def test_pre_open_is_only_the_warmup_window(self) -> None:
        self.assertEqual(
            get_market_session_status(_Calendar, datetime.fromisoformat("2026-05-21T08:00:00+09:00")),
            "pre-open",
        )
        self.assertEqual(
            get_market_session_status(_Calendar, datetime.fromisoformat("2026-05-21T08:59:59+09:00")),
            "pre-open",
        )

    def test_regular_and_post_close_statuses_are_unchanged(self) -> None:
        self.assertEqual(
            get_market_session_status(_Calendar, datetime.fromisoformat("2026-05-21T09:00:00+09:00")),
            "regular-session",
        )
        self.assertEqual(
            get_market_session_status(_Calendar, datetime.fromisoformat("2026-05-21T15:31:00+09:00")),
            "post-close",
        )

    def test_custom_warmup_minutes_can_expand_or_disable_pre_open(self) -> None:
        timestamp = datetime.fromisoformat("2026-05-21T07:30:00+09:00")

        self.assertEqual(get_market_session_status(_Calendar, timestamp), "overnight")
        self.assertEqual(get_market_session_status(_Calendar, timestamp, pre_open_warmup_minutes=120), "pre-open")
        self.assertEqual(get_market_session_status(_Calendar, timestamp, pre_open_warmup_minutes=0), "overnight")


if __name__ == "__main__":
    unittest.main()
