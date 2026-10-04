"""Logical clock and ISO 8601 (three fractional digits) timestamp helpers."""

from datetime import datetime, timedelta, timezone

_STARTUP_DEFAULT = "2026-09-01T00:00:00.000Z"


def _fmt(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant (tolerating a trailing Z). Returns naive UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError("Unparseable ISO 8601 instant: %r" % (value,))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class Clock(object):
    """A single logical instant; never falls back to wall-clock time."""

    def __init__(self):
        self.now = parse_iso(_STARTUP_DEFAULT)

    def set(self, to_iso8601):
        self.now = parse_iso(to_iso8601)
        return self.now

    def advance_to(self, as_of_iso8601):
        dt = parse_iso(as_of_iso8601)
        if dt > self.now:
            self.now = dt
        return self.now

    def stamp(self):
        return _fmt(self.now)

    def plus_minutes(self, minutes):
        return _fmt(self.now + timedelta(minutes=minutes))

    def plus_hours(self, hours):
        return _fmt(self.now + timedelta(hours=hours))


CLOCK = Clock()