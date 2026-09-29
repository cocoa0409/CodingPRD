"""ISO-8601 UTC instant parsing and rendering.

PRD 2.4: every persisted instant is rendered with exactly three fractional-second
digits and a trailing Z.
"""
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
DAY = timedelta(days=1)


def parse_instant(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None if unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # datetime.fromisoformat on 3.11+ accepts a trailing Z, but normalise anyway.
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date_only(value):
    """Parse a YYYY-MM-DD date (or a full instant) and return its UTC date."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC).date()
    except ValueError:
        pass
    dt = parse_instant(text)
    return dt.date() if dt is not None else None


def fmt_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def is_minute_aligned(dt):
    return dt.second == 0 and dt.microsecond == 0


WEEKDAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def weekday_name(dt):
    return WEEKDAY_NAMES[dt.astimezone(UTC).weekday()]


def days_between(later, earlier):
    """Plain calendar-date difference in whole days (later - earlier)."""
    return (later.astimezone(UTC).date() - earlier.astimezone(UTC).date()).days
