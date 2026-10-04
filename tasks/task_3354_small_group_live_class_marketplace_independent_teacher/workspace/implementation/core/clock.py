"""Logical clock, period accounting and timestamp helpers.

The server never consults wall-clock time: the current instant starts at
CURRENT_DEFAULT_UTC (2026-09-01T00:00:00Z) and only moves when a
PlatformAdmin calls POST /outschool/_clock/set_current_utc.
"""

from datetime import datetime, timedelta, timezone

CURRENT_DEFAULT_UTC = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
SECONDS_PER_PERIOD = 86400


class LogicalClock(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.current = CURRENT_DEFAULT_UTC
        self.period_index = 0

    def set_current(self, instant):
        """Move the clock. The period index never decreases."""
        self.current = instant
        elapsed = (instant - CURRENT_DEFAULT_UTC).total_seconds()
        index = int(elapsed // SECONDS_PER_PERIOD)
        if index < 0:
            index = 0
        if index > self.period_index:
            self.period_index = index
        return self.current

    def now(self):
        return self.current

    def period(self):
        return self.period_index


CLOCK = LogicalClock()


def now():
    return CLOCK.now()


def period():
    return CLOCK.period()


def parse_datetime(value):
    """Parse an ISO 8601 instant, tolerating 'Z', offsets and date-only forms."""
    if isinstance(value, datetime):
        return ensure_utc(value)
    if not isinstance(value, str):
        raise ValueError("not a datetime string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value.strip(), fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            raise ValueError("unparseable datetime: %r" % (value,))
    return ensure_utc(parsed)


def ensure_utc(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def try_parse_datetime(value):
    try:
        return parse_datetime(value)
    except (ValueError, TypeError):
        return None


def fmt(dt):
    """Server-generated timestamp: ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = ensure_utc(dt)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def whole_hours_between(later, earlier):
    """Whole hours between two instants, truncated down (floor)."""
    return int((later - earlier).total_seconds() // 3600)
