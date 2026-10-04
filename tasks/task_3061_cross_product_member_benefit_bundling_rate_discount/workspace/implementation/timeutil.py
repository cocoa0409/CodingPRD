"""ISO 8601 UTC timestamp helpers (three fractional digits) and logical-month maths."""

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M%z",
)


def parse_ts(value):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        dt = None
        for fmt in _FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_ts(dt):
    """Render a datetime as an ISO 8601 UTC instant.

    Whole-second instants (every logical-clock value the API accepts or derives)
    render without fractional digits, so a value that came in as
    "2026-09-01T00:00:00Z" round-trips byte-for-byte.
    """
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_ts(value):
    """Format a stored logical clock value."""
    return fmt_ts(value)


def month_index(dt):
    return dt.year * 12 + (dt.month - 1)


def month_start(index):
    year, month = divmod(index, 12)
    return datetime(year, month + 1, 1, 0, 0, 0, tzinfo=UTC)


def days_later(dt, days):
    return dt + timedelta(days=days)


def add_months(index, count):
    return index + count


def month_bounds(index):
    return month_start(index), month_start(index + 1)