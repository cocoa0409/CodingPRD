"""Instant parsing/rendering, decimal helpers and calendar arithmetic."""

import calendar
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# PRD 2.5 - fixed startup default for the logical clock; never wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

PERIOD_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime truncated to ms.

    Raises ValueError when the value is not a parseable instant.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    m = _ISO_RE.match(text)
    if not m:
        raise ValueError("not an ISO-8601 instant")
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    offset = timedelta(0)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        raise ValueError("not a valid calendar instant")
    dt = naive.replace(tzinfo=UTC) - offset
    # Render precision is three fractional digits; canonicalise on the way in
    # so that a stored instant round-trips exactly.
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def fmt_instant(dt):
    """Render an aware UTC datetime as an ISO-8601 instant with 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_wall():
    return datetime.now(UTC)


def month_key(dt):
    """The YYYY-MM period of an instant."""
    return "%04d-%02d" % (dt.year, dt.month)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def add_months(dt, months):
    """Add whole months, clamping the day-of-month to the target month's length."""
    total = (dt.year * 12 + (dt.month - 1)) + int(months)
    year, month = divmod(total, 12)
    month += 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def whole_days_between(start, end):
    """floor((end - start) / 1 day) - negative when end precedes start."""
    delta = end - start
    seconds = delta.days * 86400 + delta.seconds + delta.microseconds / 1000000.0
    return int(seconds // 86400)


def full_months_between(start, as_of):
    """Count of integers k >= 1 such that add_months(start, k) <= as_of."""
    if as_of < start:
        return 0
    k = 0
    while True:
        if add_months(start, k + 1) <= as_of:
            k += 1
        else:
            return k


def D(value):
    """Coerce a JSON number / string / Decimal into a Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def q2(value):
    return D(value).quantize(TWO, rounding=ROUND_HALF_UP)


def q4(value):
    return D(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal as a JSON number."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return float(value)


def decimal_places(value):
    """Number of decimal places a JSON number carries."""
    dec = D(value).normalize()
    exponent = dec.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("not a finite number")
    return max(0, -exponent)
