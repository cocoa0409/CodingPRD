"""Decimal money helpers.

Every monetary figure is computed with decimal arithmetic and quantised to two
decimal places using round-half-up (PRD §2.7).  Floats are never used for money.
"""

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
TWO_PLACES = Decimal("0.01")


def dec(value):
    """Coerce a JSON number to Decimal without passing through binary float."""
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_cents(value):
    """Round half up to exactly two decimal places."""
    return dec(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_int(value):
    """Round half up to a whole integer (PRD §2.7: appointment_priority)."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def as_number(value):
    """Serialise a Decimal cent amount as a JSON number.

    Whole amounts come out as ints (the API exposes integer cent values as
    numbers); fractional amounts keep at most two decimals.
    """
    if value is None:
        return 0
    d = round_cents(value)
    if d == d.to_integral_value():
        return int(d.to_integral_value())
    return float(d.normalize())


def pct(value):
    """Two-decimal percentage, rounded half up, serialised as a number."""
    d = dec(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    if d == d.to_integral_value():
        return int(d.to_integral_value())
    return float(d)