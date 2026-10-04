"""Round-half-up helpers.

PRD §2.8: every monetary quantity is integer cents, every rounding is
round-half-up, and the *point* at which rounding is applied is pinned per
calculation.  Python's built-in round() is banker's rounding, so it is never
used for these values.
"""

from decimal import Decimal, ROUND_HALF_UP


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def rhu(value, places=0):
    """Round half up to `places` decimal places, returning a Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value, places=0):
    """Round half up and return a Python int (for integer-cent quantities)."""
    return int(rhu(value, places))


def rhu_pct(value):
    """Two-decimal percentage point value as a float (PRD §2.8)."""
    return float(rhu(value, 2))


def floor_div_int(numerator, denominator):
    """Integer floor division that rounds toward negative infinity less often
    than Python's // for our non-negative inputs -- kept explicit so the
    "floors, never rounds" rule in seller_constraint_exposure is visible."""
    import math
    return int(math.floor(dec(numerator) / dec(denominator)))