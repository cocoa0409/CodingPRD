"""Money, percentage and calendar primitives.

All monetary amounts are integer counts of cents. Every division rounds
half-up (away from zero at the midpoint) to whole cents. Percentages are
applied by multiplying by the percentage figure and dividing by one hundred.
"""
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

HUNDRED = Decimal(100)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up (away from zero at the midpoint) to `places` decimals."""
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def pct_of(amount, pct):
    """round_half_up(amount * pct / 100) in whole cents."""
    return rhu_int(dec(amount) * dec(pct) / HUNDRED)


def parse_date(value):
    """Strict YYYY-MM-DD. Returns None when malformed."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        y, m, d = value.split("-")
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def add_days(d, n):
    return d + timedelta(days=n)


def add_years(d, n):
    """Add whole calendar years, clamping the day of month (Feb 29 -> Feb 28)."""
    year = d.year + n
    month = d.month
    day = d.day
    while day > 1:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, 1)


def inclusive_days(start, end):
    """Number of days in the closed interval [start, end]."""
    return (end - start).days + 1


def whole_months(start, end):
    """Whole calendar months from `start` to `end`; never negative."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def month_span_inclusive(start, end):
    """(y2-y1)*12 + (m2-m1) + 1 — the start month itself counts as elapsed."""
    return (end.year - start.year) * 12 + (end.month - start.month) + 1
