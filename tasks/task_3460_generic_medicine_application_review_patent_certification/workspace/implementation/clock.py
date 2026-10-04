"""Logical clock, calendar arithmetic, and decimal rounding (PRD 2.4 / 2.9)."""
import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# Before any administrative action the logical clock reads exactly this instant.
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def today():
    """The current logical calendar date (UTC date part of the clock instant)."""
    return _clock.date()


def fmt_instant(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_instant(_clock)


def parse_instant(s):
    """Parse an ISO 8601 instant to an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Strict YYYY-MM-DD parse to a date. Raises ValueError."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise ValueError("not a YYYY-MM-DD date")
    return date.fromisoformat(s)


def add_months(d, n):
    """Add n calendar months, clamping the day to the target month's last day.

    Example: add_months(2027-01-31, 10) == 2027-11-30.
    """
    total = d.year * 12 + (d.month - 1) + n
    y, m0 = divmod(total, 12)
    m = m0 + 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def add_days(d, n):
    """Plain calendar-day addition, no clamping."""
    return d + timedelta(days=n)


def round2(x):
    """Round-half-up to exactly 2 decimal places (per-bound, before compare)."""
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
