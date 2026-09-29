"""Exact rational arithmetic helpers.

PRD 2.6: money is whole cents, catalog prices are whole micro-dollars, proportions
are whole basis points. Rounding is round-half-up (magnitude based), ceiling where
the document says "rounded up", floor where it says "rounded down". Each rounding
step happens exactly where the calculation names it and never a second time.
"""
from decimal import Decimal
from fractions import Fraction

MICROS_PER_CENT = 10000
BPS_UNITY = 10000


def frac(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(Decimal(str(value)))
    return Fraction(value)


def round_half_up(value):
    """Round an exact rational to the nearest integer, ties away from zero."""
    f = frac(value)
    n, d = f.numerator, f.denominator
    if n >= 0:
        return (2 * n + d) // (2 * d)
    return -((2 * (-n) + d) // (2 * d))


def ceil_int(value):
    f = frac(value)
    return -((-f.numerator) // f.denominator)


def floor_int(value):
    f = frac(value)
    return f.numerator // f.denominator


def apply_bps(amount, bps):
    """round_half_up(amount * bps / 10000)."""
    return round_half_up(Fraction(amount) * Fraction(bps, BPS_UNITY))


def micros_to_cents(qty, unit_price_micros):
    """round_half_up(qty * unit_price_micros / 10000)."""
    return round_half_up(Fraction(qty * unit_price_micros, MICROS_PER_CENT))
