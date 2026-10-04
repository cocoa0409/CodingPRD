"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock default on server startup (PRD §2.4).
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Confidence score gate (publication + auto-suspend).
    "PUBLISH_GATE": 0.25,
    "VOLUME_SATURATION": 30,
    "W_VOLUME": 0.5,
    "W_DIVERSITY": 0.3,
    "W_RECENCY": 0.2,
    # Trailing reference window.
    "WINDOW_DAYS": 90,
    "RECENT_DAYS": 30,
    "WEIGHT_RECENT": 2,
    "WEIGHT_OLD": 1,
    # Tier multipliers applied to reference_price_cents.
    "TRADE_IN_MULT": 0.87,
    "PRIVATE_PARTY_MULT": 0.95,
    "RETAIL_MULT": 1.08,
    # Condition tier catalog multipliers.
    "TIER_EXCELLENT": 1.10,
    "TIER_GOOD": 1.00,
    "TIER_FAIR": 0.85,
    "TIER_POOR": 0.70,
    # Mileage / option adjustment.
    "FIRST_SLAB_MILES": 10000,
    "FIRST_RATE_PER_MILE_CENTS": 0.15,
    "SECOND_RATE_PER_MILE_CENTS": 0.10,
    "OPTION_CAP_PCT": 0.08,
    "OFFER_FLOOR_PCT": 0.20,
    "INSPECT_CAP_FLOOR": 0.90,
    "DEFAULT_ANNUAL_EXPECTED_MILES": 10000,
    # Licensing.
    "FREE_TIER_EVENTS": 1000,
    "FEE_PER_EVENT_CENTS": 4,
    "QUOTA_MIN": 1,
    "QUOTA_MAX": 100000,
    # Dispute settlement credit.
    "MAX_CREDIT_CENTS": 25000,
    "CREDIT_PCT": 0.02,
    # Source suspension.
    "SUSPEND_AFTER_CONSECUTIVE_REJECTIONS": 5,
    # Offer expiry.
    "OFFER_EXPIRY_DAYS": 7,
    # Weekly cadence minimum gap.
    "CADENCE_GAP_DAYS": 7,
    # Input shape bounds.
    "YEAR_MIN": 1990,
    "YEAR_MAX": 2030,
    "PCT_ADJUSTMENT_MIN": -0.50,
    "PCT_ADJUSTMENT_MAX": 0.50,
    "ITEMS_MIN": 1,
    "ITEMS_MAX": 500,
    "ITEM_PRICE_MIN": 100,
    "ITEM_PRICE_MAX": 100000000,
    "OPTION_CREDIT_MIN": 1,
    "OPTION_CREDIT_MAX": 1000000,
}
