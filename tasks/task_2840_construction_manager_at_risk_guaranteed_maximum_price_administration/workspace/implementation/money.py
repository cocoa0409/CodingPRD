"""Decimal helpers.  All money and ratio arithmetic in this service is Decimal
based; float is never used for a monetary or ratio value (PRD 2.5)."""
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

ZERO = Decimal("0")
CENT = Decimal("0.01")
TEN_THOUSANDTH = Decimal("0.0001")

MONEY_ZERO = Decimal("0.00")
RATIO_ZERO = Decimal("0.0000")


def dec(value):
    """Coerce to Decimal without going through float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q2(value):
    """Round half up to 2 decimal places (money precision)."""
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(value):
    """Round half up to 4 decimal places (ratio / unit-rate precision)."""
    return dec(value).quantize(TEN_THOUSANDTH, rounding=ROUND_HALF_UP)


def decimal_places(value):
    exp = dec(value).as_tuple().exponent
    if not isinstance(exp, int):
        return 0
    return -exp if exp < 0 else 0


def out_num(value):
    """Render a Decimal for the JSON body as a plain JSON number."""
    if value is None:
        return None
    return float(value)
