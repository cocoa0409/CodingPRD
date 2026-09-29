"""Datetime, decimal and JSON helpers.

PRD section 2.4: all instants exchanged with the API are ISO 8601 UTC and
server-minted audit timestamps carry three fractional digits.
PRD section 2.7: every percentage / index value carries exactly two decimal
places, is produced with decimal arithmetic and rounds HALF UP.
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc
Q2 = Decimal("0.01")
D0 = Decimal("0.00")
D100 = Decimal("100.00")


def r2(value):
    """Round to exactly two decimals, half up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Q2, rounding=ROUND_HALF_UP)


def num(value):
    """Normalise a value to a 2-decimal Decimal for JSON rendering.

    The response encoder writes a Decimal into the body as a bare JSON number
    carrying exactly two fractional digits (PRD 2.7).
    """
    if value is None:
        return None
    return r2(value)


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(raw):
    """Parse an ISO 8601 UTC instant. Returns None when malformed."""
    if not isinstance(raw, str):
        return None
    m = _DT_RE.match(raw.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, offset = m.groups()
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        moment = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second),
            micro, tzinfo=UTC,
        )
    except ValueError:
        return None
    if offset and offset[0] in "+-":
        sign = 1 if offset[0] == "+" else -1
        off_hours = int(offset[1:3])
        off_minutes = int(offset[-2:])
        moment = moment - sign * timedelta(hours=off_hours, minutes=off_minutes)
    return moment


def fmt_dt(moment):
    """Format an instant with exactly three fractional digits and a Z suffix."""
    if moment is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
        moment.microsecond // 1000,
    )


def add_days(moment, days):
    return moment + timedelta(days=days)


def whole_minutes(start, end):
    """Whole minutes between two instants, or None when not integral."""
    seconds = (end - start).total_seconds()
    if seconds != int(seconds) or int(seconds) % 60 != 0:
        return None
    return int(seconds) // 60


def median2(values):
    """Median of a list of Decimals; even counts average the two middles (half up)."""
    ordered_values = sorted(values)
    count = len(ordered_values)
    if count == 0:
        return D0
    mid = count // 2
    if count % 2 == 1:
        return r2(ordered_values[mid])
    return r2((ordered_values[mid - 1] + ordered_values[mid]) / Decimal(2))


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)
