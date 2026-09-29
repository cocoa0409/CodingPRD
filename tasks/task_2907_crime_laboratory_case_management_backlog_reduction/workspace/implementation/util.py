"""Numeric and temporal helpers (PRD sections 2.4, 2.5, 2.6)."""
import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

TWO = Decimal("0.01")
ONE = Decimal("1")

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})$"
)


def dec(value):
    """Decimal from a JSON number or string, without binary float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q2(value):
    """Round half up to 2 decimal places."""
    return dec(value).quantize(TWO, rounding=ROUND_HALF_UP)


def qcents(value):
    """Round half up to whole (integer) cents."""
    return int(dec(value).quantize(ONE, rounding=ROUND_HALF_UP))


def parse_instant(text):
    """Parse an ISO-8601 UTC instant. Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    m = _ISO_RE.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tz = m.groups()
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        base = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second),
            micro, tzinfo=UTC,
        )
    except ValueError:
        return None
    if tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:]))
        base = base - sign * offset
    return base


def fmt_instant(moment):
    """ISO-8601 UTC with exactly three fractional-second digits."""
    if moment is None:
        return None
    moment = moment.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
        moment.microsecond // 1000,
    )


def whole_seconds(start, end):
    """Difference in whole seconds between two instants."""
    return int((end - start).total_seconds())


def whole_day_floor(start, end):
    """Whole-day floor: whole seconds / 86400 with the remainder discarded."""
    return int(math.floor(whole_seconds(start, end) / 86400.0))


def fractional_days(start, end):
    """Fractional-day figure: whole seconds / 86400 rounded half up to 2dp."""
    return q2(Decimal(whole_seconds(start, end)) / Decimal(86400))


def add_days(moment, days):
    return moment + timedelta(days=days)


def as_number(value):
    """JSON-serialisable number for a Decimal."""
    if value is None:
        return None
    return float(value)
