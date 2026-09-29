"""Server-side logical clock. Nothing in this system reads wall-clock time."""
import re
from datetime import datetime, timedelta

DEFAULT_NOW = "2026-08-01T00:00:00.000Z"
SECONDS_PER_DAY = 86400

_state = {"now": DEFAULT_NOW}

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def fmt(dt):
    """Format a naive UTC datetime as ISO 8601 with exactly three fractional digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse(value):
    """Parse an ISO 8601 instant into a naive UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _ISO_RE.match(value.strip())
    if not m:
        raise ValueError("not an ISO 8601 instant")
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    dt = datetime(year, month, day, hour, minute, second, micro)
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        oh, om = int(body[:2]), int(body[2:4])
        dt = dt - sign * timedelta(hours=oh, minutes=om)
    return dt


def canonical(value):
    """Normalise a client-supplied instant to the canonical three-digit form."""
    return fmt(parse(value))


def now():
    return _state["now"]


def now_dt():
    return parse(_state["now"])


def set_now(iso_value):
    _state["now"] = canonical(iso_value)
    return _state["now"]


def reset():
    _state["now"] = DEFAULT_NOW


def plus_days(iso_value, days):
    return fmt(parse(iso_value) + timedelta(days=days))


def plus_seconds(iso_value, seconds):
    return fmt(parse(iso_value) + timedelta(seconds=seconds))


def whole_days_between(start_iso, end_iso):
    """Whole days from start to end, never negative."""
    delta = (parse(end_iso) - parse(start_iso)).total_seconds()
    if delta <= 0:
        return 0
    return int(delta // SECONDS_PER_DAY)
