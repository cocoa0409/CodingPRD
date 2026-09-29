"""Money arithmetic.  Integer cents everywhere, round half up (PRD 2.7)."""

from decimal import Decimal, ROUND_HALF_UP

ONE = Decimal(1)


def _dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal / number to a whole integer, half away from zero."""
    return int(_dec(value).quantize(ONE, rounding=ROUND_HALF_UP))


def pct_of(cents, pct):
    """round_half_up(cents * pct / 100) in whole cents."""
    return round_half_up(_dec(cents) * _dec(pct) / Decimal(100))


def half_of(cents):
    """round_half_up(cents * 0.5) in whole cents."""
    return round_half_up(_dec(cents) * Decimal("0.5"))


# --- self-pay discount tiers (PRD 3.5) --------------------------------------
TIER_1_CEILING_CENTS = 10000
TIER_2_CEILING_CENTS = 20000


def self_pay_tier_pct(subtotal_cents):
    if subtotal_cents < TIER_1_CEILING_CENTS:
        return 0
    if subtotal_cents < TIER_2_CEILING_CENTS:
        return 10
    return 15


def self_pay_total(subtotal_cents):
    """Tier from the PRE-discount subtotal; one rounded aggregate discount."""
    tier_pct = self_pay_tier_pct(subtotal_cents)
    discount = pct_of(subtotal_cents, tier_pct)
    return subtotal_cents - discount
