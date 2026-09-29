"""Cents / basis-point arithmetic with the PRD's pinned rounding discipline (§2.6).

All monetary quantities are whole cents.  Proportions are basis points where
10000 bps is the whole.  Two rounding modes only:

  * round-half-up  (the default; ties round away from zero)
  * floor          (threshold measurements, truncated toward zero)
"""

from decimal import Decimal, ROUND_HALF_UP

BPS_DENOMINATOR = 10000
ADMIN_FEE_BAND_BREAK_CENTS = 5000000
VARIANCE_TOLERANCE_BPS = 200
WARN_BAND_BPS = 500
DAYS_PER_YEAR = 365


def round_half_up_div(numerator, denominator):
    """Exact numerator/denominator rounded half up (away from zero on a tie)."""
    q = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(q.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def apply_bps(amount, bps):
    """amount * bps / 10000 rounded half up to whole cents."""
    return round_half_up_div(int(amount) * int(bps), BPS_DENOMINATOR)


def floor_div(numerator, denominator):
    """Truncate the quotient toward zero."""
    numerator = int(numerator)
    denominator = int(denominator)
    q = abs(numerator) // abs(denominator)
    if (numerator < 0) != (denominator < 0):
        return -q
    return q


def floor_bps(numerator, denominator):
    """floor(numerator * 10000 / denominator)."""
    return floor_div(int(numerator) * BPS_DENOMINATOR, denominator)
