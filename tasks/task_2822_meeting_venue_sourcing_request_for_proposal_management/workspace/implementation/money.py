"""Decimal helpers.  All money is 2dp ROUND_HALF_UP (PRD section 2.5)."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

ZERO = Decimal("0.00")
TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not numeric")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q2(value):
    return D(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def q4(value):
    return D(value).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def qn(value, places):
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def num(value):
    """Render a Decimal for JSON as a plain number (never a string)."""
    if value is None:
        return None
    return float(value)
