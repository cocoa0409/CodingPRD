"""Decimal money / rate discipline (PRD 2.5).

"All arithmetic on money and on rates is performed in decimal, never in binary
floating point, and every rounding step in this specification uses the round
half up method."
"""
from decimal import Decimal, ROUND_HALF_UP

ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")
CENT = Decimal("0.01")
RATIO = Decimal("0.0001")


def d(v):
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def q2(v):
    """Round half up to 2 decimal places."""
    return d(v).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(v):
    """Round half up to 4 decimal places."""
    return d(v).quantize(RATIO, rounding=ROUND_HALF_UP)


def m(v):
    """Serialise a monetary figure: exactly 2 decimal places."""
    if v is None:
        return None
    return float(q2(v))


def r(v):
    """Serialise a ratio-valued figure: exactly 4 decimal places."""
    if v is None:
        return None
    return float(q4(v))
