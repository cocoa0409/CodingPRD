"""Shared primitives: ids, canonical timestamps, decimal helpers, parsing."""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_ID_ALPHABET = string.ascii_uppercase + string.digits


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def iso(dt):
    """Canonical ISO-8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?"
    r"(([Zz])|([+-]\d{2}:?\d{2}))?$"
)


def parse_instant(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or not _INSTANT_RE.match(raw):
        return None
    txt = raw.replace(" ", "T").replace("t", "T")
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def day_bounds(day):
    """[start, end) instants of a UTC calendar day."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def half_up_int(value):
    return int(round_half_up(value, 0))


def floor_int(value):
    d = dec(value)
    as_int = int(d)
    if d < 0 and dec(as_int) != d:
        as_int -= 1
    return as_int


def ceil_int(value):
    d = dec(value)
    as_int = int(d)
    if d > 0 and dec(as_int) != d:
        as_int += 1
    return as_int


def fixed(value, places):
    """Fixed-precision decimal string (round half up)."""
    if value is None:
        return None
    return str(round_half_up(value, places))


def whole_minutes(start, end):
    """Elapsed whole minutes, truncated toward zero."""
    if start is None or end is None:
        return 0
    return int((end - start).total_seconds() / 60)


def overlap_minutes(a0, a1, b0, b1):
    """Whole minutes of overlap between two half-open instant intervals."""
    lo = a0 if a0 > b0 else b0
    hi = a1 if a1 < b1 else b1
    if hi <= lo:
        return 0
    return int((hi - lo).total_seconds() // 60)


def jnum(value):
    """Render a stored decimal as a JSON number."""
    if value is None:
        return None
    d = dec(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)
