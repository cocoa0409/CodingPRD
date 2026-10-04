"""The single logical clock (PRD 2.5). Starts at exactly 2026-09-01T00:00:00Z
and never falls back to wall-clock time."""
from datetime import datetime, timezone

from constants import CLOCK_START_ISO

_now = None


def _parse_start():
    return datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    global _now
    if _now is None:
        _now = _parse_start()
    return _now


def set_now(value):
    global _now
    _now = value


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def now_iso():
    return iso(now())


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None when unparseable. Naive inputs are treated as UTC.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
