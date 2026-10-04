"""Domain thresholds — the fixed constants the monetary and temporal rules use."""

THRESHOLDS = {
    # Monetary constants
    "AFTERCARE_KIT_FEE_CENTS": 1200,
    "AFTERCARE_RETAIN_FLOOR_CENTS": 500,
    "MODERATE_RATE": 0.50,
    "SEVERE_RATE": 0.75,
    "TIER_1_FLOOR_CENTS": 4000,
    "TIER_2_FLOOR_CENTS": 8000,
    "TIER_1_RATE": 0.10,
    "TIER_2_RATE": 0.15,
    "RE_PIERCE_RATE": 0.20,
    "SITE_MINIMUM_CENTS": 1500,
    "DOWNGRADE_RATE": 0.25,
    "MAX_SURCHARGE_CENTS": 2500,
    "PER_CONTRAINDICATION_CENTS": 350,
    "PER_EXTRA_SITE_CENTS": 200,
    # Store posture constants
    "RESTRICTION_INCIDENT_THRESHOLD": 3,
    "RESTRICTION_FAILED_CYCLE_THRESHOLD": 1,
    "FREEZE_FAILED_CYCLE_THRESHOLD": 2,
    # Eligibility scoring constants
    "BASE_SCORE": 100,
    "SCORE_FLOOR": 0,
    "SCORE_CEILING": 100,
    "COMPLETION_BONUS": 8,
    # Temporal constants
    "RECERTIFICATION_LEAD_DAYS": 30,
    "CHECK_IN_LEAD_MINUTES": 30,
    "CONSENT_VALIDITY_DAYS": 30,
}

# Site factors used by the site-complexity surcharge.
SITE_FACTORS = {
    "LOBE": 1.0,
    "UPPER_LOBE": 1.2,
    "HELIX": 1.5,
    "TRAGUS": 1.6,
    "INDUSTRIAL": 2.2,
    "NOSTRIL": 1.4,
}

# Base values (cents) used by the per-site downgrade credit.
SITE_BASE_VALUE_CENTS = {
    "LOBE": 2000,
    "UPPER_LOBE": 3000,
    "HELIX": 5200,
    "TRAGUS": 4300,
    "INDUSTRIAL": 7000,
    "NOSTRIL": 4600,
}

TEST_DEFAULTS = {
    "JURISDICTION_STATE_CODE": "IL",
    "STORE_NAME": "Chicago Loop",
    "PIERCER_NAME": "Rae Novak",
    "CUSTOMER_NAME": "Dana Whitfield",
    "CUSTOMER_DOB": "1996-02-02T00:00:00Z",
    "BASE_FEE_CENTS": 4500,
    "CLOCK_START": "2026-09-01T00:00:00Z",
}

# The logical clock's value before any call.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"