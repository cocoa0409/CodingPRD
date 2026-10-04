from decimal import Decimal, ROUND_HALF_UP


def round_half_up_2dp(value):
    """Round a Decimal or numeric to exactly 2 decimal places, half-up."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    """Round a Decimal or numeric to an integer (whole cents), half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
