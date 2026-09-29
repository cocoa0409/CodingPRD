"""Shared primitives: ids, logical-clock formatting, date math, money rounding."""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- identifiers
_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    """Entity identifier: a UUID with no prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """meta.api_request_id: 'req_' + 20 alphanumeric characters (PRD 2.2)."""
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# ---------------------------------------------------------------- timestamps
def iso_ts(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_instant(value):
    """Parse an ISO 8601 instant. Returns a naive UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        # bare date is an acceptable instant spelling
        try:
            d = date.fromisoformat(raw)
        except ValueError:
            return None
        return datetime(d.year, d.month, d.day)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_day(value):
    """Parse a calendar date (YYYY-MM-DD). Returns a date or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        return date.fromisoformat(raw[:10]) if len(raw) >= 10 else date.fromisoformat(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------- date math
def add_days(dt, n):
    return dt + timedelta(days=n)


def add_months_date(d, n):
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_months_dt(dt, n):
    d = add_months_date(dt.date(), n)
    return datetime(d.year, d.month, d.day, dt.hour, dt.minute, dt.second, dt.microsecond)


def whole_months_between(start, end):
    """Whole calendar months elapsed from `start` to `end` (both dates)."""
    if end <= start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def month_ends_before(as_of, earliest):
    """Every calendar month-end date strictly before `as_of`, from `earliest` on."""
    out = []
    if earliest is None:
        return out
    year, month = earliest.year, earliest.month
    guard = 0
    while guard < 6000:
        guard += 1
        last = month_end(year, month)
        if last >= as_of:
            break
        out.append(last)
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


# ---------------------------------------------------------------- money
def round_half_up(value):
    """Round half up to a whole cent (PRD 2.5 default rounding)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mul_round_half_up(amount, factor):
    return int((Decimal(amount) * Decimal(str(factor))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def mul_floor(amount, factor):
    """Floor of amount * factor — CCPA cap and aggregate cap (PRD 2.5)."""
    return int((Decimal(amount) * Decimal(str(factor))) // 1)


def ratio_4dp(numerator, denominator):
    """Income share ratio: round half up to four decimal places (PRD 2.5)."""
    if denominator == 0:
        return Decimal("0.0000")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)


def as_number(dec):
    """Render a Decimal ratio/percentage as a JSON number."""
    if dec is None:
        return None
    return float(dec)
