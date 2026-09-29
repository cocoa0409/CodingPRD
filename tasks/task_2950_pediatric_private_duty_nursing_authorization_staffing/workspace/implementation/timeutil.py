"""ISO-8601 parsing / formatting and ISO-week window helpers.

Canonical instant output form: YYYY-MM-DDTHH:MM:SS.mmmZ (exactly three
fractional digits, UTC, 'Z' suffix) -- PRD section 2.4.
"""
import re
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:[.,](\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None.

    Lenient about fractional-second width, ' ' vs 'T', a missing seconds
    component, an explicit numeric offset and a bare date (midnight UTC).
    """
    if isinstance(value, datetime):
        dt = value
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    m = _DATE_RE.match(s)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
    m = _INSTANT_RE.match(s)
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    off = m.group(8)
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def parse_date(value):
    """Parse a date-only YYYY-MM-DD value (an instant is accepted, date part used)."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    s = value.strip()
    m = _DATE_RE.match(s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    dt = parse_instant(s)
    return dt.date() if dt else None


def fmt_instant(dt):
    """Canonical ISO-8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.astimezone(UTC).date()
    return d.isoformat()


def week_start(dt):
    """Monday 00:00:00.000Z of the ISO-8601 week containing dt."""
    dt = dt.astimezone(UTC)
    midnight = datetime(dt.year, dt.month, dt.day, tzinfo=UTC)
    return midnight - timedelta(days=midnight.weekday())


def week_window(dt):
    ws = week_start(dt)
    return ws, ws + timedelta(days=7)


def in_window(instant, window):
    return window[0] <= instant < window[1]


def whole_minutes(start, end):
    return int((end - start).total_seconds() // 60)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
