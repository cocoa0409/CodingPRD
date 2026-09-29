"""Logical clock, calendar-date / instant shapes and the business-day calendar.

PRD 2.5: every deadline, window, timeliness judgement and "not in the future"
check reads a server-side logical clock rather than real wall-clock time.
Before the clock has ever been set it reads exactly 2026-08-01T00:00:00Z and it
never falls back to wall-clock time.
"""

import re
from datetime import date, datetime, timedelta, timezone

# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

_STATE = {"now": None}


def reset_clock():
    _STATE["now"] = None


def set_clock(instant):
    _STATE["now"] = instant


def now():
    """The current logical instant (never wall clock)."""
    cur = _STATE["now"]
    if cur is None:
        return DEFAULT_CLOCK
    return cur


def today():
    """The UTC calendar date of the logical clock instant."""
    return now().date()


def stamp():
    """The logical clock rendered as an instant string."""
    return fmt_instant(now())


# --------------------------------------------------------------------------
# Shapes: calendar dates (YYYY-MM-DD) and instants (3 fractional digits)
# --------------------------------------------------------------------------

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.(\d{1,9}))?"
    r"([Zz]|[+-]\d{2}:?\d{2})$"
)


def parse_date(value):
    """Strict ISO 8601 calendar date. Returns a date or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_instant(value):
    """ISO 8601 UTC datetime. Returns an aware datetime in UTC or None."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value)
    if not m:
        return None
    frac = m.group(8) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        naive = datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)), micro,
        )
    except ValueError:
        return None
    off = m.group(9)
    if off in ("Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if off[0] == "+" else -1
    body = off[1:].replace(":", "")
    delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * delta).replace(tzinfo=timezone.utc)


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


# --------------------------------------------------------------------------
# The business-day calendar (PRD 2.5)
# --------------------------------------------------------------------------

FEDERAL_HOLIDAYS = frozenset(
    [
        # 2025
        date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17),
        date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4),
        date(2025, 9, 1), date(2025, 10, 13), date(2025, 11, 11),
        date(2025, 11, 27), date(2025, 12, 25),
        # 2026
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
        date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3),
        date(2026, 9, 7), date(2026, 10, 12), date(2026, 11, 11),
        date(2026, 11, 26), date(2026, 12, 25),
        # 2027
        date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15),
        date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5),
        date(2027, 9, 6), date(2027, 10, 11), date(2027, 11, 11),
        date(2027, 11, 25), date(2027, 12, 24),
    ]
)


def is_business_day(d):
    """Neither Saturday nor Sunday and not a recognised federal holiday."""
    if d.weekday() >= 5:
        return False
    return d not in FEDERAL_HOLIDAYS


def business_days_between(start, end):
    """Count business days strictly after `start` through `end` inclusive.

    The interval is open on the left and closed on the right: the starting date
    never contributes and the ending date always contributes when it is a
    business day.
    """
    if start is None or end is None:
        return 0
    if end <= start:
        return 0
    count = 0
    cur = start + timedelta(days=1)
    while cur <= end:
        if is_business_day(cur):
            count += 1
        cur += timedelta(days=1)
    return count


def nth_business_day_after(start, n):
    """The n-th business day after `start` (walk forward from start + 1 day)."""
    cur = start + timedelta(days=1)
    seen = 0
    while True:
        if is_business_day(cur):
            seen += 1
            if seen == n:
                return cur
        cur += timedelta(days=1)


def nth_business_day_of_month(year, month, n):
    """The n-th business day of a calendar month (walk forward from the 1st)."""
    cur = date(year, month, 1)
    seen = 0
    while True:
        if is_business_day(cur):
            seen += 1
            if seen == n:
                return cur
        cur += timedelta(days=1)


def add_months(year, month, count):
    total = (year * 12 + (month - 1)) + count
    return total // 12, (total % 12) + 1


def last_day_of_month(year, month):
    ny, nm = add_months(year, month, 1)
    return date(ny, nm, 1) - timedelta(days=1)


def roll_forward_to_business_day(d):
    """Roll forward one day at a time until the date is a business day."""
    cur = d
    while not is_business_day(cur):
        cur += timedelta(days=1)
    return cur


def quarter_of(d):
    return (d.month - 1) // 3 + 1
