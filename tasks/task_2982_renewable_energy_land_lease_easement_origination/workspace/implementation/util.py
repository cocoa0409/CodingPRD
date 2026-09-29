"""Primitive helpers: identifiers, ISO-8601 instants, decimal arithmetic.

PRD section 2.5 fixes the presentation of every quantity family:
  * money    -> whole integer cents, ROUND_HALF_UP
  * acreage  -> two decimal places, ROUND_HALF_UP
  * scores   -> two decimal places, ROUND_HALF_UP
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

TWO = Decimal("0.01")
ONE = Decimal("1")
ZERO2 = Decimal("0.00")


def new_id():
    """A UUID string with no type prefix (PRD section 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def utcnow():
    return datetime.now(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, millis,
    )


_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse a client-supplied instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or not _DT_RE.match(text):
        return None
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def D(value):
    """Coerce to Decimal without ever routing through binary float repr."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def r2(value):
    """Round half up to two decimal places (acreage and scores)."""
    return D(value).quantize(TWO, rounding=ROUND_HALF_UP)


def rcents(value):
    """Round half up to a whole number of cents."""
    return int(D(value).quantize(ONE, rounding=ROUND_HALF_UP))


def num(value):
    """JSON rendering for a Decimal-backed numeric field."""
    if value is None:
        return None
    return float(D(value))


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)) or \
        isinstance(value, Decimal)


def is_str(value):
    return isinstance(value, str)


def is_bool(value):
    return isinstance(value, bool)


def blank(value):
    return not isinstance(value, str) or value.strip() == ""
