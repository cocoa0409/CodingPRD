"""Decimal helpers: every quantity in this service is exact (PRD 2.7)."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, InvalidOperation

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


def dec(value):
    """Convert an incoming JSON scalar to an exact Decimal (or None)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            return Decimal(text)
        except InvalidOperation:
            return None
    return None


def rhu(value, places):
    """Round half up to `places` decimal places."""
    if value is None:
        return None
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to a whole number of cents (an integer)."""
    if value is None:
        return None
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def trunc(value):
    """Truncate toward zero (floor for non-negative quantities)."""
    if value is None:
        return None
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_DOWN))


def scale(value, places):
    """Present a stored decimal at its documented scale."""
    if value is None:
        return None
    return rhu(value, places)


def is_int_like(value):
    return isinstance(value, int) and not isinstance(value, bool)


def rhu_frac(fraction_value, places):
    """Round an exact Fraction half up to `places` places (non-negative only).

    Used where the PRD pins accumulation "at full precision without rounding"
    so the single rounding at the end is the only one that happens.
    """
    scaled = fraction_value * (10 ** places)
    numerator, denominator = scaled.numerator, scaled.denominator
    whole = numerator // denominator
    remainder = numerator - whole * denominator
    if remainder * 2 >= denominator:
        whole += 1
    return rhu(Decimal(whole).scaleb(-places), places)
