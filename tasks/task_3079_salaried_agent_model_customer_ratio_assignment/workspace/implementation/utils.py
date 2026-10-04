"""Logical clock, identifier minting, timestamp formatting and half-up rounding."""

import math
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# The logical clock reads exactly 2026-09-01T00:00:00Z before it is ever set,
# and never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"clock": DEFAULT_CLOCK, "seq": 0}


def clock_now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(18))


def iso_z(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03d" % (dt.microsecond // 1000) + "Z"


def parse_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half-up to `places` decimal places, returned as Decimal."""
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def cents(value):
    """Integer whole cents, rounded half-up."""
    return int(rhu(value, 0))


def num(value, places=4):
    return float(rhu(value, places))


def floor_ratio(target):
    return int(math.floor(dec(target)))


def ceil_ratio(target):
    return int(math.ceil(dec(target)))


def hours_later(dt, hours):
    return dt + timedelta(hours=hours)


def days_later(dt, days):
    return dt + timedelta(days=days)