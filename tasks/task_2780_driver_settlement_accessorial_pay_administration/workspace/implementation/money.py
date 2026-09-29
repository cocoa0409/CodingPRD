"""Integer-cent arithmetic helpers (PRD section 2.6)."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up_div(numerator, denominator):
    """numerator / denominator rounded half up to a whole integer.

    The magnitude is rounded and the sign re-applied, so a down-grade and an
    up-grade of the same size round symmetrically (PRD section 2.6).
    """
    if numerator == 0:
        return 0
    sign = -1 if numerator < 0 else 1
    magnitude = Decimal(abs(int(numerator))) / Decimal(int(denominator))
    rounded = magnitude.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return sign * int(rounded)


def bps(amount, basis_points):
    """`basis_points` basis points of `amount`, rounded half up to whole cents."""
    return round_half_up_div(int(amount) * int(basis_points), 10000)


def round2(numerator, denominator):
    """numerator / denominator rounded half up to two decimal places (line quantities)."""
    if numerator == 0:
        return 0.0
    sign = -1 if numerator < 0 else 1
    magnitude = Decimal(abs(int(numerator))) / Decimal(int(denominator))
    rounded = magnitude.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(sign * rounded)
