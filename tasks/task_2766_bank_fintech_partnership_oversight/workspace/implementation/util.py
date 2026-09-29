"""Primitives: identity, the server-held logical clock, ISO-8601 handling, rounding."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, getcontext

getcontext().prec = 60

UTC = timezone.utc
# PRD 2.4: the default logical clock value on a fresh boot.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def parse_iso(value):
    """Parse an ISO-8601 instant into an aware UTC datetime; None when unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    # Trim over-long fractional parts that fromisoformat rejects.
    if "." in s:
        head, _, tail = s.partition(".")
        digits = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            else:
                break
        rest = tail[len(digits):]
        if len(digits) > 6:
            digits = digits[:6]
        s = head + "." + digits + rest
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_iso(dt):
    """Serialize with exactly three fractional digits and a trailing Z (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def rhu(value, places):
    """ROUND_HALF_UP to `places` decimal places; returns a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def rhu_float(value, places):
    return float(rhu(value, places))


def rhu_int(value):
    return int(rhu(value, 0))


def floor_bps(amount, bps):
    """floor(amount * bps / 10000) with integer arithmetic (PRD 2.6)."""
    return (int(amount) * int(bps)) // 10000


def floor_mul(amount, multiplier):
    """floor(amount * multiplier) where multiplier is an exact decimal string."""
    return int((Decimal(int(amount)) * Decimal(multiplier)).to_integral_value(
        rounding=ROUND_FLOOR))


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))
