"""Numeric / temporal primitives.

PRD 2.4: every monetary amount is an integer in minor units; every percentage or
ratio carries exactly four decimal places (scores two).  All rounding is
round-half-up.  There is no wall clock: instants come from the logical clock.
Timestamps are ISO-8601 UTC with exactly three fractional-second digits.
"""
import datetime as _dt
import re
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, localcontext
from fractions import Fraction

# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

D0 = Decimal("0")
Q4 = Decimal("0.0001")
Q2 = Decimal("0.01")
Q1 = Decimal("1")

HUNDRED = Decimal("100")


def dec(value):
    """Coerce to Decimal without ever going through binary float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, Fraction):
        with localcontext() as ctx:
            ctx.prec = 60
            return Decimal(value.numerator) / Decimal(value.denominator)
    if isinstance(value, bool):
        raise TypeError("bool is not numeric here")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def frac(value):
    """Coerce to an exact Fraction (used where division must not lose bits)."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def _quantize_frac(value, quant):
    """round_half_up of an exact Fraction onto the given quantum."""
    f = frac(value)
    step = frac(quant)
    scaled = f / step
    n = scaled.numerator
    d = scaled.denominator
    if n >= 0:
        units = (2 * n + d) // (2 * d)
    else:
        units = -((2 * (-n) + d) // (2 * d))
    return (Decimal(units) * quant).quantize(quant)


def round_half_up(value, places=0):
    """round_half_up onto `places` decimals.  Exact for int/Decimal/Fraction."""
    quant = Decimal(1).scaleb(-places)
    if isinstance(value, Fraction):
        return _quantize_frac(value, quant)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    """round_half_up to an integer number of minor units."""
    return int(round_half_up(value, 0))


def pct4(value):
    """Canonical four-decimal percentage."""
    if isinstance(value, Fraction):
        return _quantize_frac(value, Q4)
    return dec(value).quantize(Q4, rounding=ROUND_HALF_UP)


def score2(value):
    if isinstance(value, Fraction):
        return _quantize_frac(value, Q2)
    return dec(value).quantize(Q2, rounding=ROUND_HALF_UP)


def floor_4dp(value):
    """Truncation toward zero at the fourth decimal (never rounding up)."""
    if isinstance(value, Fraction):
        n = value.numerator * 10000
        d = value.denominator
        units = n // d if n >= 0 else -((-n) // d)
        return (Decimal(units) * Q4).quantize(Q4)
    return dec(value).quantize(Q4, rounding=ROUND_DOWN)


def ceil_div(n, d):
    """Integer ceiling division for non-negative d."""
    if d == 0:
        return 0
    q, r = divmod(n, d)
    return q + (1 if r else 0)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{3})Z$")
UTC = _dt.timezone.utc


def parse_instant(text):
    """Parse an ISO-8601 UTC instant with exactly three fractional digits.

    Returns an aware datetime, or None when the shape is not accepted.
    """
    if not isinstance(text, str):
        return None
    m = TS_RE.match(text)
    if not m:
        return None
    y, mo, d, h, mi, s, ms = (int(g) for g in m.groups())
    try:
        return _dt.datetime(y, mo, d, h, mi, s, ms * 1000, tzinfo=UTC)
    except ValueError:
        return None


def fmt_instant(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    v = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond // 1000,
    )


def add_days(instant, days):
    return instant + _dt.timedelta(days=days)


def day_span(later, earlier):
    """floor of the whole-day distance between two instants (may be negative)."""
    delta = later - earlier
    total = delta.total_seconds()
    return int(total // 86400)
