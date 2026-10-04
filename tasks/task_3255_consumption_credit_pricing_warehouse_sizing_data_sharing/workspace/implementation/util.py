"""Decimals, logical clock and response envelope helpers."""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- clock ----

CLOCK_START = "2026-09-01T00:00:00Z"
_clock = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def parse_iso(value, field="timestamp"):
    if value is None:
        raise ValueError(field)
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        try:
            if s.endswith("Z") or s.endswith("z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise ValueError(field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.microsecond // 1000)


def iso_now():
    return fmt_dt(now())


def num(value, field="value"):
    """Coerce JSON input to Decimal; rejects anything non-numeric."""
    if isinstance(value, bool) or value is None:
        raise ValueError(field)
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value.strip())
    raise ValueError(field)


def as_int(value, field="value"):
    if isinstance(value, bool) or value is None:
        raise ValueError(field)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            raise ValueError(field)
        return int(value)
    if isinstance(value, str):
        return int(value.strip())
    raise ValueError(field)


# ------------------------------------------------------------ rounding ----

SIX = Decimal("0.000001")
TWO = Decimal("0.01")


def r6(value):
    """Round half up to six decimals; returns a Decimal."""
    return Decimal(value).quantize(SIX, rounding=ROUND_HALF_UP)


def r2(value):
    """Round half up to two decimals; returns a Decimal."""
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def out_num(value):
    """Serialize a rounded Decimal to a JSON number."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value)


def req_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(24))


def new_id():
    return str(uuid.uuid4())


def days_between(start, end):
    return (end - start).total_seconds() / 86400.0


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test."""
    return a_start < b_end and b_start < a_end


def add_days(dt, days):
    return dt + timedelta(days=days)
