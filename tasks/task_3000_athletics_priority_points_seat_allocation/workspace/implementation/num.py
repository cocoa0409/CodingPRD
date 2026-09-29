"""Exact decimal arithmetic helpers (PRD section 2.6).

Money is integer cents, points carry exactly 2 decimal places, ratios 4, and
every rounding step rounds half up.  Nothing here ever touches binary floats.
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")
ZERO2 = Decimal("0.00")


def dec(value):
    """Coerce an int / str / Decimal to Decimal.  Raises for anything else."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise InvalidOperation("boolean is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value).strip())


def round2(value):
    return dec(value).quantize(TWO, rounding=ROUND_HALF_UP)


def round4(value):
    return dec(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round a raw product half up to whole cents and return an int."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_zero(value):
    """Point results are floored at zero (PRD section 2.6)."""
    value = dec(value)
    return ZERO2 if value < ZERO2 else value


def points_out(value):
    """Serialise a point quantity as a JSON number with 2 decimal places."""
    if value is None:
        return None
    return float(round2(value))


def ratio_out(value):
    if value is None:
        return None
    return float(round4(value))
