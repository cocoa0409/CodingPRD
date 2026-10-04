"""Domain thresholds and defaults from the Scan-Go Checkout PRD."""

# Grams in one pound (weighted-item gross computation).
LB_GRAMS = 454

# Cash rewards: PLUS members accrue 2% of qualifying spend (integer floor).
REWARD_RATE = 2

# Documented club defaults applied when the creation payload omits overrides.
CLUB_DEFAULTS = {
    "scan_go_enabled": True,
    "allow_offline_payment": False,
    "connectivity_posture": "ONLINE",
    "lp_unscanned_threshold": 2,
    "lp_suspend_strikes": 3,
    "staging_slot_capacity": 2,
    "receipt_code_ttl_minutes": 30,
    "intercept_ttl_minutes": 10,
}

# Minimum age (in years) for ALCOHOL/TOBACCO intercept approval.
RESTRICTED_MIN_AGE = 21

# The logical clock reads exactly this instant at server startup.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
# A normal-hours instant used by most setups (12:00 UTC >= open_minute 600).
NOON_ISO = "2026-09-01T12:00:00Z"
# An early-window instant for a club with open 600 / early 480 (09:00 UTC).
EARLY_ISO = "2026-09-01T09:00:00Z"

TEST_DEFAULTS = {
    "CLUB_NAME": "Test Club",
    "OPEN_MINUTE": 600,
    "EARLY_START_MINUTE": 480,
    "EXIT_MODE": "RECEIPT_CODE",
    "UNIT_PRICE_CENTS": 500,
    "WEIGHTED_PRICE_CENTS": 250,
    "BIRTH_YEAR": 1990,
    "WINDOW_START_ISO": "2026-09-01T14:00:00Z",
    "WINDOW_END_ISO": "2026-09-01T15:00:00Z",
}

# A well-formed UUID that never exists in the database under test.
UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
