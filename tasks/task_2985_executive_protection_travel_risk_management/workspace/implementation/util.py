"""Instant parsing/rendering, numeric discipline and JSON encoding helpers.

PRD 2.4  -- ISO 8601 UTC with exactly three fractional-second digits and a
            trailing Z.
PRD 2.7  -- scores are 0.00..100.00 with exactly two decimals, round-half-up;
            money is an integer count of cents; hour counts are whole integers
            obtained from whole elapsed minutes divided by 60 and rounded UP.
"""

import json
import math
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# PRD 2.5: before the clock has ever been set the logical clock reads exactly
# this instant, and that fixed startup default must never fall back to real
# system time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

TWO_PLACES = Decimal("0.01")
ZERO_SCORE = Decimal("0.00")
SCORE_CAP = Decimal("100.00")

_ISO_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"(?:[Tt ](?P<h>\d{2}):(?P<mi>\d{2})"
    r"(?::(?P<s>\d{2})(?:\.(?P<f>\d{1,9}))?)?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})?)?$"
)

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")

_REQ_ID_ALPHABET = string.ascii_uppercase + string.digits


def new_id():
    """PRD 2.4: a UUID string with no type prefix of any kind."""
    return str(uuid.uuid4())


def new_request_id():
    """PRD 2.2: a server-generated unique identifier starting with req_."""
    return "req_" + "".join(random.choice(_REQ_ID_ALPHABET) for _ in range(20))


def parse_instant(value):
    """Parse an ISO-8601 UTC instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = _ISO_RE.match(text)
    if not m:
        return None
    frac = m.group("f") or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        base = datetime(
            int(m.group("y")),
            int(m.group("mo")),
            int(m.group("d")),
            int(m.group("h") or 0),
            int(m.group("mi") or 0),
            int(m.group("s") or 0),
            micro,
            tzinfo=UTC,
        )
    except ValueError:
        return None
    tz = m.group("tz")
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offset
    return base


def fmt_instant(value):
    """Render an instant with exactly three fractional digits and trailing Z."""
    if value is None:
        return None
    dt = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def is_country_code(value):
    """PRD 2.11 item 3: exactly two uppercase letters A-Z."""
    return isinstance(value, str) and bool(_COUNTRY_RE.match(value))


def to_decimal(value):
    """Coerce an int/float/Decimal/numeric string into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("not a number")


def round2(value):
    """Round half-up to two decimal places (PRD 2.7)."""
    return to_decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def score(value):
    """Normalise a stored score to its two-decimal representation."""
    return round2(value)


def round_cents(value):
    """Round half-up to a whole cent and return a Python int (PRD 2.7)."""
    return int(to_decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def hours_between(start, end):
    """PRD 2.7: whole elapsed minutes / 60, rounded UP to the next whole hour."""
    total_seconds = (end - start).total_seconds()
    minutes = int(math.floor(total_seconds / 60.0))
    if minutes <= 0:
        return 0
    return -(-minutes // 60)


def age_in_days(observed_at, now):
    """PRD 3.2: seconds between the two instants / 86400, rounded down."""
    seconds = (now - observed_at).total_seconds()
    return int(math.floor(seconds / 86400.0))


# --------------------------------------------------------------------------
# JSON encoding
#
# Scores must appear on the wire with exactly two decimal places (PRD 2.7),
# which json.dumps cannot do for floats.  Decimal values are therefore staged
# as sentinel strings and unquoted after serialisation.
# --------------------------------------------------------------------------

_NUM_SENTINEL = "\u0000N:"
_NUM_RE = re.compile(r'"\\u0000N:(-?\d+(?:\.\d+)?)"')


def _stage(obj):
    if isinstance(obj, Decimal):
        return _NUM_SENTINEL + str(obj)
    if isinstance(obj, dict):
        return {k: _stage(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_stage(v) for v in obj]
    if isinstance(obj, datetime):
        return fmt_instant(obj)
    return obj


def dumps(obj):
    """Serialise, emitting Decimal values as bare fixed-precision numbers."""
    text = json.dumps(_stage(obj), ensure_ascii=False)
    return _NUM_RE.sub(lambda m: m.group(1), text)
