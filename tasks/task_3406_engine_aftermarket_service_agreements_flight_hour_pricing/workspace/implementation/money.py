"""Decimal money/rate helpers (PRD 2.6).

Money is carried as Decimal and rounded half-up to 2 dp when stored; rates and
percentages to 4 dp. JSON representation is a plain number.
"""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
DP4 = Decimal("0.0001")


def to_decimal(value):
    """Coerce a JSON number (int/float, never bool) to an exact Decimal."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    raise ValueError("not a number")


def round2(d):
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def round4(d):
    return d.quantize(DP4, rounding=ROUND_HALF_UP)


def num(d):
    """Serialize a Decimal (or plain number) as a JSON number."""
    if d is None:
        return None
    if isinstance(d, Decimal):
        return float(d)
    return d
