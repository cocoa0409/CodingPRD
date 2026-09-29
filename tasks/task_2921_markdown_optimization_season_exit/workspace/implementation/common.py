"""Shared primitives: identifiers, timestamps, dates and half-up rounding."""

import math
import random
import re
import string
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------
# Identifiers
# --------------------------------------------------------------------------

_REQ_ALPHABET = string.ascii_uppercase + string.digits


def new_uuid():
    """Bare UUID, no prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """`req_` followed by 20 uppercase alphanumeric characters (PRD 2.2)."""
    return "req_" + "".join(random.choice(_REQ_ALPHABET) for _ in range(20))


# --------------------------------------------------------------------------
# Instants: ISO 8601 UTC with exactly three fractional digits (PRD 2.4)
# --------------------------------------------------------------------------

_ts_lock = threading.Lock()
_last_ms = [0]


def _next_ms():
    with _ts_lock:
        ms = int(time.time() * 1000)
        if ms <= _last_ms[0]:
            ms = _last_ms[0] + 1
        _last_ms[0] = ms
        return ms


def iso_from_ms(ms):
    dt = datetime.fromtimestamp(ms // 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (ms % 1000)


def now_instant():
    """A strictly monotonic wall-clock instant, used for created_at/updated_at.

    Monotonicity guarantees that ordering by created_at is insertion ordering,
    which several PRD 2.9 tie-breaks rely on.
    """
    return iso_from_ms(_next_ms())


def instant_from_datetime(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO 8601 instant. Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mi, ss, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            micro = int(round(float(frac) * 1000000))
            if micro >= 1000000:
                micro = 999999
        dt = datetime(int(y), int(mo), int(d), int(hh), int(mi),
                      int(ss or 0), micro)
    except ValueError:
        return None
    if tz in (None, "Z", "z"):
        return dt.replace(tzinfo=timezone.utc)
    sign = 1 if tz[0] == "+" else -1
    body = tz[1:].replace(":", "")
    offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (dt - sign * offset).replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Date-only values (PRD 2.4)
# --------------------------------------------------------------------------

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def days_between(a, b):
    """Whole days from a to b (negative when b precedes a)."""
    return (b - a).days


def whole_weeks(days):
    """Days divided by seven with the remainder discarded (PRD 3.3)."""
    if days >= 0:
        return days // 7
    return -((-days) // 7)


def add_days(d, n):
    return d + timedelta(days=n)


# --------------------------------------------------------------------------
# Rounding: half up, away from zero on ties (PRD 2.8)
# --------------------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return Decimal(0)
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def rc(value):
    """Round to a whole cent (integer)."""
    return int(round_half_up(value, 0))


def r2(value):
    """Round to a two-decimal percentage, returned as a JSON number."""
    return float(round_half_up(value, 2))


def r4(value):
    """Round to four decimals, returned as a JSON number."""
    return float(round_half_up(value, 4))


def clamp(value, low, high):
    v = dec(value)
    lo = dec(low)
    hi = dec(high)
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v
