"""Domain thresholds and test defaults — numeric constants from the PRD's calculations."""

COMPONENT_CREDITS = {
    "1040_SIMPLE": 7500,
    "1040_ITEMIZED": 15000,
    "1040_BUSINESS": 30000,
    "1040_MULTI_STATE": 20000,
    "AMENDED_RETURN": 12000,
    "PRIOR_YEAR_REVIEW": 8000,
}

TIER_MULTIPLIER = {
    "ASSOCIATE": 1.0,
    "SENIOR": 1.25,
    "MASTER": 1.5,
    "ENROLLED_AGENT": 1.75,
}

BASE_PREMIUM = {
    "STANDARD": 4900,
    "PLUS": 9900,
}

THRESHOLDS = {
    "SIMPLE_CAP": 15000,
    "STANDARD_CAP": 30000,
    "OK_THRESHOLD": 80,
    "WATCH_THRESHOLD": 60,
    "DEFECT_WEIGHT": 400,
    "CLAIM_WEIGHT": 300,
}

DAILY_RATE = 0.000273972602739726
ACCRUAL_MARKUP = 1.1

TEST_DEFAULTS = {
    "TAX_YEAR": 2025,
    "FUNDED_CENTS": 100_000_000,
    "DEFAULT_CLOCK": "2026-09-01T00:00:00Z",
}

# Named case-manager operator ids (opaque X-User-ID values) used to respect
# segregation of duties: the scoper cannot also resolve the same claim.
SCOPER_USER_ID = "cm-scoper-A"
RESOLVER_USER_ID = "cm-resolver-B"
