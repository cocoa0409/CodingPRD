"""Rounding discipline (PRD 2.5), logical-clock date arithmetic (PRD 2.4)."""
import calendar
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

D = Decimal


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rnd(value, places):
    """Round half up on the magnitude to `places` decimal places."""
    if value is None:
        return None
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def decimals_of(value):
    """Number of decimal places in the literal the client supplied."""
    if isinstance(value, int):
        return 0
    exponent = dec(value).as_tuple().exponent
    if not isinstance(exponent, int):
        return 0
    return max(0, -exponent)


ISO_INSTANT = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(text):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(text, str):
        return None
    m = ISO_INSTANT.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    body = offset[1:].replace(":", "")
    delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * delta).replace(tzinfo=timezone.utc)


def parse_date(text):
    if not isinstance(text, str):
        return None
    m = ISO_DATE.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_instant(moment):
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day, moment.hour,
        moment.minute, moment.second, moment.microsecond // 1000,
    )


def fmt_date(value):
    return None if value is None else value.isoformat()


def add_months(base, months):
    """Advance a date by whole calendar months, clamping the day (PRD 2.4)."""
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def completed_years(birth, today):
    years = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        years -= 1
    return years


def completed_months(start, end):
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


DECIMAL_SENTINEL = "N" + uuid.uuid4().hex + "N"
_DECIMAL_PATTERN = re.compile('"%s(-?[0-9]+(?:\\.[0-9]+)?)%s"'
                              % (DECIMAL_SENTINEL, DECIMAL_SENTINEL))


def decimal_text(value):
    """The exact digits of a Decimal, never in exponent notation."""
    return format(value, "f")


def dumps(payload):
    """Serialise with Decimals emitted as bare numbers keeping their scale."""
    return _DECIMAL_PATTERN.sub(r"\1", json.dumps(jsonable(payload)))


def jsonable(value):
    """Wrap Decimals in a sentinel so dumps() can emit their exact digits."""
    if isinstance(value, Decimal):
        return DECIMAL_SENTINEL + decimal_text(value) + DECIMAL_SENTINEL
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, datetime):
        return fmt_instant(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
