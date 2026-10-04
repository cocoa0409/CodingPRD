"""Domain thresholds and shared defaults.

Logical clock default before any administrative set call, per the PRD:
exactly 2026-09-01T00:00:00Z.
"""

# Logical clock
CLOCK_START = "2026-09-01T00:00:00Z"

# Tier discounts (percent off retail) for member pricing.
TIER_DISCOUNT_PCT = {"BRONZE": 5, "SILVER": 10, "GOLD": 15}

# Pacing constants.
PACE_WINDOW_DAYS = 7
MIN_SELLING_DAYS = 3

# Refund window in days (boundary inclusive).
REFUND_WINDOW_DAYS = 14

# Minimum comparison-price premium over retail under the was/now window rule.
MIN_ANCHOR_PREMIUM_PCT = 20

# Grade weighting factors for the final landed-cost variant.
GRADE_B_FACTOR = 0.8
GRADE_C_FACTOR = 0.6

# Jurisdiction payload defaults used across the suite.
JURISDICTION_CA = {
    "jurisdiction_code": "CA",
    "comparison_rule": "WAS_NOW_WINDOW",
    "window_days": 90,
    "required_offer_days": 30,
    "max_advertised_discount_pct": 70,
    "member_discount_cap_pct": 30,
}
