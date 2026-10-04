"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # PRD §2.6: dispute_credit_cents strictly less than -100000 -> ON_HOLD.
    "POSTURE_ON_HOLD_DEBT_CENTS": -100000,
    # PRD §3.3: state-cooperative cap on the effective MFC discount.
    "STATE_COOP_MFC_CAP": 0.25,
    # PRD §3.6: teaming surcharge constants.
    "SURCHARGE_RATE": 0.30,
    "SURCHARGE_FLOOR_PCT": 0.015,
    "SURCHARGE_CAP_CENTS": 500000,
    # PRD §3.9: audit materiality threshold in cents ($2,500.00).
    "AUDIT_MATERIALITY_CENTS": 250000,
    # PRD §2.3: pagination defaults and bounds.
    "PAGE_DEFAULT_LIMIT": 10,
    "PAGE_MIN_LIMIT": 1,
    "PAGE_MAX_LIMIT": 100,
}

# PRD §3.7: the fixed statutory TAA designated-countries list.
TAA_DESIGNATED_COUNTRIES = [
    "US", "CA", "MX", "GB", "DE", "FR", "JP", "AU", "IL", "KR", "NO", "CH",
]

TEST_DEFAULTS = {
    "MFC_DISCOUNT_PCT": 0.20,
    "SMALL_BUSINESS_GOAL_PCT": 0.10,
    "PRODUCT_SCOPE": ["SW-"],
    "SCOPE_TIERS": ["FEDERAL"],
    "TERM_START": "2026-01-01T00:00:00Z",
    "TERM_END": "2027-01-01T00:00:00Z",
    "CEILING_CENTS": 100000000,
    "WINDOW_START": "2026-01-01T00:00:00Z",
    "WINDOW_END": "2027-01-01T00:00:00Z",
    # PRD §2.5: the logical clock initializes at 2026-09-01T00:00:00Z.
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "CLOCK_TEST": "2026-10-01T00:00:00Z",
}
