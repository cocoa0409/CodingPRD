"""The server's logical clock.

PRD.md 2.8: "The server maintains a logical clock which reads
`2026-09-01T00:00:00Z` before any call is made, and which never falls back to
the host's wall clock. Deadlines, expiries and window comparisons all resolve
against that logical clock."

The logical clock is server state that exists before any request; it is reset
on every fresh process, so the store starts empty but the clock starts at its
declared reading.
"""

from datetime import datetime, timezone

CLOCK_START = "2026-09-01T00:00:00Z"

_clock = None


def _parse(value):
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def logical_now():
    """Current logical instant. Never reads wall-clock time."""
    global _clock
    if _clock is None:
        _clock = _parse(CLOCK_START)
    return _clock


def set_logical_now(value):
    global _clock
    _clock = _parse(value)
    return _clock


def reset_clock():
    global _clock
    _clock = _parse(CLOCK_START)
    return _clock