"""The logical UTC clock (PRD 2.5) and ISO-8601 timestamp discipline (PRD 2.4)."""

import re
from datetime import datetime, timedelta, timezone

from errors import ApiError

# PRD 2.5: at startup the clock reads exactly this instant and must never fall
# back on real wall-clock time.
STARTUP_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"current_utc": STARTUP_UTC}

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def now():
    return _state["current_utc"]


def set_now(dt):
    previous = _state["current_utc"]
    _state["current_utc"] = dt
    return previous


def reset():
    _state["current_utc"] = STARTUP_UTC


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_ts(value, field="timestamp"):
    """Parse an ISO 8601 UTC instant. Anything else is ERR_INVALID_REQUEST."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC timestamp string." % field)
    m = _ISO_RE.match(value.strip())
    if not m:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 UTC timestamp." % field)
    year, month, day, hour, minute, second, frac, offset = m.groups()
    try:
        micro = 0
        if frac:
            digits = (frac[1:] + "000000")[:6]
            micro = int(digits)
        dt = datetime(int(year), int(month), int(day), int(hour), int(minute),
                      int(second or 0), micro, tzinfo=timezone.utc)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 UTC timestamp." % field)
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        if delta != timedelta(0):
            # The specification is UTC-only; a non-zero offset is normalised.
            dt = dt - sign * delta
    return dt


def tax_year(dt=None):
    """PRD 2.5: the four-digit UTC calendar year of the instant given."""
    if dt is None:
        dt = now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).year


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)
