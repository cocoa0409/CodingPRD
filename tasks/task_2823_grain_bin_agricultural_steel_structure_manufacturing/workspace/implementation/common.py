"""Shared primitives: decimal helpers, timestamp formatting, id generation."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

ZERO = Decimal("0")


def D(value):
    """Coerce to Decimal without ever routing through binary float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a numeric value")
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to a fixed number of decimal places."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    """Round half up to whole cents, returned as a Python int."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dceil(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def dfloor(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def new_id():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def utc_now():
    return datetime.now(timezone.utc)


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def parse_dt(raw):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_days(instant, days):
    return instant + timedelta(days=int(days))


def num(value):
    """Serialize a stored numeric field to JSON."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
