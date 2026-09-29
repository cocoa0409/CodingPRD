"""Low level helpers: decimal money, instants, ids.

Money is always Decimal with ROUND_HALF_UP quantisation (PRD 2.5).
Instants are timezone aware UTC datetimes, serialised as ISO 8601 with
exactly three fractional digits and a trailing Z (PRD 2.2 / 2.4).
"""
from __future__ import annotations

import calendar
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

UTC = timezone.utc

CENTS = Decimal("0.01")
FOUR = Decimal("0.0001")
SIX = Decimal("0.000001")
ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")
ONE = Decimal("1")


def _dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q2(value) -> Decimal:
    """Round to 2 decimal places, half up."""
    return _dec(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def q4(value) -> Decimal:
    """Round to 4 decimal places, half up."""
    return _dec(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def q6(value) -> Decimal:
    """Round to 6 decimal places, half up."""
    return _dec(value).quantize(SIX, rounding=ROUND_HALF_UP)


def to_decimal(value):
    """Coerce a JSON scalar into a finite Decimal, or None when impossible."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        try:
            d = Decimal(str(value))
        except InvalidOperation:
            return None
        return d if d.is_finite() else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            d = Decimal(text)
        except InvalidOperation:
            return None
        return d if d.is_finite() else None
    return None


def to_int(value):
    """Coerce a JSON scalar into an int, or None when impossible."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    d = to_decimal(value)
    if d is None:
        return None
    if d == d.to_integral_value():
        return int(d)
    return None


def num_out(value):
    """Serialise a Decimal (or number) as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def money_out(value):
    if value is None:
        return None
    return float(q2(value))


def pct4_out(value):
    if value is None:
        return None
    return float(q4(value))


_FRAC_RE = re.compile(r"\.(\d+)")


def parse_instant(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    # normalise fractional second width so fromisoformat accepts it everywhere
    match = _FRAC_RE.search(text)
    if match:
        digits = match.group(1)
        if len(digits) != 6:
            padded = (digits + "000000")[:6]
            text = text[: match.start(1)] + padded + text[match.end(1) :]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso(instant):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if instant is None:
        return None
    instant = instant.astimezone(UTC)
    millis = instant.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        instant.year,
        instant.month,
        instant.day,
        instant.hour,
        instant.minute,
        instant.second,
        millis,
    )


def wall_now():
    """Real clock — used only for created_at / updated_at bookkeeping."""
    return datetime.now(UTC)


def add_months(instant, months):
    """Same day-of-month, clamped to the last day of a shorter month."""
    months = int(months)
    total = instant.month - 1 + months
    year = instant.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return instant.replace(year=year, month=month, day=min(instant.day, last_day))


def add_days(instant, days):
    return instant + timedelta(days=int(days))


def whole_days_between(start, end):
    """Whole days from start to end, truncated toward zero for positives."""
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 86400)


def whole_minutes_between(start, end):
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 60)


def new_id():
    return str(uuid.uuid4())


_ALPHABET = string.ascii_lowercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(24))
