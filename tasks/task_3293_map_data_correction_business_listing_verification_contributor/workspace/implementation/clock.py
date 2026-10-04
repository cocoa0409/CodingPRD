"""Logical clock: single source of temporal truth.

Default before any set call: 2026-09-01T00:00:00Z. Never falls back to
wall-clock time.
"""
from datetime import datetime, timezone

_DEFAULT = "2026-09-01T00:00:00Z"
_current = None  # datetime, tz-aware UTC


def _parse(s):
    if isinstance(s, datetime):
        dt = s
    else:
        txt = str(s).strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    if _current is None:
        return _parse(_DEFAULT)
    return _current


def set_now(s):
    global _current
    _current = _parse(s)
    return _current


def parse(s):
    return _parse(s)


def iso(dt):
    """ISO 8601 UTC with three fractional digits, Z suffix."""
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
    s += "%03dZ" % (dt.microsecond // 1000)
    return s
