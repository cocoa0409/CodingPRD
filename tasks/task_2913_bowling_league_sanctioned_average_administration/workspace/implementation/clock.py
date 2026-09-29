"""The logical clock (PRD 2.4). Never reads wall-clock time."""

from datetime import datetime, timezone, timedelta

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_NOW

    def now(self):
        return self._now

    def set(self, instant):
        self._now = instant

    def reset(self):
        self._now = DEFAULT_NOW

    def iso(self):
        return to_iso(self._now)


clock = LogicalClock()


def to_iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO-8601 instant that carries an explicit UTC offset.

    Returns None when the value is not a parseable, offset-carrying instant.
    """
    if not isinstance(value, str) or value.strip() == "":
        return None
    text = value.strip()
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def plus_hours(dt, hours):
    if dt is None:
        return None
    return dt + timedelta(hours=hours)


def elapsed_whole_days(start, end):
    """Whole 24-hour days between two instants, discarding any partial day."""
    if start is None or end is None:
        return 0
    seconds = (end - start).total_seconds()
    if seconds < 0:
        seconds = 0.0
    return int(seconds // 86400)
