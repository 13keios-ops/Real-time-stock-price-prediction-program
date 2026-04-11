"""Time utilities aligned with the KRX trading calendar assumptions."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
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
