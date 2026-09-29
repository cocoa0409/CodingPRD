"""Numeric, rounding and time helpers.

All money and percentage arithmetic goes through decimal.Decimal with
ROUND_HALF_UP (never float, never Python's banker's round()).  Rounding is
applied to the magnitude with the sign preserved, which is exactly what
Decimal's ROUND_HALF_UP does.
"""
import math
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

UTC = timezone.utc

# --- constants (PRD 2.x / SCAFFOLD calculations[].constants) ----------------
PROMO_LIFT_PCT = Decimal("10")
COST_FLOOR_PCT = Decimal("40")
SELL_THROUGH_STEP_PCT = Decimal("20")
WASTE_HANDLING_PCT = Decimal("3.5")
DONATION_WINDOW_HOURS = 48
DOCK_BUFFER_MINUTES = 30
CREDIT_RATE_TIER_1_PCT = Decimal("62.5")
CREDIT_RATE_TIER_2_PCT = Decimal("72.5")
CREDIT_RATE_TIER_3_PCT = Decimal("80")
TIER_2_FLOOR_CENTS = 50000
TIER_3_FLOOR_CENTS = 200000
SEVERITY_TIER_2_HOURS = 48
SHRINK_LOOKBACK_DAYS = 7
ORDER_HORIZON_DAYS = 3
OVERCHARGE_ENFORCEMENT_CENTS = 25
POSTING_LAG_HOURS = 24


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value, places=0):
    """Decimal ROUND_HALF_UP quantize; ties go away from zero."""
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def rhu2(value):
    """Round to 2 decimals and hand back a JSON-friendly number."""
    return num(round_half_up(value, 2))


def num(value):
    """Serialise a Decimal as a JSON number, preferring int when integral."""
    d = D(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# --- time ------------------------------------------------------------------
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]00:00)$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(text):
    """Parse an ISO 8601 UTC instant, returning None when malformed."""
    if not isinstance(text, str):
        return None
    m = _INSTANT_RE.match(text)
    if not m:
        return None
    frac = m.group(7) or "0"
    micro = int((frac + "000000")[:6])
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=UTC,
        )
    except ValueError:
        return None


def parse_date(text):
    if not isinstance(text, str):
        return None
    m = _DATE_RE.match(text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_instant(moment):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if moment is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
        moment.microsecond // 1000,
    )


def midnight_utc(day):
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def end_of_day_utc(day):
    return datetime(day.year, day.month, day.day, 23, 59, 59, 999000, tzinfo=UTC)


def floor_div_seconds(delta_seconds, unit_seconds):
    """Floor toward negative infinity, e.g. 1.99 -> 1 and -0.25 -> -1."""
    return int(math.floor(D(delta_seconds) / D(unit_seconds)))


def seconds_between(later, earlier):
    return (later - earlier).total_seconds()


def add_seconds(moment, seconds):
    return moment + timedelta(seconds=seconds)
