"""Exact arithmetic helpers (PRD section 2.10).

Every monetary quantity is an integer number of cents.  Rounding is
"round half up": add one half to the exact decimal value and truncate toward
zero, so a fractional part of exactly one half always rounds away from zero
for the non-negative quantities this service deals in.
"""
import math
from decimal import Decimal
from fractions import Fraction


def exact(value):
    """Convert an int / float / str / Decimal / Fraction into an exact Fraction."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, float):
        # Go through str so 3.5 means exactly 3.5 (the decimal the client wrote)
        return Fraction(Decimal(repr(value)))
    if isinstance(value, str):
        return Fraction(Decimal(value))
    raise TypeError("cannot convert %r to an exact number" % (value,))


def round_half_up(value):
    """Round an exact quantity to an integer, halves away from zero."""
    return int(math.trunc(exact(value) + Fraction(1, 2)))


def as_float(fraction):
    """Render an exact ratio for JSON output."""
    if fraction is None:
        return None
    return float(fraction)
