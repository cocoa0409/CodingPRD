"""Domain constants for the Healthcare Claims Clearinghouse API."""

# Default logical-clock instant the server boots at.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# Credential validity windows commonly used in setups.
CREDENTIAL_EFFECTIVE_AT = "2026-09-01T00:00:00Z"
CREDENTIAL_EXPIRES_AT = "2027-09-01T00:00:00Z"

# Volume-tier floors (trailing three finalized periods, inclusive).
TIER_2_FLOOR = 10000
TIER_3_FLOOR = 100000

# Pagination defaults.
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# Billing period used by most metering scenarios.
PERIOD_2026_09 = "2026-09"

# Common X12 service type code for general benefits.
SERVICE_TYPE_GENERAL_BENEFITS = "30"
