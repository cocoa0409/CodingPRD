"""Core primitives: the logical clock, identity minting, instant formatting,
exact-rational rounding and whole-calendar-day arithmetic.

PRD 2.4: nothing in this platform reads wall-clock time. A single server-wide
logical UTC clock supplies every instant. Before the clock has ever been set it
reads exactly 2026-08-01T00:00:00Z.
"""

import datetime as _dt
import itertools
import random
import string
import uuid
from fractions import Fraction

UTC = _dt.timezone.utc

CLOCK_DEFAULT = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class _Clock(object):
    __slots__ = ("current",)

    def __init__(self):
        self.current = CLOCK_DEFAULT


_CLOCK = _Clock()


def now():
    """The logical UTC clock."""
    return _CLOCK.current


def set_clock(value):
    _CLOCK.current = value


def reset_clock():
    _CLOCK.current = CLOCK_DEFAULT


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

_SEQ = itertools.count(1)

_REQ_ALPHABET = string.ascii_uppercase + string.digits


def new_id():
    """Server-minted id: a UUID with no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion counter — the sanctioned tie-break for created_at ASC."""
    return next(_SEQ)


def new_request_id():
    return "req_" + "".join(random.choice(_REQ_ALPHABET) for _ in range(20))


# --------------------------------------------------------------------------
# instants
# --------------------------------------------------------------------------

def iso(value):
    """ISO 8601 UTC instant with exactly three fractional digits (PRD 2.2/2.5)."""
    if value is None:
        return None
    if not isinstance(value, _dt.datetime):
        return value
    v = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond // 1000,
    )


def parse_instant(raw):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if isinstance(raw, _dt.datetime):
        d = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            d = _dt.datetime.fromisoformat(text)
        except Exception:
            return None
    else:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def calendar_days(start, end):
    """Whole calendar days over the half-open interval [start, end) (PRD 2.4)."""
    if start is None or end is None:
        return 0
    return (end.astimezone(UTC).date() - start.astimezone(UTC).date()).days


def add_days(instant, days):
    return instant + _dt.timedelta(days=days)


def add_one_month(instant):
    """Advance an instant by one calendar month, clamping the day of month."""
    year = instant.year
    month = instant.month + 1
    if month > 12:
        month = 1
        year += 1
    day = instant.day
    while day > 1:
        try:
            return instant.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
    return instant.replace(year=year, month=month, day=1)


# --------------------------------------------------------------------------
# exact arithmetic
# --------------------------------------------------------------------------

def frac(*parts):
    """Exact rational product/quotient helper: frac(a, b) == Fraction(a, b)."""
    if len(parts) == 1:
        return Fraction(parts[0])
    return Fraction(parts[0], parts[1])


def round_half_up(value):
    """Round an exact rational half up (away from zero) to a whole integer.

    PRD 2.8: the whole product is evaluated in exact arithmetic and then the
    single resulting quotient is rounded half up to the nearest whole cent.
    """
    if not isinstance(value, Fraction):
        value = Fraction(value)
    if value < 0:
        return -round_half_up(-value)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)
