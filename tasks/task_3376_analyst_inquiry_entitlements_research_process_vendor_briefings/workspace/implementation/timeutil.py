"""ISO 8601 UTC helpers and the calendar rules pinned in PRD section 2.8 / 3.6.

PRD 2.8 pins timestamps to "second precision in UTC unless a field states
otherwise".  Only three fields state otherwise and carry three fractional
digits: ``created_at`` and ``updated_at`` (PRD 2.10) and
``api_request_timestamp`` (PRD 2.2).  Every other lifecycle instant is emitted
at second precision.  All calendar rolls are calendar-based, never
business-day based.
"""

from datetime import datetime, timedelta, timezone

FMT = "%Y-%m-%dT%H:%M:%S.%f"
FMT_SECONDS = "%Y-%m-%dT%H:%M:%SZ"


def format_dt(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits.

    Reserved for the fields that state their own precision: ``created_at``,
    ``updated_at`` (PRD 2.10) and ``api_request_timestamp`` (PRD 2.2).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime(FMT)[:-3] + "Z"


def format_dt_seconds(dt):
    """Render a lifecycle instant at second precision (PRD 2.8 default)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime(FMT_SECONDS)


def parse_dt(value):
    """Parse an ISO 8601 instant; returns None when the value is not parseable.

    Stored lifecycle fields are held as datetimes, so an already-parsed value is
    passed straight through.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def day_start(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def utc_date(dt):
    return dt.astimezone(timezone.utc).date()


def roll_forward_to_monday(dt):
    """Sat -> +2 days, Sun -> +1 day, otherwise unchanged (PRD 2.8)."""
    weekday = dt.weekday()  # Monday == 0 ... Sunday == 6
    if weekday == 5:
        return dt + timedelta(days=2)
    if weekday == 6:
        return dt + timedelta(days=1)
    return dt


def embargo_until(published_at, embargo_days):
    """published_at + embargo_days, weekend-rolled, at 00:00:00Z (PRD 3.6)."""
    landing = day_start(published_at + timedelta(days=embargo_days))
    return roll_forward_to_monday(landing)


def fact_check_due(requested_at):
    """T + 14 calendar days, weekend-rolled, at 23:59:59Z (PRD 2.8)."""
    raw = requested_at + timedelta(days=14)
    landing = roll_forward_to_monday(day_start(raw))
    return landing.replace(hour=23, minute=59, second=59, microsecond=0)


def add_days(dt, days):
    return dt + timedelta(days=days)
