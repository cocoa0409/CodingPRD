"""Numeric helpers: round half up with a declared number of places."""
from decimal import Decimal, ROUND_HALF_UP


def r2(value, places=2):
    """Round half up to `places` decimal places; returns a float."""
    return float(Decimal(str(value)).quantize(Decimal("1e-%d" % places), rounding=ROUND_HALF_UP))


def r1(value):
    return r2(value, 1)


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def r1_clamped(value, low=0.0, high=100.0):
    return clamp(r1(value), low, high)


def floor_half(value):
    """The integer floor of half of `value`, floored at zero (carry pool term)."""
    half = value / 2.0
    floored = int(half // 1)
    return floored if floored > 0 else 0


def ceil_int(value):
    """Smallest integer >= value (used by the over-ceiling term)."""
    from math import ceil

    return int(ceil(value))


def clean(value):
    """Normalise a float for JSON: integral values become ints."""
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


def eff(value):
    """Effective on-hand value: authoritatively zero below the depletion epsilon."""
    if value is None:
        return 0.0
    return 0.0 if abs(value) <= 0.0001 else value