"""The logical clock. Never reads wall-clock time."""

from datetime import datetime, timedelta, timezone

from constants import CLOCK_DEFAULT_ISO


def parse_iso(text):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
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
        return None
    if dt.utcoffset() != timedelta(0):
        return None
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """Render an aware datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


_DEFAULT = parse_iso(CLOCK_DEFAULT_ISO)
_current = _DEFAULT


def now():
    return _current


def set_now(dt):
    global _current
    _current = dt


def reset():
    global _current
    _current = _DEFAULT


def wall_now():
    return datetime.now(timezone.utc)
