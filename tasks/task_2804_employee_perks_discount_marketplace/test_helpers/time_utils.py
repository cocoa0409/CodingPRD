"""Logical-clock arithmetic helpers.

PRD §2.4 evaluates every window, deadline, time-to-live and decay interval
against a logical clock the tests set explicitly, so all temporal reasoning in
this suite is plain ISO-8601 arithmetic.

PRD §2.5 says stored timestamps are "an ISO 8601 UTC timestamp with three
fractional digits", so `canonical_iso` normalises any well-formed instant to
that shape and `iso_equal` compares two instants by value rather than by
spelling.  That keeps a test from failing merely because one side wrote
`2026-08-01T00:00:00Z` and the other `2026-08-01T00:00:00.000Z`.
"""
from datetime import datetime, timedelta, timezone

ISO_MILLIS = "%Y-%m-%dT%H:%M:%S.%f"


def parse_iso(value):
    """Parse any ISO-8601 UTC instant the API may emit into a datetime."""
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_iso(moment):
    """Render a datetime as an ISO-8601 UTC instant with three fractionals."""
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return moment.strftime(ISO_MILLIS)[:-3] + "Z"


def canonical_iso(value):
    """Normalise an instant to `YYYY-MM-DDTHH:MM:SS.mmmZ`."""
    if value is None:
        return None
    return format_iso(parse_iso(value))


def iso_equal(left, right):
    """True when two ISO instants denote the same moment."""
    if left is None or right is None:
        return left is None and right is None
    return parse_iso(left) == parse_iso(right)


def shift_iso(value, days=0, hours=0, minutes=0, seconds=0, milliseconds=0):
    """Offset an ISO instant by a signed duration."""
    moment = parse_iso(value) + timedelta(
        days=days, hours=hours, minutes=minutes,
        seconds=seconds, milliseconds=milliseconds,
    )
    return format_iso(moment)


def plus_days(value, days):
    return shift_iso(value, days=days)


def plus_hours(value, hours):
    return shift_iso(value, hours=hours)


def plus_seconds(value, seconds):
    return shift_iso(value, seconds=seconds)


def minus_days(value, days):
    return shift_iso(value, days=-days)


def minus_hours(value, hours):
    return shift_iso(value, hours=-hours)


def iso_seconds_between(earlier, later):
    """Elapsed whole seconds from `earlier` to `later` (may be negative)."""
    return int((parse_iso(later) - parse_iso(earlier)).total_seconds())
