"""Rounding discipline (PRD 2.5), ISO-8601 rendering and parsing helpers."""
import re
import uuid
import random
import string
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, InvalidOperation

UTC = timezone.utc

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def D(value):
    """Coerce anything numeric-ish into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places):
    """Round half up to `places` decimal places (PRD 2.5)."""
    q = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def round_int(value):
    """Round half up to a whole number, returned as an int."""
    return int(round_half_up(value, 0))


def truncate(value):
    """Truncate toward zero to a whole number (the waterfall never rounds up)."""
    return int(D(value).to_integral_value(rounding=ROUND_DOWN))


def q3(value):
    return round_half_up(value, 3)


def q2(value):
    return round_half_up(value, 2)


def q4(value):
    return round_half_up(value, 4)


def q6(value):
    return round_half_up(value, 6)


def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def iso(dt):
    """Render an aware datetime as ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_instant(text):
    """Parse an ISO-8601 instant into an aware UTC datetime; ValueError when malformed."""
    if not isinstance(text, str):
        raise ValueError("instant must be a string")
    m = _INSTANT_RE.match(text.strip())
    if not m:
        raise ValueError("unparseable ISO-8601 instant: %r" % text)
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(str(exc))
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        digits = offset[1:].replace(":", "")
        delta = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]))
        base = base - sign * delta
    return base


def parse_date_string(text):
    """Validate a YYYY-MM-DD calendar date and return a date object."""
    if not isinstance(text, str) or not _DATE_RE.match(text):
        raise ValueError("date must be YYYY-MM-DD")
    return datetime.strptime(text, "%Y-%m-%d").date()


def date_str(value):
    if isinstance(value, date):
        return value.isoformat()
    return value


def add_days(dt, days):
    return dt + timedelta(days=days)


def hours_between(start, end):
    """Exact hour count between two instants as a Decimal."""
    seconds = D((end - start).total_seconds())
    return seconds / D(3600)


def to_number(value):
    """Render a Decimal/int for JSON as a plain number."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value() and value.as_tuple().exponent >= 0:
            return int(value)
        return float(value)
    return value
