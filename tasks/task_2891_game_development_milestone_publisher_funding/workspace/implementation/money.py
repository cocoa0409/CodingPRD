"""Exact integer-cent arithmetic.

PRD 2.5: all monetary amounts are integer counts of cents; rates are basis
points and "wherever a rate is applied to an amount, the product is divided by
10000 and the result rounded half up to a whole number of cents. Rounding is
always half up, never banker's rounding and never truncation."

Every rounding in this system therefore goes through round_half_up() below,
which works on exact Fractions so no binary floating point error can ever
change a half-way case.
"""

from decimal import Decimal
from fractions import Fraction


def frac(value):
    """Coerce int / Decimal / Fraction / float / str into an exact Fraction."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, float):
        # str() gives the shortest repr that round-trips, so 97.99 -> "97.99".
        return Fraction(Decimal(str(value)))
    return Fraction(Decimal(str(value)))


def round_half_up(value):
    """Round an exact quantity to a whole number, half away from zero."""
    f = frac(value)
    num, den = f.numerator, f.denominator
    negative = num < 0
    num = -num if negative else num
    whole, rem = divmod(num, den)
    if 2 * rem >= den:
        whole += 1
    return -whole if negative else whole


def round_half_up_dp(value, places):
    """Round an exact quantity to `places` decimals, half away from zero.

    Returns a Fraction so downstream comparisons stay exact.
    """
    scale = 10 ** places
    return Fraction(round_half_up(frac(value) * scale), scale)


def apply_bps(amount, bps):
    """amount * bps / 10000, rounded half up to whole cents (PRD 2.5)."""
    return round_half_up(frac(amount) * bps / 10000)


def to_number(value):
    """Serialise an exact quantity as a JSON number."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return float(Fraction(frac(value)))
