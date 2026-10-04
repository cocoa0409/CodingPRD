"""Monetary arithmetic.

Every monetary value is an integer number of cents.  The only rounding
primitive is round-half-up to the cent, applied at exactly the points named in
the calculation rules; ceiling is used only where a rule names it (PRD 2.7).
"""

import math
from decimal import Decimal, ROUND_HALF_UP


def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    """Round half-up (not banker's rounding) to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return int(to_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP))


def round_ceil(value):
    """Smallest integer at or above the value."""
    return int(math.ceil(float(to_decimal(value))))


def as_int(value, field="value"):
    if isinstance(value, bool):
        raise TypeError("%s must be an integer" % field)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            raise TypeError("%s must be an integer" % field)
        return int(value)
    if isinstance(value, str):
        return int(value.strip())
    raise TypeError("%s must be an integer" % field)


def as_number(value, field="value"):
    if isinstance(value, bool):
        raise TypeError("%s must be a number" % field)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value.strip())
    raise TypeError("%s must be a number" % field)


def apply_rate(cents, rate):
    """cents * rate, rounded half-up to the cent."""
    return round_half_up(to_decimal(cents) * to_decimal(rate))


def scale_no_round(cents, rate):
    """Exact product of two decimal quantities (no rounding named)."""
    return to_decimal(cents) * to_decimal(rate)