"""The logical settlement clock (PRD section 2.5).

It starts at exactly 2026-08-01T00:00:00Z on every server boot and moves only
when an operator sets it.  Real wall-clock time is never consulted.
"""
from datetime import datetime, timedelta, timezone

EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = EPOCH


def now():
    return _now


def set_now(value):
    global _now
    _now = value
    return _now


def reset():
    global _now
    _now = EPOCH
    return _now


def iso(value):
    """Render an aware datetime as ISO-8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def now_iso():
    return iso(_now)


def plus_days(value, days):
    return value + timedelta(days=days)
