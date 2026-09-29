"""Exact arithmetic helpers.

Every quantity that feeds a stored value is evaluated as an exact rational
(fractions.Fraction) and rounded exactly once, half up (away from zero at the
midpoint), as required by PRD 2.6.  Floats are never used for money.
"""
from decimal import Decimal
from fractions import Fraction


def to_frac(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value))
    if isinstance(value, str):
        return Fraction(Decimal(value))
    raise TypeError("unsupported numeric type: %r" % (value,))


def round_half_up_int(value):
    """Round an exact rational half up to a whole number (money in cents)."""
    f = to_frac(value)
    num, den = f.numerator, f.denominator
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


def round_half_up_dec(value, places=2):
    """Round an exact rational half up to `places` decimals -> Decimal."""
    scale = Fraction(10) ** places
    scaled = round_half_up_int(to_frac(value) * scale)
    return Decimal(scaled).scaleb(-places)


def ceil_frac(value):
    f = to_frac(value)
    return -((-f.numerator) // f.denominator)


def dec2(value):
    """Normalise a percentage input to a 2-decimal Decimal (half up)."""
    return round_half_up_dec(value, 2)


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    return value
