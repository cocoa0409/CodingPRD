"""The logical compliance clock (PRD section 2.5) plus instant helpers.

Before the clock has ever been set it reads exactly 2026-08-01T00:00:00.000Z.
The server never falls back to real wall-clock time for any domain instant.
"""

import calendar
from datetime import datetime, timedelta, timezone
from fractions import Fraction

UTC = timezone.utc
STARTUP_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

_current = STARTUP_DEFAULT


def now():
    return _current


def set_now(dt):
    global _current
    _current = dt
    return _current


def reset():
    global _current
    _current = STARTUP_DEFAULT


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    # canonicalise to millisecond resolution so what is stored is what is served
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    """Calendar-month arithmetic preserving day-of-month, clamping to the
    target month's last day, with the time of day unchanged."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


_MICROS_PER_DAY = 86400 * 10 ** 6


def days_between_exact(start, end):
    """Exact rational number of days between two instants."""
    delta = end - start
    micros = (delta.days * 86400 + delta.seconds) * 10 ** 6 + delta.microseconds
    return Fraction(micros, _MICROS_PER_DAY)


def ceil_days(start, end):
    """Whole days between two instants, rounded up to the next whole day."""
    exact = days_between_exact(start, end)
    whole = exact.numerator // exact.denominator
    if exact != whole:
        whole += 1
    return whole
