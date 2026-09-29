"""Shared primitives: logical clock, id generation, rounding, temporal helpers.

PRD 2.4: every deadline, expiry, window and eligibility rule is evaluated
against a logical program clock, never the host wall clock.  The clock starts
at exactly 2026-08-01T00:00:00Z on every boot and only POST
/_clock/set_current_utc moves it.
"""

import random
import re
import string
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self._now = CLOCK_DEFAULT

    def now(self):
        return self._now

    def set(self, value):
        self._now = value

    def today(self):
        return self._now.astimezone(timezone.utc).date()


clock = LogicalClock()


def new_id():
    """PRD 2.6: id is a server-generated UUID string with no prefix."""
    return str(uuid.uuid4())


_REQ_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    """PRD 2.2: api_request_id is an opaque req_-prefixed identifier."""
    return "req_" + "".join(random.choice(_REQ_ALPHABET) for _ in range(20))


def fmt_instant(value):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2/2.6)."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(raw):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime truncated to
    milliseconds, or None when the value is not a well formed instant."""
    if not isinstance(raw, str):
        return None
    m = _INSTANT_RE.match(raw.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tz = m.group(8)
    if tz in (None, "Z", "z"):
        offset = timedelta(0)
    else:
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    value = (naive - offset).replace(tzinfo=timezone.utc)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(raw):
    """Parse a YYYY-MM-DD calendar date.  Returns a datetime.date or None."""
    if not isinstance(raw, str):
        return None
    m = _DATE_RE.match(raw.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    """PRD 2.9: every rounding step in this specification is half up."""
    quant = Decimal(1).scaleb(-places)
    return to_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Money is integer cents throughout (PRD 2.8)."""
    return int(round_half_up(value, 0))


def ceil_to_multiple(value, multiple):
    """Round a Decimal UP to the next multiple (PRD 3.5 five-minute grid)."""
    m = to_decimal(multiple)
    steps = (to_decimal(value) / m).to_integral_value(rounding=ROUND_CEILING)
    return int(steps) * int(m)


def dec_or_none(value, places):
    if value is None:
        return None
    return round_half_up(value, places)


def whole_days_between(start, end):
    """Number of whole days between two instants (PRD 3.7 days_since_visit)."""
    delta = end - start
    return int(delta.total_seconds() // 86400)
