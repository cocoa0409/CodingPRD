"""ISO-8601 UTC instant parsing and emission.

PRD 2.5: "All datetime-valued fields anywhere in this specification, whether
supplied by the caller or computed by the server, are ISO 8601 instants in UTC.
Server-written instants are emitted with three fractional digits."
"""
from datetime import datetime, timedelta, timezone

__all__ = ["parse_instant", "fmt_instant", "add_minutes", "add_hours", "add_days"]


def parse_instant(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None if unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_instant(moment):
    """Emit an aware datetime as an ISO-8601 UTC instant with three fractional digits."""
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
    )


def add_minutes(moment, minutes):
    return moment + timedelta(minutes=minutes)


def add_hours(moment, hours):
    return moment + timedelta(hours=hours)


def add_days(moment, days):
    return moment + timedelta(days=days)
