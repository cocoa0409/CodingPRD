"""Money and rate arithmetic.

PRD 2.10: all monetary amounts are integer cents; where a computation produces
a fractional result the standard is round half up.  Rates are decimals and are
never float, because IEEE 754 would make 0.1 + 0.2 != 0.3.
"""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("1")
TENTH = Decimal("0.1")
TEN_THOUSANDTH = Decimal("0.0001")


def dec(value, default="0"):
    """Coerce an int / Decimal / numeric string to Decimal without touching float."""
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(default)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # Only reached for JSON numbers the client sent as floats; repr keeps
        # the shortest round-tripping decimal so 0.85 stays 0.85, not 0.84999...
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            return Decimal(default)
    return Decimal(default)


def round_cents(value):
    """Round a Decimal to whole cents, half up, and return an int."""
    return int(dec(value).quantize(CENT, rounding=ROUND_HALF_UP))


def round_tenth(value):
    """Round to one decimal place, half up, and return a Decimal."""
    return dec(value).quantize(TENTH, rounding=ROUND_HALF_UP)


def round_ten_thousandth(value):
    """Round to four decimal places, half up, and return a Decimal."""
    return dec(value).quantize(TEN_THOUSANDTH, rounding=ROUND_HALF_UP)


def ceil_div(numerator, denominator):
    """Ceiling division over integers (denominator > 0)."""
    numerator = int(numerator)
    denominator = int(denominator)
    return -((-numerator) // denominator)


def ceil_int(value):
    """Ceiling of a Decimal to an int."""
    d = dec(value)
    floored = int(d)
    if d > floored:
        return floored + 1
    return floored


def as_number(value):
    """A Decimal rendered for JSON: int when integral, else float.

    Rate fields preserve the precision at which they were supplied (PRD 2.10),
    so a supplied 0.15 comes back as 0.15 rather than being re-rounded.
    """
    d = dec(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)