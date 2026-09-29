"""Decimal money helpers. Money is never a float in the arithmetic path."""
import math
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q2(value):
    """Round to two decimal places, half away from zero."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal for JSON output."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def pct_of(amount, pct):
    """round(amount * pct / 100, 2)."""
    return q2(D(amount) * D(pct) / Decimal(100))


def floor_div_seconds(delta_seconds, unit):
    return int(math.floor(delta_seconds / float(unit)))
