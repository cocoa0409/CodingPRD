"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Quote TTL (PRD §3.3): expires_at = quoted_at + 30 days
    "QUOTE_TTL_DAYS": 30,
    # Telematics up-front participation discount in the DIRECT channel (PRD §3.5)
    "DIRECT_TELEMATICS_UPFRONT_PCT": 0.15,
    # Telematics score tiers (PRD §3.5): >= 90 -> 0.20; 70..89 -> 0.10; < 70 -> 0.00
    "TELEMATICS_TIER_HIGH_MIN_SCORE": 90,
    "TELEMATICS_TIER_MID_MIN_SCORE": 70,
    # Policy term (PRD §3.3)
    "TERM_DAYS": 365,
    # Trailing loss-ratio window (PRD §3.7)
    "TRAILING_WINDOW_DAYS": 365,
    # Bonus pool eligibility gate defaults (PRD §3.7)
    "LOSS_RATIO_THRESHOLD_DEFAULT": 0.70,
    "GROWTH_THRESHOLD_PCT_DEFAULT": 0.05,
    # First-year growth definition (PRD §3.7): prior-12m earned 0 => growth 1.0
    "FIRST_YEAR_GROWTH": 1.0,
    # Feed publication minimum gap between sibling windows (PRD §3.2)
    "FEED_GAP_HOURS": 24,
}

TEST_DEFAULTS = {
    # Clock instant most fixtures start from
    "CLOCK_START": "2026-01-01T00:00:00Z",
    # Standard product rate table pieces used across tests
    "LIABILITY_BASIC_RATE_CENTS": 50000,
    "COLLISION_STANDARD_RATE_CENTS": 90000,
    # Standard agent / consumer descriptors
    "AGENCY_NAME": "Hill Country Insurance",
    "PRINCIPAL_NAME": "A. Reyes",
    "STATE_CODE": "TX",
    "RATER_CODE": "PL-RATER",
    "FEED_FORMAT_VERSION": "v4.2",
    # Flat 10% single-tier schedule used in commission fixtures
    "FLAT_TIER_RATE_PCT": 0.10,
}
