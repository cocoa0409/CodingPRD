"""Numeric, temporal and identifier helpers.

Money is carried in whole integer cents.  Ratios are carried to four decimal
places and labor minutes to two, both as Decimal internally (PRD 2.6) and as
plain JSON numbers on the wire.  Rounding is always round-half-up.
"""

import datetime
import random
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, InvalidOperation

UTC = datetime.timezone.utc

ZERO = Decimal("0")
Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")


def dec(value):
    """Coerce an int/float/str/Decimal into Decimal without float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise InvalidOperation("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    """Round half up to `places` decimal places, returning a Decimal."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to whole cents and return a Python int."""
    return int(round_half_up(value, 0))


def q2(value):
    return dec(value).quantize(Q2, rounding=ROUND_HALF_UP)


def q4(value):
    return dec(value).quantize(Q4, rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def num(value):
    """Render a stored Decimal as a JSON number (never a string)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            # keep integral labor/ratio values as floats for stable JSON typing
            return float(value)
        return float(value)
    return value


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------

def now_wall():
    return datetime.datetime.now(tz=UTC)


def fmt_dt(value):
    """ISO-8601 UTC with exactly three fractional digits, Z suffix."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


def parse_dt(raw):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(raw):
    """Parse a YYYY-MM-DD calendar date.  Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


DOW_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def day_of_week(date_obj):
    """Weekday under the proleptic Gregorian calendar."""
    return DOW_NAMES[date_obj.weekday()]


def add_minutes(instant, minutes):
    return instant + datetime.timedelta(minutes=float(minutes))


def add_hours(instant, hours):
    return instant + datetime.timedelta(hours=float(hours))


# ---------------------------------------------------------------------------
# identifiers
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
