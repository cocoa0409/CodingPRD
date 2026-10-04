"""Logical clock. Default startup value is 2026-09-01T00:00:00Z; never wall-clock."""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = _DEFAULT


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def iso(dt):
    """Format a datetime as ISO8601 UTC with three fractional digits."""
    if dt is None:
        return None
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
    ms = dt.microsecond // 1000
    return f"{s}{ms:03d}Z"


def iso_echo(dt):
    """Format a client-supplied datetime as ISO8601 UTC at whole-second
    precision (echo of the client's own input)."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso():
    return iso(_now)
