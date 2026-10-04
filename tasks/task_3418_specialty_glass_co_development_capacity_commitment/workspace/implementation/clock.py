"""The logical clock (PRD section 2.4).

The system runs on a logical clock, never on wall-clock time. Before any call
to the clock-setting endpoint the clock reads exactly CONST.DEFAULT_CLOCK_ISO.
"""
from datetime import datetime, timezone

from constants import DEFAULT_CLOCK_ISO

_current = None  # datetime, once set


def parse_iso(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    if _current is None:
        return parse_iso(DEFAULT_CLOCK_ISO)
    return _current


def set_current(dt):
    global _current
    _current = dt


def iso_ms(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)
