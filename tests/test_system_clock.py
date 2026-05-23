import unittest
from datetime import datetime, timedelta, timezone

from app.services.system_clock import (
    DEFAULT_MAX_CLOCK_SKEW_SECONDS,
    evaluate_clock_skew,
    evaluate_clock_skew_from_http_date_header,
    reference_time_from_http_date_header,
)


class SystemClockTests(unittest.TestCase):
    def test_allows_clock_inside_default_two_second_window(self) -> None:
        reference = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
        local = reference + timedelta(seconds=DEFAULT_MAX_CLOCK_SKEW_SECONDS)

        decision = evaluate_clock_skew(local_time=local, reference_time=reference)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.blocking_reasons, ())
        self.assertEqual(decision.skew_seconds, 2.0)

    def test_blocks_clock_outside_window(self) -> None:
        reference = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
        local = reference + timedelta(seconds=2.1)

        decision = evaluate_clock_skew(local_time=local, reference_time=reference)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocking_reasons, ("system_clock_skew_exceeded",))
        self.assertEqual(decision.skew_seconds, 2.1)

    def test_normalizes_naive_timestamps_as_utc(self) -> None:
        reference = datetime(2026, 5, 18, 9, 0)
        local = datetime(2026, 5, 18, 9, 0, 1)

        decision = evaluate_clock_skew(local_time=local, reference_time=reference)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.local_time.tzinfo, timezone.utc)
        self.assertEqual(decision.reference_time.tzinfo, timezone.utc)

    def test_custom_limit_can_tighten_window(self) -> None:
        reference = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
        local = reference + timedelta(seconds=1.5)

        decision = evaluate_clock_skew(local_time=local, reference_time=reference, max_skew_seconds=1.0)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.max_skew_seconds, 1.0)

    def test_extracts_reference_time_from_kis_rest_http_date_header(self) -> None:
        reference = reference_time_from_http_date_header(
            {"date": "Wed, 20 May 2026 00:00:01 GMT"},
        )

        self.assertIsNotNone(reference)
        self.assertEqual(reference.source, "kis_rest_http_date")
        self.assertEqual(reference.raw_value, "Wed, 20 May 2026 00:00:01 GMT")
        self.assertEqual(reference.reference_time, datetime(2026, 5, 20, 0, 0, 1, tzinfo=timezone.utc))

    def test_http_date_header_matching_is_case_insensitive(self) -> None:
        reference = reference_time_from_http_date_header(
            [("Date", "Wed, 20 May 2026 09:00:00 GMT")],
            source="fixture_http_date",
        )

        self.assertIsNotNone(reference)
        self.assertEqual(reference.source, "fixture_http_date")
        self.assertEqual(reference.reference_time, datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc))

    def test_missing_http_date_header_returns_none(self) -> None:
        self.assertIsNone(reference_time_from_http_date_header({"tr_cont": ""}))

    def test_invalid_http_date_header_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            reference_time_from_http_date_header({"date": "not-a-date"})

    def test_http_date_without_timezone_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must include a timezone"):
            reference_time_from_http_date_header({"date": "Wed, 20 May 2026 09:00:00"})

    def test_http_date_with_unknown_timezone_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must include a timezone"):
            reference_time_from_http_date_header({"date": "Wed, 20 May 2026 09:00:00 KST"})

    def test_http_date_with_numeric_offset_is_normalized_to_utc(self) -> None:
        reference = reference_time_from_http_date_header({"date": "Wed, 20 May 2026 18:00:00 +0900"})

        self.assertIsNotNone(reference)
        self.assertEqual(reference.reference_time, datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc))

    def test_http_date_reference_can_feed_clock_skew_decision(self) -> None:
        reference = reference_time_from_http_date_header({"date": "Wed, 20 May 2026 09:00:00 GMT"})
        self.assertIsNotNone(reference)

        decision = evaluate_clock_skew(
            local_time=datetime(2026, 5, 20, 9, 0, 1, tzinfo=timezone.utc),
            reference_time=reference.reference_time,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.skew_seconds, 1.0)

    def test_evaluates_clock_skew_directly_from_http_date_header(self) -> None:
        decision = evaluate_clock_skew_from_http_date_header(
            {"date": "Wed, 20 May 2026 09:00:00 GMT"},
            local_time=datetime(2026, 5, 20, 9, 0, 3, tzinfo=timezone.utc),
        )

        self.assertIsNotNone(decision)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocking_reasons, ("system_clock_skew_exceeded",))

    def test_missing_http_date_header_cannot_create_clock_decision(self) -> None:
        self.assertIsNone(
            evaluate_clock_skew_from_http_date_header(
                {"tr_cont": ""},
                local_time=datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc),
            )
        )


if __name__ == "__main__":
    unittest.main()
