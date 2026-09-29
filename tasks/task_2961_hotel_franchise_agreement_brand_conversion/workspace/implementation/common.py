"""Shared primitives: decimal discipline, the logical clock, calendar arithmetic, ids."""

import random
import string
import uuid
from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_HALF_UP, getcontext, InvalidOperation

getcontext().prec = 40

CENT = Decimal("0.01")
TEN_K = Decimal("0.0001")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100.00")

# ---------------------------------------------------------------------------
# Decimal helpers.  Every money / rate / score value in this system is a
# Decimal; ROUND_HALF_UP everywhere (PRD 2.6).
# ---------------------------------------------------------------------------


def D(value):
    """Coerce an incoming JSON number (int / Decimal / float / str) to Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise InvalidOperation("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q2(value):
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(value):
    return D(value).quantize(TEN_K, rounding=ROUND_HALF_UP)


def dmin(a, b):
    return a if a <= b else b


def dmax(a, b):
    return a if a >= b else b


def decimals_within(value, places):
    """True when the supplied number carries no more than `places` decimals."""
    try:
        dec = D(value)
    except (InvalidOperation, ValueError, TypeError):
        return False
    quant = Decimal(1).scaleb(-places)
    return dec == dec.quantize(quant, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# The logical clock (PRD 2.4).  Nothing in this system reads the host wall
# clock.  Before the first POST /_clock/set_current_utc the clock reads
# exactly 2026-08-01T00:00:00Z.
# ---------------------------------------------------------------------------

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0)

_clock = {"now": CLOCK_EPOCH}


def clock_now():
    return _clock["now"]


def clock_set(instant):
    _clock["now"] = trunc_ms(instant)
    return _clock["now"]


def clock_reset():
    _clock["now"] = CLOCK_EPOCH


def trunc_ms(dt):
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt_instant(clock_now())


def parse_instant(text):
    """Parse an ISO-8601 instant.  Returns a naive UTC datetime or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    offset = parsed.utcoffset()
    if offset is not None:
        parsed = parsed.replace(tzinfo=None) - offset
    return parsed


def parse_date(text):
    """Strict YYYY-MM-DD calendar date.  Returns a date or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
        return None
    try:
        return date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        return None


def fmt_date(value):
    if value is None:
        return None
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def add_days(instant, days):
    """Whole days added to an instant, time of day preserved exactly."""
    if instant is None:
        return None
    return instant + timedelta(days=int(days))


def _days_in_month(year, month):
    if month == 12:
        return 31
    return (date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)).day


def add_years_date(value, years):
    """Advance the year component, keeping month and day unchanged."""
    year = value.year + int(years)
    day = min(value.day, _days_in_month(year, value.month))
    return date(year, value.month, day)


def month_span(later, earlier):
    """Whole calendar months by month index, floored at zero (PRD 2.4)."""
    span = (later.year * 12 + later.month) - (earlier.year * 12 + earlier.month)
    return span if span > 0 else 0


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
