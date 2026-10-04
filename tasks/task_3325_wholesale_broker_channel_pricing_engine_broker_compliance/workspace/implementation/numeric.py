"""Decimal helpers. Money and rates never touch binary floating point."""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")
HUNDRED = Decimal("100")


def to_decimal(value, default=None):
    """Coerce a JSON number/string to an exact Decimal."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return Decimal(text)
        except InvalidOperation:
            return default
    return default


def quantize(value, places):
    """Round half up to `places` decimal places."""
    exponent = Decimal(1).scaleb(-places)
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def round_half_up(value, places):
    return quantize(value, places)


def round_int(value):
    """Round half up to a whole number, returned as a Python int."""
    return int(quantize(value, 0))


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def dump_decimal(value, places=None):
    """Render a Decimal as a JSON float with a fixed number of decimals."""
    if value is None:
        return None
    if places is not None:
        value = quantize(value, places)
    return float(value)


def all_values_equal(*values):
    seen = None
    for value in values:
        if seen is None:
            seen = value
        elif value != seen:
            return False
    return True