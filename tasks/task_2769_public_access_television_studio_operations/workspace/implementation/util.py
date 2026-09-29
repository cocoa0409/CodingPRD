"""Time, formatting and integer/basis-point arithmetic helpers.

PRD 2.6:
  * money is integer cents only;
  * a basis-point rate is applied as (cents * bp) / 10000 rounded half up;
  * where several rated lines are summed, each line is rounded first;
  * where a per-unit fee is multiplied by a unit count, the per-unit fee is
    rounded once and the product is taken exactly.
PRD 2.4: created_at / updated_at carry three fractional digits.
PRD 2.6: service-computed instants are at second precision.
"""

import calendar
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# datetimes
# --------------------------------------------------------------------------- #
def parse_iso(value):
    """Parse an ISO-8601 string to an aware UTC datetime; None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso_s(dt):
    """Second-precision ISO-8601 UTC instant, e.g. 2026-08-10T18:00:00Z."""
    if dt is None:
        return None
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_ms(dt):
    """Three-fractional-digit ISO-8601 UTC instant (created_at / updated_at)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def seconds_after_midnight(dt):
    dt = dt.astimezone(UTC)
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def minutes_after_midnight(dt):
    """PRD 3.4: hour * 60 + minute."""
    dt = dt.astimezone(UTC)
    return dt.hour * 60 + dt.minute


def add_seconds(dt, seconds):
    return dt + timedelta(seconds=seconds)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    """Advance by whole calendar months, clamping the day to the month's end."""
    dt = dt.astimezone(UTC)
    total = (dt.year * 12) + (dt.month - 1) + months
    year = total // 12
    month = (total % 12) + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# --------------------------------------------------------------------------- #
# arithmetic
# --------------------------------------------------------------------------- #
def round_half_up_div(numerator, denominator):
    """Integer division of non-negative integers, rounding the quotient half up."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    negative = numerator < 0
    n = -numerator if negative else numerator
    quotient, remainder = divmod(n, denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return -quotient if negative else quotient


def apply_bp(cents, bp):
    """cents * bp / 10000, rounded half up to a whole cent."""
    return round_half_up_div(int(cents) * int(bp), 10000)


def ceil_div(numerator, denominator):
    """Ceiling division for non-negative integers."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return -((-int(numerator)) // int(denominator))


def clip_fraction(numerator, denominator):
    """numerator / denominator as an exact Decimal, clipped at 1."""
    value = Decimal(int(numerator)) / Decimal(int(denominator))
    one = Decimal(1)
    return one if value > one else value


def quantize2(value):
    """Round a Decimal half up to two fraction digits."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decimal_to_number(value):
    """Emit a two-decimal Decimal as a JSON number."""
    return float(value)
