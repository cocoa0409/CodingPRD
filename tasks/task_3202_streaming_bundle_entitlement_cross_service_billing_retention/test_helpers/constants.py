"""Domain thresholds — numeric constants from the PRD."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Logical clock startup default (PRD §2.5).
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Billing period lengths (PRD §2.10).
PLATFORM_PERIOD_DAYS = 30
THIRD_PARTY_PERIOD_DAYS = 31

# Dunning budget (PRD §2.10).
GRACE_DAYS = 7
MAX_RENEWAL_FAILURES = 3

# Effective-price cap and floor (PRD §3.5).
MAX_DISCOUNT_PCT = 60
MIN_PRICE_CENTS = 100

# Maturity rank ladder (PRD §3.3).
MATURITY_RANK = {
    "TV_Y": 0,
    "TV_G": 1,
    "TV_PG": 2,
    "TV_14": 3,
    "TV_MA": 4,
}

TEST_DEFAULTS = {
    "PLATFORM_REFERENCE": "platform",
}
