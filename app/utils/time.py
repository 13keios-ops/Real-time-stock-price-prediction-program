"""Time utilities aligned with the KRX trading calendar assumptions."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def get_timezone(name: str) -> ZoneInfo:
    """Return a zoneinfo timezone for the configured name."""

    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name in {"Asia/Seoul", "KST"}:
            return timezone(timedelta(hours=9), name="KST")
        raise


def parse_hhmm(value: str) -> time:
    """Parse HH:MM text into a time object."""

    hour_text, minute_text = value.split(":", maxsplit=1)
    return time(hour=int(hour_text), minute=int(minute_text))


def now_local(timezone_name: str) -> datetime:
    """Return the current localized time."""

    return datetime.now(tz=get_timezone(timezone_name))


def is_market_holiday(market_calendar: Any, timestamp: datetime) -> bool:
    """Return whether the configured calendar marks the date as a market holiday."""

    holiday_dates = {str(value).strip() for value in getattr(market_calendar, "holidays", ()) if str(value).strip()}
    return timestamp.date().isoformat() in holiday_dates


def get_market_session_status(market_calendar: Any, timestamp: datetime) -> str:
    """Classify the timestamp as weekend, holiday, pre-open, regular-session, or post-close."""

    if timestamp.weekday() >= 5:
        return "weekend"
    if is_market_holiday(market_calendar, timestamp):
        return "holiday"

    current_time = timestamp.timetz().replace(tzinfo=None)
    session_open = parse_hhmm(market_calendar.session_open)
    session_close = parse_hhmm(market_calendar.session_close)
    if current_time < session_open:
        return "pre-open"
    if current_time > session_close:
        return "post-close"
    return "regular-session"
