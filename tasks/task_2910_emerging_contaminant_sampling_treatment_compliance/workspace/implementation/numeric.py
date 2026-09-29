"""Decimal helpers.  Money is always an integer count of cents; every other
declared-precision quantity is a quantized Decimal.  Rounding is round-half-up
(away from zero on an exact tie) — never truncation, never bankers' rounding.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, localcontext

D0 = Decimal(0)
D2 = Decimal("0.01")
D4 = Decimal("0.0001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    with localcontext() as ctx:
        ctx.prec = 60
        return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a monetary expression to a whole number of cents."""
    return int(round_half_up(value, 0))


def q2(value):
    return round_half_up(value, 2)


def q4(value):
    return round_half_up(value, 4)


def divide(numerator, denominator):
    """Exact-as-possible decimal division at high precision (no rounding yet)."""
    with localcontext() as ctx:
        ctx.prec = 60
        return dec(numerator) / dec(denominator)


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def decimal_places(value):
    exponent = dec(value).as_tuple()[2]
    if not isinstance(exponent, int):
        return 0
    return max(0, -exponent)
