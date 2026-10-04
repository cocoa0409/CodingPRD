"""Logical clock and temporal arithmetic.

PRD §2.4: the server holds a logical clock starting at 2026-09-01T00:00:00Z and
no deadline, expiry, window boundary, excursion SLA or appeal window is ever
evaluated against wall-clock time.  Everything below reads the logical clock.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from db import STORE
from errors import ApiError

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


def parse_ts(value):
    """Parse an ISO 8601 UTC instant.  Returns None for None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Timestamp is not a valid ISO 8601 instant: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """Render as an ISO 8601 UTC instant.

    A whole second is rendered without fractional digits; only a sub-second
    instant carries them.  That keeps a client-supplied instant that lands on a
    whole second round-tripping verbatim while a server-stamped instant keeps
    its millisecond precision.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def clock():
    """The current logical instant."""
    return parse_ts(STORE.current_utc)


def set_clock(value):
    dt = parse_ts(value)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "current_utc is required.")
    STORE.current_utc = fmt(dt)
    return dt


def add_hours(dt, hours):
    if dt is None:
        return None
    return dt + timedelta(hours=hours)


def add_minutes(dt, minutes):
    if dt is None:
        return None
    return dt + timedelta(minutes=minutes)


def add_days(dt, days):
    if dt is None:
        return None
    return dt + timedelta(days=days)


def diff_hours(later, earlier):
    """Whole-and-fractional hours between two instants (0.0 if either is None)."""
    if later is None or earlier is None:
        return 0.0
    return (later - earlier).total_seconds() / 3600.0


def diff_minutes(later, earlier):
    """Whole minutes between two instants, truncated toward zero."""
    if later is None or earlier is None:
        return 0
    return int((later - earlier).total_seconds() // 60)


def diff_hours_rounded(later, earlier, places=4):
    """Hours between two instants, rounded half up to `places` decimal places."""
    if later is None or earlier is None:
        return 0.0
    secs = Decimal(str((later - earlier).total_seconds()))
    q = secs / Decimal(3600)
    return float(q.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def earlier(*values):
    live = [v for v in values if v is not None]
    return min(live) if live else None


def round_half_up(value, places):
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def ceil_div(numerator, denominator):
    """Exact integer ceiling division -- never through floating point."""
    if denominator == 0:
        return 0
    if numerator <= 0:
        return 0
    return -(-numerator // denominator)


def floor_div(numerator, denominator):
    if denominator == 0:
        return 0
    return numerator // denominator


def is_sunday_first_index(dt):
    return dt.weekday()


def weekday_name(dt):
    return WEEKDAYS[dt.weekday()]