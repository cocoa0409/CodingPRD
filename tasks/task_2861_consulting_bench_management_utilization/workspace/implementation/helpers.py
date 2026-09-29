"""Decimal, date and workday helpers.

All rounding in this system is round-half-up applied at the decimal width the
field declares (PRD 2.6). Money and every other numeric quantity is handled as
decimal.Decimal -- never float -- and only converted to a JSON number at the
edge of the serializers.
"""
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

UTC = timezone.utc

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,29}$")

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def dec(value):
    """Coerce a JSON scalar to Decimal. Raises ValueError for non-numbers."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    raise ValueError("not a number")


def rnd(value, places):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return rnd(value, 2)


def q4(value):
    return rnd(value, 4)


def num(value):
    """Render a Decimal as a JSON number (never a string)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return float(value)
        return float(value)
    return value


def decimal_places(value):
    """Number of digits after the decimal point in the literal supplied."""
    d = dec(value).normalize()
    exp = d.as_tuple().exponent
    if not isinstance(exp, int):
        return 0
    return max(0, -exp)


def parse_date(value):
    """Strict ISO 8601 calendar date (YYYY-MM-DD). Returns None when invalid."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_instant(value):
    """ISO 8601 UTC instant. Tolerant about fractional-second width and about a
    trailing offset, because the value is only ever used to move the logical
    clock; a malformed value returns None and becomes ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(txt)
    except ValueError:
        if DATE_RE.match(raw):
            day = parse_date(raw)
            if day is None:
                return None
            return datetime(day.year, day.month, day.day, tzinfo=UTC)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def fmt_date(day):
    return None if day is None else day.isoformat()


def fmt_instant(moment):
    if moment is None:
        return None
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def is_workday(day):
    return day.weekday() < 5


def workdays(start, end_exclusive):
    """Count Monday-Friday dates in the half-open range [start, end)."""
    if start is None or end_exclusive is None or end_exclusive <= start:
        return 0
    span = (end_exclusive - start).days
    weeks, rest = divmod(span, 7)
    total = weeks * 5
    weekday = start.weekday()
    for offset in range(rest):
        if (weekday + offset) % 7 < 5:
            total += 1
    return total


def workdays_inclusive(start, end_inclusive):
    if start is None or end_inclusive is None:
        return 0
    return workdays(start, end_inclusive + timedelta(days=1))


def day_after(day):
    return None if day is None else day + timedelta(days=1)
