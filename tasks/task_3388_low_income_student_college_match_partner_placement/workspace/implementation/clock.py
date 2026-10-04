"""Logical clock (PRD section 2.4).

Every window check, deadline comparison, and system-assigned timestamp reads
this single server-side logical clock -- never the wall clock. Before the
clock is explicitly set it reads exactly 2026-09-01T00:00:00Z.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _DEFAULT


def now():
    return _current


def set_current(dt):
    global _current
    _current = dt.astimezone(timezone.utc)
    return _current


def fmt(dt):
    """Serialize as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ValueError on malformed input; the caller maps that to
    ERR_INVALID_REQUEST. Naive inputs are treated as UTC.
    """
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
