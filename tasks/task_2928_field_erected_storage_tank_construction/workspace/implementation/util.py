"""Timestamps, the server-side logical clock, rounding and id minting."""

import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# PRD 2.4: "Before any request sets it, the clock reads exactly
# 2026-08-01T00:00:00Z; that startup default is mandatory and the server never
# falls back to real time."
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"clock": CLOCK_DEFAULT}
LOCK = threading.RLock()


def now_logical():
    return _state["clock"]


def set_logical(dt):
    _state["clock"] = dt
    return _state["clock"]


def now_real():
    """Wall clock instant used for created_at / updated_at / envelope meta."""
    return datetime.now(timezone.utc)


def new_id():
    """PRD 2.4: a server-minted UUID with no type prefix of any kind."""
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ---------------------------------------------------------------- timestamps
def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO-8601 UTC instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def add_hours(dt, hours):
    return dt + timedelta(hours=float(hours))


def add_years(dt, years):
    """Calendar arithmetic: same month and day-of-month, whole years later."""
    years = int(years)
    year = dt.year + years
    month = dt.month
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


# ------------------------------------------------------------------ rounding
def D(value):
    """Decimal from anything numeric, via its shortest decimal representation."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q(value, places):
    """Round half up to `places` decimals; returns a float."""
    exp = Decimal(1).scaleb(-places)
    return float(D(value).quantize(exp, rounding=ROUND_HALF_UP))


def qd(value, places):
    """Round half up to `places` decimals; returns a Decimal."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)
