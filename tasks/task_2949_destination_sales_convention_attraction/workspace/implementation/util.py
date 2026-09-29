"""Time, date and money helpers.

PRD 2.4: instants are ISO 8601 UTC with a trailing Z, rendered with exactly
three fractional digits.  Dates are plain YYYY-MM-DD calendar dates and, where
compared against the clock, are interpreted at 00:00:00Z on that day.
PRD 2.5: every monetary value carries at most two fraction digits and every
monetary computation rounds to two decimals using round-half-up.
"""

import datetime
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

UTC = datetime.timezone.utc

INSTANT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?Z$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

TWO_PLACES = Decimal("0.01")


# --------------------------------------------------------------------------
# instants
# --------------------------------------------------------------------------
def parse_instant(value):
    """Parse an ISO-8601 UTC instant with a trailing Z.  None when malformed."""
    if not isinstance(value, str):
        return None
    m = INSTANT_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        return datetime.datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=UTC,
        )
    except ValueError:
        return None


def format_instant(dt):
    """Render an instant with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------
def parse_date(value):
    """Parse a YYYY-MM-DD calendar date.  None when malformed."""
    if not isinstance(value, str):
        return None
    m = DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def format_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def date_at_midnight(d):
    """A calendar date interpreted at 00:00:00Z on that day."""
    if d is None:
        return None
    return datetime.datetime(d.year, d.month, d.day, tzinfo=UTC)


def nights_of(arrival, departure):
    """The half-open occupied nights [arrival_date, departure_date)."""
    out = []
    cur = arrival
    while cur < departure:
        out.append(cur)
        cur += datetime.timedelta(days=1)
    return out


# --------------------------------------------------------------------------
# money / decimals
# --------------------------------------------------------------------------
def to_decimal(value):
    """Coerce a JSON scalar to Decimal.  None when it is not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if not re.match(r"^-?\d+(\.\d+)?$", text):
            return None
        try:
            return Decimal(text)
        except InvalidOperation:
            return None
    return None


def fraction_digits(value):
    """How many fraction digits the caller actually wrote."""
    d = to_decimal(value)
    if d is None:
        return None
    exponent = d.as_tuple().exponent
    if not isinstance(exponent, int):
        return None
    return max(0, -exponent)


def money(value):
    """Round a Decimal to two places, half-up (PRD 2.5)."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_int(value):
    """Round to a whole number, half-up (the delegate person-night rule)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money_out(value):
    """Serialise a monetary Decimal as a JSON number with two decimals."""
    if value is None:
        return None
    return float(money(value))


def decimal_out(value):
    if value is None:
        return None
    return float(value)
