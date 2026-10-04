"""Numeric disciplines.

All monetary figures are integer cents; numerators are Decimal so that the
half-up rounding rules in PRD.md 2.9 and 2.12 are reproduced exactly.  Final
stored figures are ints where the field is an integer and floats where the
field is a plain JSON number.
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

WHOLESALE = lambda v: v  # noqa: E731  (kept for readability at call sites)


def dec(value, default="0"):
    if value is None or value == "":
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value, places):
    """Round to `places` decimals, half up (PRD.md 2.9)."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def round_half_away(value, places):
    """Round to `places` decimals, half away from zero.

    Decimal's ROUND_HALF_UP already rounds away from zero for negatives, which
    is the semantic the education credit rule asks for.
    """
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Whole cents as an int, half up at zero decimal places."""
    return int(round_half_up(value, 0))


def as_float(value, places=None):
    d = dec(value)
    if places is not None:
        d = round_half_up(d, places)
    return float(d)


def as_int_cents(value):
    return int(round_half_up(value, 0))


def whole_days(start, end):
    """Whole-day difference between two instants (PRD.md 2.8)."""
    if start is None or end is None:
        return None
    return (end - start).days


def floor_int(value):
    """Whole-number floor of a Decimal."""
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def percent(numerator, denominator, places):
    if denominator is None or dec(denominator) == 0:
        return None
    return round_half_up(dec(numerator) / dec(denominator) * Decimal(100), places)