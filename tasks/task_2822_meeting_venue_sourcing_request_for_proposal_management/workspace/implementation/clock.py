"""Logical clock (PRD section 2.6) plus ISO-8601 helpers.

Nothing in this system reads wall-clock time for business decisions.  The
process boots with the logical clock pinned to exactly 2026-08-01T00:00:00Z and
it only ever moves when POST /_clock/set_current_utc says so.
"""
import re
from datetime import datetime, date, timedelta, timezone

UTC = timezone.utc
DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_state = {"now": DEFAULT_NOW}

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(?:([Zz])|([+-])(\d{2}):(\d{2}))?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def now():
    return _state["now"]


def set_now(value):
    _state["now"] = value


def reset():
    _state["now"] = DEFAULT_NOW


def fmt_instant(value):
    """ISO 8601 UTC with exactly three fractional-second digits and a Z."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    value = value.astimezone(UTC)
    millis = value.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second, millis,
    )


def fmt_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def parse_instant(raw):
    """Parse an ISO-8601 instant.  Raises ValueError when unusable."""
    if not isinstance(raw, str):
        raise ValueError("not a string")
    m = _INSTANT_RE.match(raw.strip())
    if not m:
        raise ValueError("bad instant")
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    value = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    if m.group(9):
        offset = timedelta(hours=int(m.group(10)), minutes=int(m.group(11)))
        value = value - offset if m.group(9) == "+" else value + offset
    return value


def parse_date(raw):
    if not isinstance(raw, str):
        raise ValueError("not a string")
    m = _DATE_RE.match(raw.strip())
    if not m:
        raise ValueError("bad date")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def day_start(day):
    """The instant 00:00:00.000Z on the given calendar date."""
    return datetime(day.year, day.month, day.day, 0, 0, 0, 0, tzinfo=UTC)


def day_end(day):
    """The instant 23:59:59.999Z on the given calendar date."""
    return datetime(day.year, day.month, day.day, 23, 59, 59, 999000, tzinfo=UTC)
