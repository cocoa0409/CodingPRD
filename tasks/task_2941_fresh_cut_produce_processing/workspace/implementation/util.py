"""Logical clock, ISO-8601 instant handling and decimal rounding helpers.

Nothing in this system reads the host machine's wall clock (PRD 2.4): every
server-stamped instant and every time-window rule reads the logical clock which
starts at exactly 2026-08-01T00:00:00Z on every boot.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"T(\d{2}):(\d{2}):(\d{2})"
    r"(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


class Instant(object):
    """A client-supplied instant: the verbatim text plus the parsed datetime."""

    __slots__ = ("raw", "dt")

    def __init__(self, raw, dt):
        self.raw = raw
        self.dt = dt


def parse_instant(text):
    """Parse an ISO 8601 UTC instant. Raises ValueError when not acceptable."""
    if not isinstance(text, str):
        raise ValueError("not a string")
    m = _ISO_RE.match(text.strip())
    if not m:
        raise ValueError("not an ISO 8601 instant")
    year, month, day, hour, minute, second, frac, tz = m.groups()
    if tz not in (None, "Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        off = int(body[:2]) * 60 + int(body[2:])
        if sign * off != 0:
            raise ValueError("instant must be UTC")
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        raise ValueError("instant out of range")
    return Instant(text, dt)


def fmt_instant(dt):
    """Canonical server rendering: ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


class _Clock(object):
    def __init__(self):
        self.current = parse_instant(DEFAULT_CLOCK_ISO).dt

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt


CLOCK = _Clock()


def now_dt():
    return CLOCK.now()


def now_iso():
    return fmt_instant(CLOCK.now())


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Decimal helpers. Rounding is half-up everywhere in this specification.
# ---------------------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def _q(value, places):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def q0(value):
    return _q(value, 0)


def q1(value):
    return _q(value, 1)


def q2(value):
    return _q(value, 2)


def q3(value):
    return _q(value, 3)


def round_cents(value):
    """Round half-up to a whole number of cents and return an int."""
    return int(_q(value, 0))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def clamp_int(value, low, high):
    return max(low, min(high, int(value)))


def date_of(dt):
    return dt.astimezone(timezone.utc).date()


def iso_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def julian_label(d):
    return "%04d%03d" % (d.year, d.timetuple().tm_yday)


def minutes(n):
    return timedelta(minutes=n)


def hours(n):
    return timedelta(hours=n)
