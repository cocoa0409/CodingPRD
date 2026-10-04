"""The logical clock.

PRD section 2.9: the system maintains a logical clock rather than reading real
wall-clock time.  Its starting value is exactly the first instant of
1 September 2026 in UTC and the server must never silently fall back to the
machine's real time.  PRD section 2.8: timestamps are ISO 8601 in UTC at
second precision.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# The logical clock is process-global state and is re-initialised on every
# fresh boot: start.sh restarts the interpreter for each per-test server.
_now = DEFAULT_CLOCK


def now():
    return _now


def set_now(value):
    global _now
    _now = value


def fmt(dt):
    """Render an instant as ISO 8601 UTC at second precision."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(value):
    """Parse any ISO 8601 instant into an aware UTC datetime.

    Accepts a trailing 'Z', an explicit offset, or a naive value (treated as
    UTC).  Returns None when the value cannot be interpreted.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
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


def days(n):
    return timedelta(days=n)


def hours(n):
    return timedelta(hours=n)