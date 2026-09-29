"""Logical clock, ISO-8601 helpers and rounding discipline.

PRD 2.5: every temporal rule reads a single server-side logical clock which
never falls back to real wall-clock time.  At startup it reads exactly
2026-08-01T00:00:00.000Z.

PRD 2.8: money is integer cents, rates are rounded half up, percentages carry
exactly one decimal place (also half up), seat losses are floored.
"""

import re
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

CLOCK_STARTUP_INSTANT = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)


class LogicalClock(object):
    def __init__(self):
        self.current = CLOCK_STARTUP_INSTANT

    def now(self):
        return self.current

    def today(self):
        return self.current.astimezone(UTC).date()

    def now_iso(self):
        return fmt_instant(self.current)

    def set(self, instant):
        self.current = instant.astimezone(UTC)


clock = LogicalClock()


# --------------------------------------------------------------------------
# ISO-8601 formatting / parsing
# --------------------------------------------------------------------------

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_instant(value):
    """Parse an ISO-8601 instant.  Returns None when malformed."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset is None or offset in ("Z", "z"):
        return naive.replace(tzinfo=UTC)
    sign = 1 if offset[0] == "+" else -1
    body = offset[1:].replace(":", "")
    try:
        off_hours = int(body[:2])
        off_minutes = int(body[2:4])
    except ValueError:
        return None
    delta = timedelta(hours=off_hours, minutes=off_minutes) * sign
    return (naive - delta).replace(tzinfo=UTC)


def parse_date(value):
    """Parse an ISO calendar date (YYYY-MM-DD).  Returns None when malformed."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def date_of(dt):
    """Calendar date of an instant, in UTC."""
    if dt is None:
        return None
    return dt.astimezone(UTC).date()


def add_days(d, days):
    return d + timedelta(days=days)


# --------------------------------------------------------------------------
# Rounding
# --------------------------------------------------------------------------

def round_half_up(value):
    """Round a Decimal/int/float to a whole number of cents, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate_cents(base_cents, rate):
    """base_cents * rate rounded half up to whole cents."""
    return round_half_up(Decimal(int(base_cents)) * Decimal(str(rate)))


def pct_one_dp(numerator, denominator):
    """100 * numerator / denominator with exactly one decimal place, half up."""
    if denominator in (0, None):
        return 0.0
    value = (Decimal(int(numerator)) * Decimal(100)) / Decimal(int(denominator))
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def floor_div_rate(seats, remaining_rate):
    """seats * remaining_rate taken down to the next whole seat."""
    value = Decimal(int(seats)) * Decimal(str(remaining_rate))
    return int(value.to_integral_value(rounding="ROUND_FLOOR"))
