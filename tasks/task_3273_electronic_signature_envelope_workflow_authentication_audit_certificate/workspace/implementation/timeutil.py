"""Datetime helpers: ISO 8601 parsing/formatting and calendar arithmetic.

The logical clock and every stored datetime are ISO 8601 UTC with millisecond
precision. Calendar arithmetic (expiry, retention) is true calendar arithmetic
rather than a fixed number of seconds (PRD §2.9, §2.11).
"""

import calendar
from datetime import datetime, timedelta, timezone

from errors import ApiError, ERR_INVALID_REQUEST


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise ApiError(
                ERR_INVALID_REQUEST[0],
                "to_iso8601 is not a valid ISO 8601 instant",
                ERR_INVALID_REQUEST[1],
            )
    else:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "expected an ISO 8601 instant",
            ERR_INVALID_REQUEST[1],
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """Render an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_calendar_days(anchor, days):
    """Advance an instant by whole calendar days, keeping the time of day."""
    return anchor + timedelta(days=days)


def add_calendar_years(anchor, years):
    """Advance an instant by whole calendar years (Feb 29 -> Feb 28)."""
    try:
        return anchor.replace(year=anchor.year + years)
    except ValueError:
        return anchor.replace(year=anchor.year + years, day=28)


def add_business_days(anchor, days):
    """Advance an instant by whole business days, skipping Sat and Sun."""
    remaining = days
    cursor = anchor
    while remaining > 0:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() < 5:  # Mon..Fri
            remaining -= 1
    return cursor


def at_end_of_day(anchor):
    """Pin an instant to 23:59:59Z on its own (UTC) calendar day."""
    return anchor.replace(hour=23, minute=59, second=59, microsecond=0)


def at_start_of_day(anchor):
    """Pin an instant to 00:00:00Z on its own (UTC) calendar day."""
    return anchor.replace(hour=0, minute=0, second=0, microsecond=0)


def days_in_month(year, month):
    return calendar.monthrange(year, month)[1]