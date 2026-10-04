"""Logical clock helpers (PRD section 2.12).

The service never reads wall-clock time. The logical clock starts at
2026-09-01T00:00:00Z and moves only forward, and only when a CatalogAdmin
advances it through POST /catalog/_clock/set_current_utc.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def parse_instant(value):
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string instant")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def tried_instant(value):
    try:
        return parse_instant(value)
    except Exception:
        return None


def fmt(dt):
    """ISO 8601 UTC with three fractional digits (PRD section 2.5)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def whole_days(start, end):
    """Whole days between two instants, truncated toward zero."""
    return int((end - start).total_seconds() // 86400)


def term_months(start, end):
    """Whole calendar months between two instants (year-month ordinals)."""
    return (end.year * 12 + end.month) - (start.year * 12 + start.month)


def month_start(dt):
    return datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)


def next_month_start(dt):
    if dt.month == 12:
        return datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(dt.year, dt.month + 1, 1, tzinfo=timezone.utc)


def add_months(dt, count):
    ordinal = dt.year * 12 + (dt.month - 1) + count
    year, month = divmod(ordinal, 12)
    day = min(dt.day, 28)
    return dt.replace(year=year, month=month + 1, day=day)


def q2(value):
    """Quantise to two decimals, round half up, as a float."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def q4(value):
    """Quantise to four decimals, round half up, as a float."""
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
