"""Exact decimal arithmetic.

Every monetary amount in the programme is an integer number of cents; no float
ever touches money.  Rounding half away from zero is applied only where the PRD
says it is, and truncation toward zero only where the PRD says that.
"""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP


def round_half_up_ratio(numerator, denominator):
    """round_half_up(numerator / denominator) as an integer."""
    value = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round a Decimal to two decimal places, half away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def floor_ratio(numerator, denominator):
    """Truncate numerator / denominator toward zero."""
    value = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(value.quantize(Decimal("1"), rounding=ROUND_DOWN))


def decimal_out(value):
    """Render a 2-dp Decimal for the JSON body."""
    if value is None:
        return None
    return float(value)
