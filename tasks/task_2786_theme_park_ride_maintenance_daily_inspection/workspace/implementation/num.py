"""Exact rational arithmetic with round-half-up rounding (PRD 2.10)."""

import math
from fractions import Fraction

HALF = Fraction(1, 2)


def frac(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def round_half_up(value, places=0):
    """Round half away from zero to `places` decimals, returning a Fraction."""
    scale = 10 ** places
    scaled = frac(value) * scale
    if scaled >= 0:
        rounded = math.floor(scaled + HALF)
    else:
        rounded = -math.floor(-scaled + HALF)
    return Fraction(rounded, scale)


def cents(value):
    """Round half up to a whole cent."""
    return int(round_half_up(value, 0))


def hundredths(value):
    """Round half up to 2 decimals, returned as an integer count of 1/100."""
    return int(round_half_up(value, 2) * 100)


def dec2(value):
    """Render a value as a JSON number carrying exactly 2 decimal places."""
    return float(round_half_up(value, 2))


def from_hundredths(count):
    return float(Fraction(int(count), 100))


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)
