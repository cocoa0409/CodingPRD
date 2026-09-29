"""Shared primitives: logical clock, ids, ISO parsing, round-half-up arithmetic."""
import re
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# The logical clock's startup value, per PRD 2.5.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_instant(value):
    """Parse an ISO-8601 UTC instant. A bare YYYY-MM-DD is read as midnight UTC."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    d = parse_date(text)
    if d is not None:
        return datetime(d.year, d.month, d.day, tzinfo=UTC)
    m = _INSTANT_RE.match(text)
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzs = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if tzs and tzs not in ("Z", "z"):
        sign = 1 if tzs[0] == "+" else -1
        body = tzs[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def iso(dt):
    """Canonical ISO-8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def D(value):
    """Decimal from any JSON number without binary-float contamination."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up (away from zero at the midpoint) to `places` decimals."""
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def num1(value):
    """Round half up to one decimal place, returned as a JSON number."""
    if value is None:
        return None
    return float(rhu(value, 1))


def num2(value):
    """Round half up to two decimal places, returned as a JSON number."""
    if value is None:
        return None
    return float(rhu(value, 2))


def whole(value):
    """Round half up to a whole number, returned as an int."""
    if value is None:
        return None
    return int(rhu(value, 0))
