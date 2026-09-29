"""The server-owned logical clock (PRD 2.4).

"Now" in this system never means the host wall clock. At server startup the
logical clock is 2026-08-01T00:00:00Z.
"""
import re
from datetime import datetime, timezone

_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _START}

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)
    return _state["now"]


def reset():
    _state["now"] = _START


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _ISO_RE.match(text):
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    candidate = candidate.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_seconds(later, earlier):
    """Whole seconds of difference between two instants."""
    return int((later - earlier).total_seconds())


def elapsed_minutes_floor(later, earlier):
    """Whole seconds of difference, divided by 60 and truncated downward."""
    secs = whole_seconds(later, earlier)
    if secs < 0:
        # Truncation toward the whole minute already elapsed.
        return -((-secs) // 60)
    return secs // 60
