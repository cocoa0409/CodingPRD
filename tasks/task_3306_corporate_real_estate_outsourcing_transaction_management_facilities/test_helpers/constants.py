"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

THRESHOLDS = {
    # Commission credits / tiered fee (PRD §2.9)
    "TIER_RATE_LOW_CENTS": 145,
    "TIER_RATE_MID_CENTS": 118,
    "TIER_RATE_HIGH_CENTS": 96,
    "TIER_LOW_MAX_SQFT": 250_000,
    "TIER_MID_MAX_SQFT": 750_000,
    "COMMISSION_CREDIT_FLOOR_CENTS": 10_000,
    # Savings realisation benchmark (PRD §3.3)
    "MARKET_BENCHMARK_CENTS_PER_SQFT": 1750,
    # KPI adjustment (PRD §3.7)
    "SERVICE_LEVEL_SHORTFALL_BASE_CENTS": 3_000_000,
    "SAVINGS_SHORTFALL_BASE_CENTS": 2_000_000,
    "GAINSHARE_RATE_BPS": 2500,
    # KPI escalation margins (PRD §2.11)
    "BPS_ESCALATION_MARGIN": 500,
    "CENTS_ESCALATION_MARGIN": 500_000,
    # Scorecard weights (PRD §3.7)
    "W_QUALITY_COMPLETE": 6000,
    "W_RESPONSE_COMPLETE": 4000,
    "W_QUALITY_BASIC": 5000,
    "W_RESPONSE_BASIC": 5000,
    "COMPOSITE_CEILING_BPS": 10_000,
    # Consolidation savings (PRD §3.6)
    "COST_INFLATION_CAP": 1.10,
    # Broker commission split (PRD §3.4)
    "SENIOR_BROKER_SHARE_BPS": 6000,
    "STANDARD_BROKER_SHARE_BPS": 4500,
    "PRIOR_BASE_LIMIT_BPS": 300,
    # Approval banding (PRD §2.11)
    "LEVEL_MANAGER_MAX_CENTS": 25_000_000,
    "LEVEL_DIRECTOR_MAX_CENTS": 75_000_000,
    # Governance posture rollup (PRD §2.4)
    "RESTRICTED_FAILED_THRESHOLD": 2,
    "WATCH_ESCALATION_THRESHOLD": 1,
    # Completion (PRD §3.8)
    "COMPLETION_COMPLETE_BPS": 10_000,
    # Premises cooldown (PRD §2.10)
    "PREMISES_COOLDOWN_DAYS": 30,
    # Cooling off (PRD §3.7)
    "COOLING_OFF_HOURS": 72,
    # Vendor KPI track (PRD §3.5)
    "LEVEL_C_MIN_OCCUPIED_SITES": 1,
    # Pagination (PRD §2.3)
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
}

TEST_DEFAULTS = {
    "PORTFOLIO_SQFT": 400_000,
    "PLATFORM_TIER": "ENTERPRISE",
    # A 400,000 sqft ENTERPRISE account: gross fee = 118 * 400000 = 47,200,000 cents.
    "GROSS_FEE_CENTS": 47_200_000.0,
    "PRIOR_RENT_CENTS": 74_000_000,
    "PROPOSED_RENT_CENTS": 68_000_000,
    "TERM_MONTHS": 60,
    "THIRD_PARTY_COMMISSION_CENTS": 1_850_000,
    "LEASED_SQFT": 40_000,
    "MARKET_CODE": "SFO",
    "PROPERTY_ADDRESS": "1 Market St",
    "LEASE_START": "2026-10-01T00:00:00Z",
    "LEASE_END": "2027-10-01T00:00:00Z",
    "DEFAULT_CLOCK": "2026-09-01T00:00:00Z",
}

# The account clock's fixed default before any call (PRD §3.9).
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"