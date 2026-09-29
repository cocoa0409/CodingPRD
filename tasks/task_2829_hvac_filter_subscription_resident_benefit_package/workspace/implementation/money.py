"""Exact-rational money arithmetic. PRD 2.6: whole signed cents, round half up
(away from zero on an exact half)."""
from fractions import Fraction


def frac(value):
    return value if isinstance(value, Fraction) else Fraction(value)


def round_half_up(value):
    """Round an exact rational to the nearest integer, halves away from zero."""
    x = frac(value)
    if x >= 0:
        n = x + Fraction(1, 2)
        return n.numerator // n.denominator
    n = (-x) + Fraction(1, 2)
    return -(n.numerator // n.denominator)


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
