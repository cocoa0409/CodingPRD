"""Logical clock: default 2026-09-01T00:00:00Z; settable by PlatformAdmin."""
from datetime import datetime, timezone

from constants import CLOCK_DEFAULT_ISO

_state = {"current": None}


def _parse(iso):
    if isinstance(iso, datetime):
        return iso
    s = str(iso)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def now():
    if _state["current"] is None:
        return _parse(CLOCK_DEFAULT_ISO)
    return _state["current"]


def now_iso():
    return to_iso(now())


def set_current(iso):
    _state["current"] = _parse(iso)
    return now_iso()


def to_iso(dt):
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms
