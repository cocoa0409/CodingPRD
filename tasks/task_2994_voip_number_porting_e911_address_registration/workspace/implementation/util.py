"""Time, id and arithmetic helpers.

Every temporal reading in this domain comes from the logical clock held in
store.py -- nothing here reads the host wall clock.
"""
import calendar
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ISO 8601 UTC instant.  Emitted with exactly three fractional digits and a
# trailing Z; accepted with an optional fractional part and a UTC designator.
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|z|\+00:00|-00:00)$"
)

_ALNUM_UPPER = string.ascii_uppercase + string.digits


def new_id():
    """Server generated UUID, no type prefix."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM_UPPER) for _ in range(20))


def parse_instant(value):
    """Parse an ISO 8601 UTC instant.  Returns a tz-aware datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, _tz = m.groups()
    try:
        micro = 0
        if frac:
            digits = (frac[1:] + "000000")[:6]
            micro = int(digits)
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def to_iso(dt):
    """Format a datetime as an ISO 8601 UTC instant with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


PERIOD_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def parse_period(value):
    """Parse a YYYY-MM month string, returning (year, month) or None."""
    if not isinstance(value, str) or not PERIOD_RE.match(value):
        return None
    return int(value[0:4]), int(value[5:7])


def period_bounds(year, month):
    """(period_start, period_end, days_in_month) for a calendar month."""
    days = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(year, month, days, 23, 59, 59, 999000, tzinfo=timezone.utc)
    return start, end, days


def month_key(dt):
    return "%04d-%02d" % (dt.year, dt.month)


def round_half_up(numerator, denominator):
    """Integer half-up division: a fractional half rounds away from zero."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_decimal(value):
    """Half-up rounding of a Decimal/int/float-free value to a whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


def hours(n):
    return timedelta(hours=n)


def minutes(n):
    return timedelta(minutes=n)


def normalize_alnum(value):
    """Uppercase and strip every character outside [A-Z0-9]."""
    if value is None:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def day_start(dt):
    return datetime(dt.year, dt.month, dt.day, 0, 0, 0, 0, tzinfo=timezone.utc)


def jsonable(value):
    """Recursively convert datetimes to ISO strings for the response body."""
    if isinstance(value, datetime):
        return to_iso(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value
