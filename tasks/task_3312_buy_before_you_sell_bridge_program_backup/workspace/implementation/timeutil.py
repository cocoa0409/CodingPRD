"""Datetime helpers for the logical clock and ISO-8601 rendering.

Every timestamp this API emits is ISO 8601 UTC with exactly three fractional
digits (PRD 2.2/2.5), e.g. ``2026-09-01T00:00:00.000Z``.  Datetimes are handled
as timezone-aware UTC ``datetime`` objects throughout; the only place a
wall-clock time could enter is ``now_utc``, which is never used for business
logic.
"""

from datetime import datetime, timedelta, timezone


def parse_iso(value):
    """Parse a client-supplied instant into an aware UTC datetime.

    Accepts ``...Z`` and ``+00:00`` suffixes, with or without fractional
    seconds.  Returns ``None`` when the value is absent or unparseable so the
    caller can raise the appropriate typed error.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_days(dt, days):
    return dt + timedelta(days=days)


def now_utc():
    """Real wall-clock time.  Used only for envelope metadata, never for rules."""
    return datetime.now(timezone.utc)


def whole_months_between(start, end):
    """Count whole calendar months elapsed from ``start`` to ``end``.

    A month counts only once the same day-of-month has been reached; a negative
    span yields 0 so downstream interest arithmetic never goes backwards.
    """
    if start is None or end is None:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)