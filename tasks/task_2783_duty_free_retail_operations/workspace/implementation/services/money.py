"""Money is integer cents, rates are basis points (PRD section 2.6)."""
from decimal import Decimal, ROUND_HALF_UP

_ONE = Decimal("1")


def round_half_up(numerator, denominator=1):
    """Round numerator/denominator half up to a whole number."""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(_ONE, rounding=ROUND_HALF_UP))


def apply_bps(amount, bps):
    """amount * bps / 10000, rounded half up to whole cents."""
    return round_half_up(Decimal(amount) * Decimal(bps), 10000)


def floor_bps(amount, bps):
    """amount * bps / 10000, floored to a whole number (quantities, not money)."""
    return (int(amount) * int(bps)) // 10000
