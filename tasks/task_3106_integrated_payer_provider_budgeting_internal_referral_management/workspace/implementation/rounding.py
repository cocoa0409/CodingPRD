"""Rounding helpers. PRD 2.8: every rounding operation is round-half-up."""

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("1")
TWO_DP = Decimal("0.01")
ONE_DP = Decimal("0.1")


def dec(value):
    """Coerce to Decimal without routing through binary float where avoidable."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up_int(value):
    """Round to a whole integer cent using round-half-up."""
    return int(dec(value).quantize(CENT, rounding=ROUND_HALF_UP))


def round_half_up_dp(value, places):
    """Round to a fixed number of decimal places using round-half-up.

    Returns a Decimal carrying exactly `places` decimal digits.
    """
    quantum = ONE_DP if places == 1 else TWO_DP
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def clamp(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def number_out(value):
    """Serialise a number for JSON.

    Monetary values are plain ints and stay ints. Fields with declared decimal
    places (`wait_days`, `access_breach_pct`, `utilization_pct`) are Decimals
    and become floats, so a value of exactly 10 reads as 10.0 and a value of
    exactly 0 reads as 0.0.
    """
    if isinstance(value, Decimal):
        return float(value)
    return value