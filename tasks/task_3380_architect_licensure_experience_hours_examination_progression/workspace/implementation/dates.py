"""Calendar arithmetic helpers. All deadline rules operate at day granularity
using calendar-month / calendar-day addition on ISO dates."""
import calendar
from datetime import date, timedelta


def parse_date(value):
    """Parse an ISO date string (YYYY-MM-DD). Raises ValueError otherwise."""
    if not isinstance(value, str):
        raise ValueError("not an ISO date string")
    return date.fromisoformat(value)


def fmt_date(d):
    return d.isoformat()


def add_days(d, n):
    return d + timedelta(days=n)


def add_months(d, months):
    """Calendar-month addition: same day-of-month N months later, clamped to
    the target month's last day when that day-of-month does not exist."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
