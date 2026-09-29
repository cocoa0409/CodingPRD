"""The server-wide logical clock (PRD §2.4).

"A single server-wide logical clock supplies the value of 'now' ... Nothing in
this service reads the host machine's wall clock."  The clock starts at
2026-08-01T00:00:00Z on every boot and only POST /_clock/set_current_utc moves it.
"""

from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(value):
    _state["now"] = value


def reset():
    _state["now"] = DEFAULT_NOW


def fmt(dt):
    """Domain instants: ISO-8601 UTC, whole-second precision, trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_millis(dt):
    """api_request_timestamp only: exactly three fractional digits (PRD §2.2)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
