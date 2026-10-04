"""The server-owned logical clock (PRD 2.4). Never wall-clock; monotonic."""
from datetime import datetime, timezone

from constants import DEFAULT_CLOCK_ISO

_current = None  # datetime, lazily initialized to the fixed default


def _default():
    return datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    global _current
    if _current is None:
        _current = _default()
    return _current


def advance(dt):
    global _current
    _current = dt


def parse(value):
    """Parse an ISO 8601 string to an aware UTC datetime; None when invalid."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    """Canonical clock serialization: no fractional part when zero."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso_z(now())


def default_iso():
    return DEFAULT_CLOCK_ISO
