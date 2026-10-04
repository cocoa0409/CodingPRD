"""The single logical clock.

The network never consults wall-clock time; it reads this logical clock, whose
value before any administrative call is exactly 2026-09-01T00:00:00Z.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = "2026-09-01T00:00:00.000Z"


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime; None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Render an instant as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        parsed = parse_iso(dt)
        dt = parsed if parsed is not None else None
        if dt is None:
            return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class LogicalClock:
    def __init__(self):
        self.current_utc = parse_iso(DEFAULT_CLOCK)

    def set(self, value):
        parsed = parse_iso(value)
        if parsed is None:
            return False
        self.current_utc = parsed
        return True

    def now(self):
        return self.current_utc

    def minus_days(self, days):
        return self.current_utc - timedelta(days=days)