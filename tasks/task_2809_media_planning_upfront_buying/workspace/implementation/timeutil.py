"""Timestamp parsing and rendering (PRD 2.3, 2.4).

Every instant is UTC.  Rendered form is always
``YYYY-MM-DDTHH:MM:SS.mmmZ`` so the width never varies between responses.
"""

from datetime import datetime, timedelta, timezone


def parse_ts(text):
    """Parse an ISO-8601 UTC instant.  Returns an aware datetime or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Render an aware datetime with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_days(dt, days):
    return dt + timedelta(days=days)


def sub_days(dt, days):
    return dt - timedelta(days=days)
