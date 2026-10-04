"""Domain thresholds and defaults from the PRD business rules (§3)."""

THRESHOLDS = {
    # Store default low-stock threshold (PRD §3.1)
    "DEFAULT_LOW_STOCK_THRESHOLD": 5,
    # Order pricing (PRD §3.3)
    "FOOD_MEMBER_DISCOUNT_PCT": 0.10,
    "POINTS_REDEMPTION_CAP_PCT": 0.20,
    # Delivery fee quote (PRD §3.5)
    "ZONE_BASE_A": 4900,
    "ZONE_BASE_B": 7900,
    "ZONE_BASE_C": 12900,
    "WEIGHT_TIER1_KG": 50,
    "WEIGHT_TIER2_KG": 150,
    "TIER2_FLAT_CENTS": 2500,
    "OVERAGE_CENTS_PER_KG": 15,
    "WALKUP_HIGH_FEE_CENTS": 1200,
    "WALKUP_HIGH_MAX_CARTON_KG": 40,
    "MEMBER_FEE_DISCOUNT_PCT": 0.20,
    # Assembly (PRD §3.6)
    "BILLING_CAP_FACTOR": 1.5,
    "CREW_BUFFER_MINUTES": 30,
    # Spare-part claims (PRD §3.7)
    "MAX_CLAIMS_365D": 3,
    "MAX_CLAIM_VALUE_365D_CENTS": 3000,
    # Returns (PRD §3.8)
    "NO_RECEIPT_PENALTY_PCT": 0.10,
    "GRADE_FACTOR_LIKE_NEW": 1.00,
    "GRADE_FACTOR_OPEN_BOX": 0.85,
    "GRADE_FACTOR_DAMAGED": 0.50,
    "GRADE_FACTOR_SCRAP": 0.00,
    # Reservations (PRD §3.4)
    "RESERVATION_TTL_HOURS": 24,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "STORE_NAME": "Renton",
    "STORE_CODE_PREFIX": "ST-",
    "LOW_STOCK_THRESHOLD": 5,
    "UNKNOWN_ORDER_ID": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
}
