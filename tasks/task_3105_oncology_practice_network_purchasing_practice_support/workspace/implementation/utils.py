"""Time, identifier and numeric helpers.

The platform reads time from a logical clock (PRD S2.4): it starts at exactly
2026-09-01T00:00:00Z and only moves when a PlatformAdmin calls the clock
endpoint. Nothing here ever consults the host clock.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

STARTUP_CLOCK = "2026-09-01T00:00:00Z"

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|z|[+-]\d{2}:?\d{2})?$"
)


def utc_now_dt():
    return _CLOCK["now"]


_CLOCK = {"now": None}


def set_clock(dt):
    _CLOCK["now"] = dt


def reset_clock():
    _CLOCK["now"] = parse_iso(STARTUP_CLOCK)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6])
    tzpart = m.group(8)
    if tzpart in (None, "Z", "z"):
        tz = timezone.utc
    else:
        tzpart = tzpart.replace(":", "")
        sign = 1 if tzpart[0] == "+" else -1
        tz = timezone(sign * timedelta(hours=int(tzpart[1:3]), minutes=int(tzpart[3:5])))
    try:
        return datetime(y, mo, d, h, mi, s, micro, tzinfo=tz).astimezone(timezone.utc)
    except ValueError:
        return None


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    raw = uuid.uuid4().hex
    return "req_" + raw[:20].upper()


def num(value):
    """Coerce a JSON scalar to a Decimal for exact arithmetic, or None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except Exception:
            return None
    return None


def half_up(value):
    """Round a Decimal half up to an integer number of cents/units."""
    dec = value if isinstance(value, Decimal) else num(value)
    if dec is None:
        return 0
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ratio4(value):
    """Report a stored ratio to four decimal places, rounded half up."""
    dec = value if isinstance(value, Decimal) else num(value)
    if dec is None:
        return 0.0
    q = dec.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def dec_div(numerator, denominator, places=4):
    """Exact rational division reported to `places` decimal places (half up).

    Non-integral results are reported at the pinned precision; the caller keeps
    the exact rational when a boundary comparison depends on it.
    """
    if denominator == 0:
        return Decimal(0)
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
    )


def exact_div(numerator, denominator):
    if denominator == 0:
        return None
    return Decimal(numerator) / Decimal(denominator)


def add_months(dt, months):
    """Advance an instant by whole calendar months, clamping the day."""
    month_index = dt.month - 1 + int(months)
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(
        dt.day,
        [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
         31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1],
    )
    return dt.replace(year=year, month=month, day=day)


def whole_months_between(start, end):
    """Whole calendar months from start to end, inclusive of the start month."""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day >= start.day:
        months += 1
    return max(months, 0)


def month_key(dt):
    return (dt.year, dt.month)