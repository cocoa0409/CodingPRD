"""Exact decimal arithmetic helpers (PRD 2.4).

All money is integer cents.  Percentages, indices and ratios are Decimal.
Rounding is half-up unless the PRD says floor.  No float ever participates in
an arithmetic step; floats appear only at JSON serialisation.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def D(value):
    """Coerce to Decimal without ever going through binary float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a number here")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def half_up(value, places=0):
    """Round half-up to `places` decimal places, returning a Decimal."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half-up to whole cents, returning an int."""
    return int(half_up(value, 0))


def floor_int(value):
    """Floor toward negative infinity, returning an int."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def q2(value):
    return half_up(value, 2)


def q4(value):
    return half_up(value, 4)


def out_num(value):
    """Render a Decimal for JSON: a float that keeps the decided scale."""
    if value is None:
        return None
    return float(value)
