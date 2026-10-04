"""Server-side logical clock (PRD §2.5) and ISO-8601 helpers.

All server-recorded time reads from this clock — never from wall-clock time.
Before it has ever been set, the clock reads exactly 2026-09-01T00:00:00Z.
"""

from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

_state = {"now": None}


def parse_iso(value):
    """Parse an ISO-8601 string (with Z or numeric offset) to an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format an aware datetime as ISO-8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now():
    if _state["now"] is None:
        _state["now"] = parse_iso(DEFAULT_CLOCK_ISO)
    return _state["now"]


def now_iso():
    return format_iso(now())


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)
