"""The single logical clock.

The server starts at the fixed default instant and never falls back to
wall-clock time; every temporal verdict is rendered against this value.
"""

from .constants import DEFAULT_CLOCK_ISO
from .utils import format_instant, parse_datetime

_clock = {"current": parse_datetime(DEFAULT_CLOCK_ISO)}


def now():
    """Current reading of the logical clock (timezone-aware UTC datetime)."""
    return _clock["current"]


def current_iso():
    return format_instant(_clock["current"])


def set_current(value):
    """Set the clock from an ISO 8601 instant; returns the new reading."""
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    _clock["current"] = parsed
    return parsed
