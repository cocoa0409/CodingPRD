"""Domain thresholds and derived-value helpers — numeric constants from the PRD
formulas (§3.3 tiered exchange, §3.7 marketplace split, §3.8 engagement payout,
§3.12 DevEx ladder and withholding)."""


# --- Tiered fiat -> Robux exchange (PRD §3.3) ---------------------------------
# Bounds are cumulative cut points: tier 1 covers the first 999 cents, tier 2
# the next 4000 (1000..4999), tier 3 the next 15000 (5000..19999), tier 4 the rest.
CURRENCY_TIERS = [
    # (tier_start_after_cents, tier_end_at_cents, robux_per_cent)
    (0, 999, 0.80),
    (999, 4999, 0.90),
    (4999, 19999, 1.00),
    (19999, None, 1.10),
]

MARKETPLACE_FEE_PCT = 0.30
RESALE_FLOOR_PCT = 0.5

# --- Engagement payout per-hour rates keyed on age rating (PRD §3.8) ----------
ENGAGEMENT_RATE_PER_HOUR = {
    "ALL": 2,
    "NINE_PLUS": 3,
    "THIRTEEN_PLUS": 4,
    "SEVENTEEN_PLUS": 5,
}

# --- DevEx progressive ladder, usd cents per robux (PRD §3.12) ----------------
DEVEX_BRACKETS = [
    (0, 30000, 0.35),
    (30000, 100000, 0.38),
    (100000, 1000000, 0.40),
    (1000000, None, 0.42),
]

# --- DevEx withholding (PRD §3.12) ---------------------------------------------
W9_WITHHOLDING_BRACKETS = [
    (0, 10000, 0.00),
    (10000, 50000, 0.10),
    (50000, 200000, 0.24),
    (200000, None, 0.30),
]
W8_FLAT_WITHHOLDING_RATE = 0.30

# --- DevEx eligibility thresholds (PRD §3.2) ------------------------------------
DEVEX_MIN_ACCOUNT_AGE_DAYS = 30
DEVEX_MIN_EARNED_ROBUX = 30000
DEVEX_MIN_REQUEST_ROBUX = 30000

# --- Resale account-age gate (PRD §3.6) -------------------------------------------
RESALE_MIN_ACCOUNT_AGE_DAYS = 7


def round_half_up(x: float) -> int:
    """Round half up to a whole number (PRD §2.7)."""
    import math

    return int(math.floor(x + 0.5))


def expected_credited_robux(fiat_amount_cents: int) -> int:
    """Tiered exchange with round-half-up applied once to the final aggregate."""
    total = 0.0
    for lo, hi, rate in CURRENCY_TIERS:
        if fiat_amount_cents > lo:
            upper = fiat_amount_cents if hi is None else min(fiat_amount_cents, hi)
            total += (upper - lo) * rate
    return round_half_up(total)


def expected_devex_usd_payout_cents(requested_robux: int) -> int:
    """Progressive DevEx ladder, round half up once at the end (PRD §3.12)."""
    total = 0.0
    for lo, hi, rate in DEVEX_BRACKETS:
        if requested_robux > lo:
            upper = requested_robux if hi is None else min(requested_robux, hi)
            total += (upper - lo) * rate
    return round_half_up(total)


def expected_withholding_cents(usd_payout_cents: int, form_type: str) -> int:
    """Progressive W9 withholding, or flat 30% for W8BEN/W8BENE (PRD §3.12)."""
    if form_type in ("W8BEN", "W8BENE"):
        return round_half_up(usd_payout_cents * W8_FLAT_WITHHOLDING_RATE)
    total = 0.0
    for lo, hi, rate in W9_WITHHOLDING_BRACKETS:
        if usd_payout_cents > lo:
            upper = usd_payout_cents if hi is None else min(usd_payout_cents, hi)
            total += (upper - lo) * rate
    return round_half_up(total)


def expected_marketplace_split_nonlimited(price_robux: int):
    """Returns (platform_fee_robux, creator_credit_robux) for non-limited sales."""
    fee = round_half_up(price_robux * MARKETPLACE_FEE_PCT)
    return fee, price_robux - fee


def expected_resale_waterfall(price_robux: int, royalty_pct: int):
    """Returns (platform_fee, royalty_to_original_creator, reseller_credit).

    Fee-first, royalty-second on the post-fee gross seller share (PRD §3.7).
    """
    fee = round_half_up(price_robux * MARKETPLACE_FEE_PCT)
    gross_seller = price_robux - fee
    royalty = round_half_up(gross_seller * royalty_pct / 100)
    return fee, royalty, gross_seller - royalty


def expected_engagement_payout(minutes_engaged: int, age_rating: str) -> int:
    """floor(minutes / 60) * per-hour rate for the experience's rating (PRD §3.8)."""
    return (minutes_engaged // 60) * ENGAGEMENT_RATE_PER_HOUR[age_rating]


def expected_resale_floor(item_price_robux: int) -> int:
    """floor(item.price_robux * 0.5) — the inclusive resale ask floor (PRD §3.6)."""
    return int(item_price_robux * RESALE_FLOOR_PCT)
