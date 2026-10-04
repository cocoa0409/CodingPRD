"""Pinned integer-cent arithmetic (PRD sections 2.8 and 3.8).

Rounding is always half-up, applied to the nearest whole cent, and it is applied
to exactly the step the governing rule names -- never to a running total.
"""

from decimal import Decimal, ROUND_HALF_UP

# Stream creator rates -- the royalty share split (PRD section 3.8).
AD_CREATOR_RATE = Decimal("0.55")
MEMBERSHIP_CREATOR_RATE = Decimal("0.70")
SUPER_CHAT_CREATOR_RATE = Decimal("0.70")
SHOPPING_CREATOR_RATE = Decimal("0.60")

STREAM_CREATOR_RATES = {
    "AD": AD_CREATOR_RATE,
    "MEMBERSHIP": MEMBERSHIP_CREATOR_RATE,
    "SUPER_CHAT": SUPER_CHAT_CREATOR_RATE,
    "SHOPPING": SHOPPING_CREATOR_RATE,
}

STREAM_TYPES = ("AD", "MEMBERSHIP", "SUPER_CHAT", "SHOPPING")

NETWORK_FEE_RATE = Decimal("0.03")
SPLITTER_SHARE_RATE = Decimal("0.55")
HOLDER_KEEP_RATE = Decimal("0.45")
MEMBER_REVENUE_UNIT_CENTS = 25

PAYMENT_THRESHOLD_DEFAULT_CENTS = 10000
STRIKE_LIFETIME_DAYS = 90
DISPUTE_WINDOW_DAYS = 30
APPEAL_LOCKOUT_DAYS = 14

MEMBER_PAYOUT_SELECTOR_VERSION = 1


def half_up(value):
    """Round a Decimal (or int/str) to the nearest whole cent, half-up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def split_amount(gross_cents, rate):
    """Per-record split: creator share rounds, partner share is the remainder.

    `creator_share_cents + partner_share_cents == gross_revenue_cents` exactly.
    """
    creator = half_up(Decimal(int(gross_cents)) * Decimal(rate))
    partner = int(gross_cents) - creator
    return creator, partner


def withholding_rate_for(country_code, tax_treaty, tax_tin_status):
    """PRD section 3.11 -- tax documentation first, jurisdiction second."""
    if tax_tin_status == "TIN_MISSING":
        return Decimal("0.30")
    country = (country_code or "").upper()
    if country == "US":
        return Decimal("0.00")
    if tax_treaty:
        return Decimal("0.15")
    return {
        "GB": Decimal("0.20"),
        "DE": Decimal("0.26"),
        "IN": Decimal("0.24"),
        "BR": Decimal("0.24"),
    }.get(country, Decimal("0.24"))


def format_rate(rate):
    """A three-decimal fraction, emitted as a JSON number."""
    return float(Decimal(rate).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def floor_confidence(value):
    """match_confidence is recorded to three decimals, floored (PRD 3.4)."""
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding="ROUND_FLOOR"))