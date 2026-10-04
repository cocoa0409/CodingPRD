"""Shared helpers: identifiers, ISO-8601 timestamps and decimal rounding."""

import random
import string
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

_ALPHANUM = string.ascii_uppercase + string.digits


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(_ALPHANUM, k=16))


def iso(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 timestamp (or bare date). Returns an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError("empty timestamp")
        if raw.endswith("Z") or raw.endswith("z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(value.strip().rstrip("Zz"), fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("unparseable timestamp: %s" % value)
    else:
        raise ValueError("unparseable timestamp: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dt_date(dt):
    """UTC date component, used wherever the spec truncates to whole days."""
    if isinstance(dt, str):
        dt = parse_dt(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def days_between(later, earlier):
    return (dt_date(later) - dt_date(earlier)).days


def dec(value):
    return Decimal(str(value))


def round_half_up(value, places):
    """Round half up to `places` decimal places, returning a Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_half_up_float(value, places):
    return float(round_half_up(value, places))


def as_int(value, field):
    """Strict integer coercion for request bodies."""
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise ValueError("%s must be an integer" % field)
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be a number" % field)
    return value


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)
