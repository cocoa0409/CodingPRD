"""Numeric helpers: cents rounding, four-decimal ratios, calendar months, instants."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- rounding
def rhu_int(value) -> int:
    """Round half up (away from zero on an exact half) to a whole integer."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu4(value) -> Decimal:
    """Round half up to four decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def ratio4(numerator: int, denominator: int) -> float:
    """numerator / denominator rounded half up to four decimals, as a float."""
    if denominator == 0:
        return 0.0
    return float(rhu4(Decimal(numerator) / Decimal(denominator)))


def bps_of(amount: int, bps: int) -> int:
    """amount * bps / 10000 rounded half up to whole cents."""
    return rhu_int(Decimal(amount) * Decimal(bps) / Decimal(10000))


# ---------------------------------------------------------------- instants
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_instant(raw):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None when invalid."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    match = _INSTANT_RE.match(text)
    if not match:
        return None
    year, month, day, hour, minute, second, frac, offset = match.groups()
    try:
        micros = 0
        if frac:
            micros = int((frac + "000000")[:6])
        moment = datetime(
            int(year), int(month), int(day),
            int(hour or 0), int(minute or 0), int(second or 0), micros,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        moment = moment - sign * delta
    return moment


def iso(moment) -> str:
    """Format an aware datetime as ISO 8601 UTC with exactly three fractional digits."""
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
        moment.microsecond // 1000,
    )


def add_months(moment: datetime, months: int) -> datetime:
    """Advance an instant by whole calendar months, clamping the day of month."""
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    day = min(moment.day, _days_in_month(year, month))
    return moment.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return (nxt - timedelta(days=1)).day


def hours_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600.0
