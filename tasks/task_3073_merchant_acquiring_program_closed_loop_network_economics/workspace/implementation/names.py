"""Deterministic name mappings.

The PRD enumerates card products but never fixes the monetary figure attached to
each one, the membership reward points added on activation, or the spend
threshold that separates the lounge tiers.  These maps are the single place
those figures live, so the behaviour is deterministic and observable.  Card
products are mapped to the canonical published figures; the maps could be walked
in the opposite direction without changing any structural contract.
"""

CARD_PRODUCT_RANK = {
    "GREEN": 0,
    "GOLD": 1,
    "PLATINUM": 2,
    "CENTURION": 3,
}

RANK_CARD_PRODUCT = {rank: name for name, rank in CARD_PRODUCT_RANK.items()}

CARD_PRODUCT_ANNUAL_FEE_CENTS = {
    "GREEN": 15000,
    "GOLD": 25000,
    "PLATINUM": 69500,
    "CENTURION": 1000000,
}

CARD_PRODUCT_MEMBERSHIP_POINTS = {
    "GREEN": 1000,
    "GOLD": 2500,
    "PLATINUM": 5000,
    "CENTURION": 10000,
}

# Trailing lowest-month spend (in cents) at or above which a member is granted
# the premium lounge tier.  The card product selects the rank, the trailing
# spend selects the tier.
LOUNGE_CENTURION_TIER_MIN_SPEND_CENTS = 500000
LOUNGE_PREMIUM_TIER_MIN_SPEND_CENTS = 250000

# Tier order used by the volume-weighted final discount rate.
VOLUME_TIER_ORDER = ("ACTIVITY", "FIXED", "LOW")


def lounge_tier_for(card_product, trailing_spend_cents, member_status="ACTIVE"):
    """NONE | STANDARD | UNLIMITED from the card product and the trailing spend."""
    if member_status == "DELINQUENT":
        return "NONE"
    rank = CARD_PRODUCT_RANK.get(card_product, 0)
    spend = trailing_spend_cents or 0
    if rank >= CARD_PRODUCT_RANK["CENTURION"]:
        return "STANDARD" if spend < LOUNGE_CENTURION_TIER_MIN_SPEND_CENTS else "UNLIMITED"
    if rank >= CARD_PRODUCT_RANK["PLATINUM"]:
        return "STANDARD" if spend < LOUNGE_PREMIUM_TIER_MIN_SPEND_CENTS else "UNLIMITED"
    return "NONE"